"""Signed capture notifications; activation re-fetches authoritative provider data."""
import hashlib
import hmac
import json
from types import SimpleNamespace
from uuid import UUID
from fastapi import HTTPException


async def handle_capture(body, signature, secret, gateway, activate):
    if not secret or not gateway:
        raise HTTPException(503, 'Payment recovery is not configured.')
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ''):
        raise HTTPException(400, 'Invalid webhook signature.')
    try:
        event = json.loads(body)
        if event.get('event') != 'payment.captured':
            return {'status': 'ignored'}
        payment = event['payload']['payment']['entity']
        order_id, payment_id = payment['order_id'], payment['id']
        if not isinstance(order_id, str) or not order_id.startswith('order_'):
            return {'status': 'ignored'}
        if not isinstance(payment_id, str) or not payment_id.startswith('pay_'):
            raise ValueError('Invalid payment ID')
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(400, 'Invalid webhook payload.') from None
    try:
        order = gateway.order.fetch(order_id)
        notes = order.get('notes') or {}
        # The same merchant account may serve other applications.
        if notes.get('app') != 'arivora':
            return {'status': 'ignored'}
        user_id = str(UUID(notes['user_id']))
        return await activate(SimpleNamespace(razorpay_order_id=order_id,
                                             razorpay_payment_id=payment_id), user_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, 'Payment activation is temporarily unavailable.') from None
