import unittest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_app_hardening import load_routes, QuizRouteTests
from test_chat_cost_controls import load_chat
from quiz_security import QuizBodyLimit


class InputTests(unittest.TestCase):
    def test_whitespace_chat_is_rejected(self):
        model = load_chat()['ChatRequest']
        with self.assertRaises(ValidationError):
            model(question='   ', subject='Maths', grade_level=10,
                  session_id='00000000-0000-4000-8000-000000000001')

    def test_invalid_quiz_fields_are_rejected(self):
        model = load_routes()['QuizRequest']
        valid = dict(subject='Maths', units=['Fractions'], grade_level=10)
        for change in ({'subject':''}, {'subject':' '}, {'subject':'x'*101},
                       {'units':[]}, {'units':[' ']}, {'units':['x'*151]},
                       {'units':['x']*21}, {'section':' '}, {'section':'x'*151},
                       {'board':'unknown'}):
            with self.subTest(change=str(change)[:100]), self.assertRaises(ValidationError):
                model(**(valid | change))

    def test_body_limit_includes_chat_and_solo_quiz(self):
        app=FastAPI()
        app.add_middleware(QuizBodyLimit)
        client=TestClient(app)
        for path in ('/ask','/generate-quiz'):
            self.assertEqual(client.post(path,content=b'x'*65537).status_code,413)


class BoardTests(QuizRouteTests):
    async def test_cbse_quiz_uses_cbse_retrieval_and_english(self):
        self.request.board = 'cbse'
        await self.routes['generate_quiz'](self.request, 'student')
        self.assertEqual(self.context.call_args.kwargs['board'], 'cbse')
        self.assertIn('CBSE', self.prompts[0])
        self.assertNotIn('TN State Board', self.prompts[0])
        self.assertIn('must be in English', self.prompts[0])
