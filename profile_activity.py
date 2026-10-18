"""Student-owned, paginated credit usage. Never expose provider costs or replies."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query


def create_profile_activity_router(database, get_current_user):
    router = APIRouter()

    @router.get('/profile/activity')
    async def activity(offset: int = Query(0, ge=0, le=10000), user_id: str = Depends(get_current_user)):
        def read():
            rows = (database.table('ai_chat_requests')
                    .select('id,created_at,session_id,learning_credits_charged,topup_credits_charged,response_source')
                    .eq('user_id', user_id).gt('learning_credits_charged', 0)
                    .order('created_at', desc=True).order('id', desc=True)
                    .range(offset, offset + 20).execute().data)
            return {'items': [{
                'id': row['id'], 'created_at': row['created_at'],
                'session_id': row['session_id'],
                'credits_used': max(0, int(row.get('learning_credits_charged') or 0)),
                'topup_credits_used': max(0, int(row.get('topup_credits_charged') or 0)),
                'kind': 'Saved textbook answer' if row.get('response_source') == 'cache' else 'Tutor request',
            } for row in rows[:20]], 'has_more': len(rows) > 20}
        try:
            return await asyncio.to_thread(read)
        except Exception:
            raise HTTPException(503, 'Could not load your credit history. Please try again.') from None

    return router
