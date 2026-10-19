import ast
import os
import asyncio
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock
from fastapi import HTTPException, Depends
from database_reliability import retry_database


class TopupPaymentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from unittest.mock import patch
        env_patch = patch.dict(os.environ, {'RAZORPAY_KEY_ID': 'rzp_test_synthetic', 'RAZORPAY_KEY_SECRET': 'synthetic', 'RAZORPAY_LIVE_ENABLED': 'false'})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        nodes = [n for n in ast.parse((Path(__file__).parents[1]/'main.py').read_text(encoding='utf-8')).body
                 if getattr(n, 'name', '') in ('verify_payment', '_activate_captured_payment', 'create_order', 'payment_status')]
        for n in nodes:
            n.decorator_list = []
        self.gateway = Mock()
        self.gateway.order.fetch.return_value = {'amount': 4900, 'currency': 'INR',
            'notes': {'tier_id': 'topup_49', 'user_id': 'student'}}
        self.gateway.payment.fetch.return_value = {'amount': 4900, 'currency': 'INR',
            'order_id': 'order_test', 'status': 'captured'}
        self.db = Mock()
        self.db.rpc.return_value.execute.return_value.data = {'credits': 300000}
        env = dict(globals(), razorpay_client=self.gateway, supabase=self.db,
            razorpay=SimpleNamespace(errors=SimpleNamespace(SignatureVerificationError=type('BadSignature',(Exception,),{}))),
            VerifyPaymentRequest=object, OrderRequest=object, get_current_user=lambda: None,
            TOPUP_PACKS={'topup_49': {'amount':49,'days':30,'credits':300000}}, TIER_PRICES={'tier_999': {'amount':999,'days':30}})
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'main.py','exec'),env)
        self.verify = env['verify_payment']
        self.create = env['create_order']
        self.status = env['payment_status']
        self.request = SimpleNamespace(razorpay_order_id='order_test',razorpay_payment_id='pay_test',razorpay_signature='verified-by-mock')

    async def test_captured_payment_grants_pack_without_changing_subscription(self):
        result = await self.verify(self.request,'student')
        self.assertEqual(result['topup']['credits'],300000)
        self.db.table.assert_not_called()
        self.db.rpc.assert_called_once_with('grant_learning_credit_topup', {
            'target_user_id':'student','payment_id_value':'pay_test','order_id_value':'order_test'})

    async def test_wrong_user_cannot_redeem(self):
        with self.assertRaises(HTTPException) as error:
            await self.verify(self.request,'different-user')
        self.assertEqual(error.exception.status_code,403)
        self.db.rpc.assert_not_called()

    async def test_uncaptured_or_wrong_amount_or_currency_does_not_grant(self):
        valid=dict(self.gateway.payment.fetch.return_value)
        for changes in ({'status':'authorized'},{'amount':1},{'currency':'USD'},{'order_id':'other'}):
            self.gateway.payment.fetch.return_value = valid | changes
            with self.assertRaises(HTTPException):
                await self.verify(self.request,'student')
        self.db.rpc.assert_not_called()

    async def test_topup_rejects_ineligible_and_unavailable_eligibility(self):
        for eligibility in ({'eligible':False}, {}, None):
            self.db.rpc.return_value.execute.return_value.data=eligibility
            with self.assertRaises(HTTPException) as error:
                await self.create(SimpleNamespace(tier_id='topup_49'),'student')
            self.assertEqual(error.exception.status_code,403)
        self.gateway.order.create.assert_not_called()

    async def test_eligible_topup_creates_49_rupee_order(self):
        self.db.rpc.return_value.execute.return_value.data={'eligible':True}
        self.gateway.order.create.return_value={'id':'order_test','amount':4900,'currency':'INR'}
        result=await self.create(SimpleNamespace(tier_id='topup_49'),'student')
        self.assertEqual(result['amount'],4900)
        self.assertEqual(self.gateway.order.create.call_args.args[0]['amount'],4900)
        self.db.rpc.assert_called_once_with('learning_topup_eligibility',{'target_user_id':'student'})

    async def test_orders_use_server_prices_and_public_key(self):
        self.gateway.order.create.return_value = {'id':'order_test', 'amount':4900, 'currency':'INR'}
        from unittest.mock import patch
        with patch.dict(os.environ, {'RAZORPAY_KEY_ID':'rzp_test_public'}):
            for tier, price in [('tier_999',99900)]:
                result = await self.create(SimpleNamespace(tier_id=tier),'student')
                sent = self.gateway.order.create.call_args.args[0]
                self.assertEqual(sent['amount'],price)
                self.assertEqual(sent['notes'],{'app':'arivora','tier_id':tier,'user_id':'student'})
                self.assertEqual(result['key_id'],'rzp_test_public')

    async def test_live_requires_explicit_enablement_and_webhook_secret(self):
        from unittest.mock import patch
        for enabled, secret in [('false','secret'), ('true','')]:
            with patch.dict(os.environ, {'RAZORPAY_KEY_ID':'rzp_live_synthetic',
                                       'RAZORPAY_LIVE_ENABLED':enabled,
                                       'RAZORPAY_WEBHOOK_SECRET':secret}):
                self.assertFalse((await self.status())['checkout_enabled'])
                with self.assertRaises(HTTPException):
                    await self.create(SimpleNamespace(tier_id='tier_999'),'student')
        self.gateway.order.create.assert_not_called()

    async def test_explicit_live_configuration_creates_server_priced_order(self):
        from unittest.mock import patch
        self.gateway.order.create.return_value = {'id':'order_live','amount':99900,'currency':'INR'}
        with patch.dict(os.environ, {'RAZORPAY_KEY_ID':'rzp_live_synthetic',
                                   'RAZORPAY_LIVE_ENABLED':'true',
                                   'RAZORPAY_WEBHOOK_SECRET':'synthetic'}):
            self.assertTrue((await self.status())['live_charging_enabled'])
            result = await self.create(SimpleNamespace(tier_id='tier_999'),'student')
            self.assertEqual(result['key_id'],'rzp_live_synthetic')
            self.assertEqual(self.gateway.order.create.call_args.args[0]['amount'],99900)

    async def test_invalid_plan_is_400(self):
        with self.assertRaises(HTTPException) as error:
            await self.create(SimpleNamespace(tier_id='invalid'),'student')
        self.assertEqual(error.exception.status_code,400)
        self.gateway.order.create.assert_not_called()

    async def test_premium_requires_captured_correct_payment(self):
        self.gateway.order.fetch.return_value = {'amount':99900,'currency':'INR',
            'notes':{'tier_id':'tier_999','user_id':'student'}}
        valid = {'amount':99900,'currency':'INR','order_id':'order_test','status':'captured'}
        for changes in ({'amount':1},{'status':'authorized'},{'currency':'USD'},{'order_id':'other'}):
            self.gateway.payment.fetch.return_value = valid | changes
            with self.assertRaises(HTTPException) as error:
                await self.verify(self.request,'student')
            self.assertEqual(error.exception.status_code,400)
        self.db.table.assert_not_called()

    async def test_premium_activates_for_30_days(self):
        self.gateway.order.fetch.return_value = {'amount':99900,'currency':'INR',
            'notes':{'tier_id':'tier_999','user_id':'student'}}
        self.gateway.payment.fetch.return_value = {'amount':99900,'currency':'INR',
            'order_id':'order_test','status':'captured'}
        self.db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {'subscription_tier':'free','previous_tier':None}]
        result = await self.verify(self.request,'student')
        self.assertEqual(result['status'],'success')
        self.assertEqual(self.db.rpc.call_args.args[0], 'apply_verified_subscription')
        values=self.db.rpc.call_args.args[1]
        self.assertEqual(values['tier_value'],'tier_999')
        self.assertEqual(values['mode_value'],'test')
        from datetime import datetime, timedelta
        self.assertEqual(datetime.fromisoformat(values['expiry_value'])-
            datetime.fromisoformat(values['start_value']),timedelta(days=30))
        self.db.table.assert_not_called()

    async def test_provider_errors_do_not_expose_private_details(self):
        self.gateway.order.create.side_effect = RuntimeError('synthetic-private-provider-detail')
        with self.assertRaises(HTTPException) as error:
            await self.create(SimpleNamespace(tier_id='tier_999'), 'student')
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn('synthetic-private', error.exception.detail)
        self.gateway.order.fetch.side_effect = RuntimeError('synthetic-private-provider-detail')
        with self.assertRaises(HTTPException) as error:
            await self.verify(self.request, 'student')
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn('synthetic-private', error.exception.detail)
        self.db.table.assert_not_called()

    async def test_invalid_signature_does_not_activate(self):
        from unittest.mock import patch
        bad_signature = self.verify.__globals__['razorpay'].errors.SignatureVerificationError
        self.gateway.utility.verify_payment_signature.side_effect = bad_signature('synthetic-invalid')
        with self.assertRaises(HTTPException) as error:
            await self.verify(self.request, 'student')
        self.assertEqual(error.exception.status_code, 400)
        self.gateway.order.fetch.assert_not_called()
        self.db.table.assert_not_called()

    async def test_live_credentials_do_not_create_a_real_order(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'RAZORPAY_KEY_ID': 'rzp_live_synthetic'}):
            with self.assertRaises(HTTPException) as error:
                await self.create(SimpleNamespace(tier_id='tier_999'), 'student')
        self.assertEqual(error.exception.status_code, 503)
        self.gateway.order.create.assert_not_called()

    async def test_status_reports_mode_without_exposing_credentials(self):
        from unittest.mock import patch
        for prefix in ('rzp_test_', 'rzp_live_'):
            with patch.dict(os.environ, {'RAZORPAY_KEY_ID': prefix + 'synthetic',
                                        'RAZORPAY_KEY_SECRET': 'synthetic-private-value'}):
                status = await self.status()
            self.assertTrue(status['configured'])
            self.assertEqual(status['checkout_enabled'], prefix == 'rzp_test_')
            self.assertFalse(status['live_charging_enabled'])
            self.assertNotIn('synthetic', str(status))
