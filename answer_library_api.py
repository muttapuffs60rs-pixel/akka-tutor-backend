"""Admin review and authenticated student feedback for the shared answer library."""
import asyncio
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field


class AnswerReview(BaseModel):
    status: Literal['approved', 'rejected', 'pending']
    answer: str = Field(min_length=1, max_length=16000)
    chapter: str = Field(default='', max_length=200)
    source_reference: str = Field(default='', max_length=1000)
    review_note: str = Field(default='', max_length=1000)
    privacy_checked: bool = False
    accuracy_checked: bool = False
    expected_updated_at: datetime


def create_answer_library_router(database, authenticate):
    router = APIRouter(prefix='/answer-library', tags=['Answer library'])

    async def require_admin(user_id: str = Depends(authenticate)):
        rows = await asyncio.to_thread(lambda: database.table('profiles').select(
            'subscription_tier').eq('id', user_id).limit(1).execute().data)
        if not rows or rows[0].get('subscription_tier') != 'admin':
            raise HTTPException(403, 'Administrator access required')
        return user_id

    @router.get('')
    async def list_answers(status: Literal['pending', 'approved', 'rejected'] = 'pending',
                           offset: int = Query(default=0, ge=0, le=100000),
                           user_id: str = Depends(require_admin)):
        rows = await asyncio.to_thread(lambda: database.table('answer_library').select('*').eq(
            'status', status).order('updated_at', desc=True).range(offset, offset + 29).execute().data)
        return {'answers': rows, 'offset': offset}

    @router.patch('/{answer_id}')
    async def review_answer(answer_id: UUID, review: AnswerReview, user_id: str = Depends(require_admin)):
        if review.status == 'approved' and not (
            review.answer.strip() and review.chapter.strip() and review.source_reference.strip()
            and review.privacy_checked and review.accuracy_checked
        ):
            raise HTTPException(422, 'Check accuracy and privacy, and supply the chapter and textbook reference before approval')
        result = await asyncio.to_thread(lambda: database.rpc('review_library_answer', {
            'target_id': str(answer_id), 'reviewer_id': user_id,
            'review': review.model_dump(mode='json'),
        }).execute().data)
        if not result:
            raise HTTPException(409, 'This answer changed. Refresh the list before reviewing it again.')
        return result

    @router.post('/{answer_id}/report')
    async def report_answer(answer_id: UUID, user_id: str = Depends(authenticate)):
        result = await asyncio.to_thread(lambda: database.rpc('report_library_answer', {
            'target_id': str(answer_id), 'reporter_id': user_id,
        }).execute().data)
        if not result:
            raise HTTPException(404, 'No saved answer delivery found for your account')
        return {'reported': True}

    return router
