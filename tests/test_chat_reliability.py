import asyncio
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from chat_queue import ChatQueue, run_queued
from database_reliability import retry_database
import test_chat_cost_controls as chat_tests


class DatabaseRetryTests(unittest.TestCase):
    @patch('database_reliability.time.sleep')
    def test_disconnect_retries_but_application_errors_do_not(self, sleep):
        operation = Mock(side_effect=[httpx.RemoteProtocolError('disconnected'), 'ok'])
        self.assertEqual(retry_database(operation), 'ok')
        self.assertEqual(operation.call_count, 2)
        operation = Mock(side_effect=ValueError('invalid request'))
        with self.assertRaises(ValueError): retry_database(operation)
        self.assertEqual(operation.call_count, 1)
        operation = Mock(side_effect=httpx.ReadTimeout('timeout'))
        with self.assertRaises(httpx.ReadTimeout): retry_database(operation)
        self.assertEqual(operation.call_count, 3)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_bound_and_timeout_do_not_admit_excess_work(self):
        queue = ChatQueue(active=1, waiting=1, timeout=.05)
        lease = await queue.acquire()
        waiter = asyncio.create_task(queue.acquire())
        await asyncio.sleep(.001)
        with self.assertRaises(HTTPException) as caught: await queue.acquire()
        self.assertEqual(caught.exception.status_code, 503)
        with self.assertRaises(HTTPException): await waiter
        self.assertEqual(queue.waiting, 0)
        lease.release(); lease.release()
        self.assertEqual(queue.active, 0)
        next_lease = await queue.acquire(); next_lease.release()

    async def test_burst_cannot_bypass_waiting_limit(self):
        queue = ChatQueue(active=2, waiting=2, timeout=.03)
        results = await asyncio.gather(*(queue.acquire() for _ in range(12)), return_exceptions=True)
        leases = [r for r in results if not isinstance(r, BaseException)]
        self.assertEqual(len(leases), 2)
        self.assertEqual(queue.waiting, 0)
        for lease in leases: lease.release()

    async def test_cancelled_waiter_does_not_leak_permits(self):
        queue = ChatQueue(active=1)
        first = await queue.acquire()
        task = asyncio.create_task(queue.acquire())
        await asyncio.sleep(.001); task.cancel(); first.release()
        with self.assertRaises(asyncio.CancelledError): await task
        lease = await queue.acquire(); lease.release()
        self.assertEqual(queue.active, 0)
        self.assertEqual(queue.waiting, 0)

    async def test_response_holds_slot_until_stream_finishes(self):
        queue = ChatQueue(active=1)
        async def body():
            self.assertEqual(queue.active, 1)
            yield 'answer'
        async def operation(): return StreamingResponse(body())
        response = await run_queued(queue, None, operation)
        self.assertEqual(queue.active, 1)
        async def send(message): pass
        async def receive():
            await asyncio.sleep(10)
        await response({'type':'http','asgi':{'spec_version':'2.4'}}, receive, send)
        self.assertEqual(queue.active, 0)

    async def test_preparation_failure_releases_slot(self):
        queue = ChatQueue(active=1)
        async def fail(): raise RuntimeError('failure')
        with self.assertRaises(RuntimeError): await run_queued(queue, None, fail)
        self.assertEqual(queue.active, 0)


class ChatIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    setUp = chat_tests.ChatCostTests.setUp

    async def test_completed_duplicate_replays_without_model_or_usage_write(self):
        self.db.rpc.return_value.execute.return_value.data = {
            'request_id':'request','turns_used':1,'same_execution':False,
            'status':'complete','response_text':'Saved reply','response_source':'ai'}
        response = await self.env['chat_handler'](self.request, 'student')
        self.assertEqual([part async for part in response.body_iterator], ['Saved reply'])
        self.assertEqual(response.headers['x-request-replayed'], 'true')
        self.env['get_context'].assert_not_called()
        self.db.table.assert_called_once_with('chat_sessions')

    async def test_pending_duplicate_never_starts_second_generation(self):
        self.db.rpc.return_value.execute.return_value.data = {
            'request_id':'request','turns_used':1,'same_execution':False,'status':'processing'}
        with self.assertRaises(HTTPException) as caught:
            await self.env['chat_handler'](self.request, 'student')
        self.assertEqual(caught.exception.headers['X-Chat-Error'], 'request_pending')
        self.env['get_context'].assert_not_called()

    @patch('database_reliability.time.sleep')
    async def test_uncertain_reservation_retry_uses_same_keys(self, sleep):
        self.db.rpc.return_value.execute.side_effect = [httpx.RemoteProtocolError('lost'),
            SimpleNamespace(data={'error':'daily_limit'})]
        with self.assertRaises(HTTPException):
            await self.env['chat_handler'](self.request, 'student')
        calls = self.db.rpc.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[0].args[0], 'reserve_chat_request_v2')
