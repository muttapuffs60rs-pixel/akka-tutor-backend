import hashlib
import hmac
import json
import unittest
from unittest.mock import Mock, AsyncMock
from fastapi import HTTPException
from payment_webhook import handle_capture


class PaymentWebhookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.gateway = Mock()
        self.uid = '00000000-0000-4000-8000-000000000001'
        self.gateway.order.fetch.return_value = {'notes': {'app': 'arivora', 'user_id': self.uid}}
        self.activate = AsyncMock(return_value={'status': 'success'})
        self.body = json.dumps({'event':'payment.captured', 'payload':{'payment':{'entity':{'id':'pay_synthetic','order_id':'order_synthetic'}}}}).encode()

    async def send(self, body=None, signature=None):
        body = self.body if body is None else body
        signature = signature if signature is not None else hmac.new(b'synthetic', body, hashlib.sha256).hexdigest()
        return await handle_capture(body, signature, 'synthetic', self.gateway, self.activate)

    async def test_signed_capture_uses_provider_order_owner(self):
        self.assertEqual(await self.send(), {'status':'success'})
        request, owner = self.activate.call_args.args
        self.assertEqual(owner, self.uid)
        self.assertEqual(request.razorpay_payment_id, 'pay_synthetic')
        self.assertEqual(request.razorpay_order_id, 'order_synthetic')

    async def test_bad_signature_never_fetches_or_activates(self):
        with self.assertRaises(HTTPException) as error:
            await self.send(signature='invalid')
        self.assertEqual(error.exception.status_code, 400)
        self.gateway.order.fetch.assert_not_called()
        self.activate.assert_not_called()

    async def test_other_merchant_app_is_ignored(self):
        self.gateway.order.fetch.return_value = {'notes':{'user_id':self.uid}}
        self.assertEqual(await self.send(), {'status':'ignored'})
        self.activate.assert_not_called()

    async def test_non_capture_event_is_ignored(self):
        self.assertEqual(await self.send(b'{"event":"payment.authorized"}'), {'status':'ignored'})
        self.activate.assert_not_called()

    async def test_provider_failure_retries_without_exposing_details(self):
        self.gateway.order.fetch.side_effect = Exception('private provider data')
        with self.assertRaises(HTTPException) as error:
            await self.send()
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn('private', error.exception.detail)
        self.activate.assert_not_called()

    async def test_uncaptured_payment_rejection_is_preserved(self):
        self.activate.side_effect = HTTPException(400,'Payment not captured')
        with self.assertRaises(HTTPException) as error:
            await self.send()
        self.assertEqual(error.exception.status_code,400)
