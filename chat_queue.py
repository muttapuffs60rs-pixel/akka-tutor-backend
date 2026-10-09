"""Per-process bounded admission held until the response stream closes."""
import asyncio
import time
from fastapi import HTTPException
from fastapi.responses import StreamingResponse


class ChatQueue:
    def __init__(self, active=20, waiting=40, timeout=25):
        self.limit = active
        self.waiting_limit = waiting
        self.timeout = timeout
        self.active = 0
        self.waiting = 0
        self._slots = asyncio.Semaphore(active)

    async def acquire(self, request=None):
        if self.active + self.waiting >= self.limit + self.waiting_limit:
            raise HTTPException(503, 'The tutor is busy. Please try again shortly.',
                                headers={'Retry-After': '3'})
        self.waiting += 1
        start = time.monotonic()
        task = asyncio.create_task(self._slots.acquire())
        acquired = False
        try:
            while not task.done():
                if request is not None and await request.is_disconnected():
                    raise HTTPException(499, 'Request disconnected before admission')
                remaining = self.timeout - (time.monotonic() - start)
                if remaining <= 0:
                    raise HTTPException(503, 'The tutor is busy. Please try again shortly.',
                                        headers={'Retry-After': '3'})
                await asyncio.wait({task}, timeout=min(0.25, remaining))
            await task
            acquired = True
            self.active += 1
            return QueueLease(self, time.monotonic() - start)
        finally:
            self.waiting -= 1
            if not acquired:
                # Cancellation can race with a released semaphore permit.
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                if task.done() and not task.cancelled() and task.exception() is None:
                    self._slots.release()


class QueueLease:
    def __init__(self, queue, seconds):
        self.queue, self.seconds, self.released = queue, seconds, False

    def release(self):
        if not self.released:
            self.released = True
            self.queue.active -= 1
            self.queue._slots.release()


class QueuedResponse(StreamingResponse):
    def __init__(self, response, lease):
        self.lease = lease
        super().__init__(response.body_iterator, status_code=response.status_code,
                         headers=dict(response.headers), background=response.background)
        self.headers['X-Queue-Wait-Ms'] = str(round(lease.seconds * 1000))

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.lease.release()


async def run_queued(queue, request, operation):
    lease = await queue.acquire(request)
    try:
        return QueuedResponse(await operation(), lease)
    except BaseException:
        lease.release()
        raise
