"""Retry only reads and explicitly idempotent database operations."""
import random
import time
import httpx
from supabase.lib.client_options import SyncClientOptions


def database_options():
    # Isolate requests on pooled HTTP/1.1 connections instead of a shared HTTP/2
    # stream whose disconnection previously failed a whole burst of reservations.
    return SyncClientOptions(
        auto_refresh_token=False, persist_session=False,
        httpx_client=httpx.Client(
            http2=False,
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20,
                               keepalive_expiry=15),
            timeout=httpx.Timeout(15, connect=5, pool=5),
        ),
    )


def retry_database(operation, attempts=3):
    for attempt in range(attempts):
        try:
            return operation()
        except (httpx.TransportError,):
            if attempt + 1 == attempts:
                raise
            time.sleep(0.15 * 2 ** attempt + random.uniform(0, 0.1))
