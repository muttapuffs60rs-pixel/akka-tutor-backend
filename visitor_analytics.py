"""Anonymous app-open counts. No account IDs, URLs, questions or contact details."""
import asyncio
import hashlib
import time
from collections import OrderedDict, deque
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Request, HTTPException, Response
from pydantic import BaseModel, ConfigDict, ValidationError

class Visit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: UUID
    visitor_id: UUID
    source: Literal['direct', 'google', 'bing', 'facebook', 'instagram', 'whatsapp', 'other'] = 'direct'


def create_visitor_router(database):
    router = APIRouter()
    recent = OrderedDict()
    traffic = deque()

    @router.post('/analytics/visit', status_code=204)
    async def record_visit(request: Request):
        if request.headers.get('origin') != 'https://arivora.onrender.com':
            raise HTTPException(403, 'Origin not allowed')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024:
                raise HTTPException(413, 'Request too large')
        try:
            visit = Visit.model_validate_json(bytes(body))
        except ValidationError:
            raise HTTPException(422, 'Invalid visit') from None
        now = time.monotonic()
        while traffic and traffic[0] <= now - 60:
            traffic.popleft()
        key = hashlib.sha256(str(visit.visitor_id).encode()).hexdigest()
        entries = recent.pop(key, deque())
        while entries and entries[0] <= now - 60:
            entries.popleft()
        recent[key] = entries
        while len(recent) > 5000:
            recent.popitem(last=False)
        if len(traffic) >= 1000 or len(entries) >= 30:
            raise HTTPException(429, 'Try later')
        traffic.append(now)
        entries.append(now)
        try:
            await asyncio.to_thread(lambda: database.rpc('record_anonymous_visit', {
                'event': str(visit.event_id), 'visitor': key, 'referrer_source': visit.source,
            }).execute())
        except Exception:
            raise HTTPException(503, 'Analytics temporarily unavailable') from None
        return Response(status_code=204)
    return router
