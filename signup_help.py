"""Minimal, rate-limited signup diagnostics; never returns profile details."""
import asyncio
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SignupPhone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=10, max_length=20, pattern=r"^\+?[0-9 ()-]+$")


def create_signup_help_router(database):
    router = APIRouter()
    traffic = deque()

    @router.post("/auth/signup-phone-status")
    async def phone_status(request: Request):
        if request.headers.get("origin") != "https://arivora.onrender.com":
            raise HTTPException(403, "Origin not allowed")
        now = time.monotonic()
        while traffic and traffic[0] <= now - 60:
            traffic.popleft()
        # Bound anonymous enumeration and DB load across all callers per worker.
        if len(traffic) >= 60:
            raise HTTPException(429, "Please try again later")
        traffic.append(now)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 256:
                raise HTTPException(413, "Request too large")
        try:
            payload = SignupPhone.model_validate_json(bytes(body))
        except ValidationError:
            raise HTTPException(422, "Invalid mobile number") from None
        try:
            # Match the exact value used by the existing UNIQUE constraint.
            result = await asyncio.to_thread(
                lambda: database.table("profiles").select("id")
                .eq("phone_number", payload.phone).limit(1).execute()
            )
        except Exception:
            raise HTTPException(503, "Signup check temporarily unavailable") from None
        return {"registered": bool(result.data)}

    return router
