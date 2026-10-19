"""Bounded quiz inputs and service-only transactional database operations."""
import asyncio
import logging
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)


class QuizBodyLimit:
    """Bound actual received bytes, including requests without Content-Length."""
    def __init__(self, app, maximum=1024 * 1024):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/live-quiz/'):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > self.maximum:
                from starlette.responses import JSONResponse
                return await JSONResponse({'detail': 'Quiz request is too large'}, status_code=413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
        return await self.app(scope, replay, send)


class LiveQuestion(BaseModel):
    question_text: str = Field(min_length=1, max_length=2000)
    question_type: Literal['mcq', 'fill_blank']
    options: list[str] | None = Field(default=None, min_length=2, max_length=4)
    correct_answer: str = Field(min_length=1, max_length=500)
    points: int = Field(default=1, ge=1, le=100)
    timer_seconds: int = Field(default=60, ge=5, le=600)
    timer_mode: Literal['auto', 'manual'] = 'manual'

    @model_validator(mode='after')
    def valid_options(self):
        if not self.question_text.strip() or not self.correct_answer.strip():
            raise ValueError('Question and answer must contain text')
        if self.options and any(not x.strip() or len(x) > 500 for x in self.options):
            raise ValueError('Options must contain 1–500 characters')
        if self.question_type == 'mcq' and (not self.options or self.correct_answer not in self.options):
            raise ValueError('MCQ answer must match an option')
        return self


class SecureLiveQuizCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    questions: list[LiveQuestion] = Field(min_length=1, max_length=50)


class SecureStudentAnswer(BaseModel):
    question_id: UUID
    submitted_answer: str = Field(min_length=1, max_length=500)
    student_name: str = Field(min_length=1, max_length=100)


async def quiz_rpc(database, name, params):
    try:
        result = await asyncio.to_thread(lambda: database.rpc(name, params).execute().data)
        if not isinstance(result, dict):
            raise ValueError('Invalid quiz database response')
        if result.get('error'):
            errors = {
                'not_found': (404, 'Quiz or question not found'),
                'forbidden': (403, 'Join this quiz before accessing it'),
                'quota': (403, 'Your live quiz allowance has been reached'),
                'inactive': (400, 'This question is not currently active'),
                'duplicate': (409, 'Already answered this question'),
                'invalid': (400, 'Invalid quiz input'),
            }
            status, detail = errors.get(result['error'], (503, 'Quiz service is unavailable'))
            raise HTTPException(status, detail)
        return result
    except HTTPException:
        raise
    except Exception:
        reference = uuid4().hex
        log.exception('Quiz operation failed reference=%s operation=%s', reference, name)
        raise HTTPException(503, f'Quiz service is unavailable. Reference: {reference}') from None


async def secure_create(database, data, user_id):
    return await quiz_rpc(database, 'secure_create_live_quiz', {
        'uid': user_id, 'title_value': data.title,
        'questions_value': [q.model_dump() for q in data.questions],
    })


async def secure_get(database, code, user_id):
    return await quiz_rpc(database, 'secure_join_live_quiz', {'uid': user_id, 'code_value': code.upper()})


async def secure_answer(database, code, data, user_id):
    return await quiz_rpc(database, 'secure_answer_live_quiz', {
        'uid': user_id, 'code_value': code.upper(), 'question_value': str(data.question_id),
        'answer_value': data.submitted_answer, 'name_value': data.student_name,
    })


async def secure_leaderboard(database, code, user_id):
    return await quiz_rpc(database, 'secure_live_leaderboard', {'uid': user_id, 'code_value': code.upper()})
