"""Central pre-launch authorization, shared with direct database access rules."""
from fastapi import HTTPException
from database_reliability import retry_database


def require_launch_access(database, user_id):
    try:
        allowed = retry_database(lambda: database.rpc(
            'app_launch_access_for_user', {'target_user_id': str(user_id)}
        ).execute().data)
    except Exception:
        raise HTTPException(503, 'Access could not be checked. Please try again shortly.')
    if allowed is not True:
        raise HTTPException(403, 'Arivora launches on 20 October 2026. Private testing access only.')
