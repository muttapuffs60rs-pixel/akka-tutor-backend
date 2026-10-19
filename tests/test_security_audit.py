import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from quiz_security import (QuizBodyLimit, SecureLiveQuizCreate, SecureStudentAnswer,
                           secure_create, secure_get, secure_answer, secure_leaderboard)
from image_security import validate_image_url, download_chat_image

OWNER = '00000000-0000-0000-0000-000000000001'
OTHER = '00000000-0000-0000-0000-000000000002'
ORIGIN = 'https://example.supabase.co'
IMAGE = f'{ORIGIN}/storage/v1/object/authenticated/chat-images/chat_uploads/{OWNER}/random.jpg'
QUESTION = dict(question_text='Choose B', question_type='mcq', options=['A', 'B'], correct_answer='B')


class SecurityApiTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.rpc.return_value.execute.return_value.data = {'error': 'forbidden'}
        app = FastAPI()
        app.add_middleware(QuizBodyLimit)
        scope = dict(app=app, supabase=self.db, Depends=Depends, HTTPException=HTTPException,
                     get_current_user=lambda: OWNER, SecureLiveQuizCreate=SecureLiveQuizCreate,
                     SecureStudentAnswer=SecureStudentAnswer, secure_create=secure_create,
                     secure_get=secure_get, secure_answer=secure_answer, secure_leaderboard=secure_leaderboard)
        names = {'LiveQuizCreate', 'StudentAnswerRequest', 'create_live_quiz', 'get_live_quiz',
                 'submit_answer', 'get_leaderboard', 'start_live_quiz', 'next_question', 'complete_live_quiz'}
        source = Path(__file__).resolve().parents[1] / 'main.py'
        nodes = [n for n in ast.parse(source.read_text(encoding='utf-8')).body if getattr(n, 'name', '') in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
        self.client = TestClient(app)

    def test_direct_answer_and_leaderboard_deny_nonparticipants(self):
        response = self.client.post('/live-quiz/ABC123/answer', json={
            'question_id': OTHER, 'submitted_answer': 'B', 'student_name': 'Student'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/live-quiz/ABC123/leaderboard').status_code, 403)
        self.db.table.assert_not_called()

    def test_join_and_host_quota_rejections_remain_403(self):
        self.db.rpc.return_value.execute.return_value.data = {'error': 'quota'}
        self.assertEqual(self.client.get('/live-quiz/ABC123').status_code, 403)
        self.assertEqual(self.client.post('/live-quiz/create', json={'title': 'Quiz', 'questions': [QUESTION]}).status_code, 403)

    def test_database_details_never_reach_http_responses(self):
        self.db.rpc.side_effect = RuntimeError('SYNTHETIC_SECRET_SCHEMA_DETAIL')
        with self.assertLogs('quiz_security', level='ERROR'):
            response = self.client.get('/live-quiz/ABC123/leaderboard')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('SYNTHETIC', response.text)
        self.db.table.side_effect = RuntimeError('SYNTHETIC_SECRET_SCHEMA_DETAIL')
        for action in ('start', 'next', 'complete'):
            response = self.client.post(f'/live-quiz/ABC123/{action}')
            self.assertEqual(response.status_code, 500)
            self.assertNotIn('SYNTHETIC', response.text)

    def test_oversized_or_invalid_quiz_never_calls_database(self):
        for questions in ([], [QUESTION] * 51, [{**QUESTION, 'options': ['X', 'Y']}],
                          [{**QUESTION, 'question_text': 'x'*2001}], [{**QUESTION, 'timer_seconds': 0}]):
            self.assertEqual(self.client.post('/live-quiz/create', json={'title': 'Quiz', 'questions': questions}).status_code, 422)
        response = self.client.post('/live-quiz/create', content=b'x' * (1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)
        self.db.rpc.assert_not_called()

    def test_atomic_creation_receives_caller_identity_and_validated_questions(self):
        self.db.rpc.return_value.execute.return_value.data = {'session_code': 'ABC123'}
        self.assertEqual(self.client.post('/live-quiz/create', json={'title': 'Quiz', 'questions': [QUESTION]}).status_code, 200)
        name, params = self.db.rpc.call_args.args
        self.assertEqual(name, 'secure_create_live_quiz')
        self.assertEqual(params['uid'], OWNER)
        self.assertEqual(params['questions_value'][0]['correct_answer'], 'B')
        self.db.table.assert_not_called()


class PrivateImageTests(unittest.TestCase):
    @patch('image_security.requests.get')
    def test_cross_user_and_legacy_public_urls_cannot_be_downloaded(self, request):
        for url in (IMAGE.replace(OWNER, OTHER), IMAGE.replace('/authenticated/', '/public/'),
                    IMAGE.replace('/random.jpg', '/%2e%2e/random.jpg'), IMAGE+'?token=x',
                    IMAGE.replace('example.supabase.co', 'evil.test')):
            with self.subTest(url=url), self.assertRaises(HTTPException):
                download_chat_image(url, ORIGIN, OWNER, 'synthetic-key')
        request.assert_not_called()

    @patch('image_security.requests.get')
    def test_private_download_has_credentials_and_does_not_follow_redirects(self, request):
        response = Mock(status_code=200, headers={'Content-Type': 'image/jpeg'})
        response.iter_content.return_value = [b'image']
        request.return_value.__enter__.return_value = response
        self.assertEqual(download_chat_image(IMAGE, ORIGIN, OWNER, 'synthetic-key'), (b'image', 'image/jpeg'))
        self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer synthetic-key')
        self.assertFalse(request.call_args.kwargs['allow_redirects'])


class ChunkedBodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_request_without_content_length_is_limited(self):
        app = Mock()
        limit = QuizBodyLimit(app, maximum=10)
        messages = iter([{'type': 'http.request', 'body': b'x'*6, 'more_body': True},
                         {'type': 'http.request', 'body': b'x'*6, 'more_body': False}])
        sent = []
        async def receive(): return next(messages)
        async def send(message): sent.append(message)
        await limit({'type': 'http', 'path': '/live-quiz/create'}, receive, send)
        self.assertEqual(sent[0]['status'], 413)
        app.assert_not_called()
