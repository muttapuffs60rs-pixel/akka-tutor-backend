import ast
import asyncio
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from fastapi import HTTPException, Depends
from database_reliability import retry_database


class TopupPaymentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        nodes = [n for n in ast.parse((Path(__file__).parents[1]/'main.py').read_text(encoding='utf-8')).body
                 if getattr(n, 'name', '') in ('verify_payment', 'create_order')]
        for n in nodes:
            n.decorator_list = []
        self.gateway = Mock()
        self.gateway.order.fetch.return_value = {'amount': 4900, 'currency': 'INR',
            'notes': {'tier_id': 'topup_49', 'user_id': 'student'}}
        self.gateway.payment.fetch.return_value = {'amount': 4900, 'currency': 'INR',
            'order_id': 'order_test', 'status': 'captured'}
        self.db = Mock()
        self.db.rpc.return_value.execute.return_value.data = {'credits': 200000}
        env = dict(globals(), razorpay_client=self.gateway, supabase=self.db,
            razorpay=SimpleNamespace(errors=SimpleNamespace(SignatureVerificationError=type('BadSignature',(Exception,),{}))),
            VerifyPaymentRequest=object, OrderRequest=object, get_current_user=lambda: None,
            TOPUP_PACKS={'topup_49': {'amount':49,'days':30,'credits':200000}}, TIER_PRICES={})
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'main.py','exec'),env)
        self.verify = env['verify_payment']
        self.create = env['create_order']
        self.request = SimpleNamespace(razorpay_order_id='order_test',razorpay_payment_id='pay_test',razorpay_signature='verified-by-mock')

    async def test_captured_payment_grants_pack_without_changing_subscription(self):
        result = await self.verify(self.request,'student')
        self.assertEqual(result['topup']['credits'],200000)
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

    async def test_topup_orders_stay_disabled_until_payment_launch(self):
        with self.assertRaises(HTTPException) as error:
            await self.create(SimpleNamespace(tier_id='topup_49'),'student')
        self.assertEqual(error.exception.status_code,503)
        self.gateway.order.create.assert_not_called()
