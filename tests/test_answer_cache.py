from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from answer_cache import AnswerCache, GREETING, eligible_question, normalize_question
from answer_library_api import create_answer_library_router
import test_chat_cost_controls as chat_tests


class CacheIdentityTests(unittest.TestCase):
    def test_same_atom_question_has_separate_answers_for_each_grade(self):
        from prompts import TUTOR_CACHE_PROMPT
        cache = AnswerCache(Mock(), '2026-v1', TUTOR_CACHE_PROMPT)
        keys = {cache.identity('What is an atom?', 'Science', grade, 'same context')['cache_key']
                for grade in (6, 9, 12)}
        self.assertEqual(len(keys), 3)

    def test_normalization_preserves_meaningful_differences(self):
        self.assertEqual(normalize_question(' What  is gravity? '), 'What is gravity?')
        self.assertNotEqual(normalize_question('1 2\n3 4'), normalize_question('1 2 3 4'))
        self.assertNotEqual(normalize_question('Explain CO'), normalize_question('Explain Co'))
        self.assertNotEqual(normalize_question('Solve x+2=5'), normalize_question('Solve x-2=5'))

    def test_keys_separate_context_grade_subject_prompt_and_edition(self):
        cache = AnswerCache(Mock(), '2026-v1', 'prompt')
        base = cache.identity('What is gravity?', 'Science', 10, 'textbook')
        for item in (
            cache.identity('What is gravity?', 'Science', 11, 'textbook'),
            cache.identity('What is gravity?', 'Physics', 10, 'textbook'),
            cache.identity('What is gravity?', 'Science', 10, 'changed textbook'),
            AnswerCache(Mock(), '2027-v1', 'prompt').identity('What is gravity?', 'Science', 10, 'textbook'),
            AnswerCache(Mock(), '2026-v1', 'new prompt').identity('What is gravity?', 'Science', 10, 'textbook'),
        ):
            self.assertNotEqual(base['cache_key'], item['cache_key'])
        self.assertIsNone(AnswerCache(Mock(), '', 'prompt').identity('question', 'Science', 10, 'text'))
        self.assertIsNone(cache.identity('question', 'Science', 10, 'No specific textbook context found.'))

    def test_followups_images_history_and_obvious_personal_information_are_excluded(self):
        self.assertTrue(eligible_question('What is gravity?', [{'role': 'assistant', 'content': GREETING}], None, 1))
        for question, history, image, turns in (
            ('What is gravity?', [], 'image', 1),
            ('What is gravity?', [], None, 2),
            ('What is gravity?', [{'role': 'user', 'content': 'Earlier question'}], None, 1),
            ('What is gravity?', [{'role': 'assistant', 'content': 'Custom context'}], None, 1),
            ('Explain this step again', [], None, 1),
            ('Send to name@example.com', [], None, 1),
            ('My name is Priya', [], None, 1),
        ):
            self.assertFalse(eligible_question(question, history, image, turns))

    def test_candidate_insert_cannot_overwrite_review_and_lookup_requires_approval(self):
        db = Mock()
        cache = AnswerCache(db, 'v1', 'prompt')
        identity = cache.identity('What is gravity?', 'Science', 10, 'text')
        cache.save_candidate(identity, 'An explanation')
        _, kwargs = db.table.return_value.upsert.call_args
        self.assertTrue(kwargs['ignore_duplicates'])
        self.assertEqual(db.table.return_value.upsert.call_args.args[0]['status'], 'pending')
        result = {'id': 'approved-entry', 'answer': 'Reviewed explanation'}
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [result]
        self.assertEqual(cache.lookup(identity), result)
        db.table.return_value.select.return_value.eq.return_value.eq.assert_called_with('status', 'approved')

    def test_cache_failures_fall_back_without_exposing_question(self):
        db = Mock()
        db.table.side_effect = RuntimeError('offline')
        cache = AnswerCache(db, 'v1', 'prompt')
        identity = cache.identity('What is gravity?', 'Science', 10, 'text')
        self.assertIsNone(cache.lookup(identity))
        cache.save_candidate(identity, 'answer')


class CacheRouteTests(unittest.IsolatedAsyncioTestCase):
    setUp = chat_tests.ChatCostTests.setUp

    async def test_cached_answer_requires_full_3000_credit_balance(self):
        self.request.history = []
        self.credits.execute.return_value.data = {'enabled': True, 'remaining': 2999}
        self.env['answer_cache'].lookup.return_value = {'id': 'entry', 'answer': 'Reviewed answer'}
        model = Mock()
        self.env['deepseek_llm'] = model
        with self.assertRaises(chat_tests.HTTPException) as error:
            await self.env['chat_handler'](self.request, 'student')
        self.assertEqual(error.exception.status_code, 403)
        model.bind.assert_not_called()
        records = [call.args[1]['record'] for call in self.db.rpc.call_args_list
                   if call.args[0] == 'finish_learning_credit_request']
        self.assertEqual(records[-1]['status'], 'failed')

    async def test_cache_hit_has_zero_tokens_and_skips_ai(self):
        self.request.history = []
        self.env['answer_cache'].lookup.return_value = {'id': 'entry', 'answer': 'Reviewed answer'}
        model = Mock()
        self.env['deepseek_llm'] = model
        result = await self.env['chat_handler'](self.request, 'student')
        self.assertEqual([part async for part in result.body_iterator], ['Reviewed answer'])
        model.bind.assert_not_called()
        self.assertEqual(result.headers['x-answer-source'], 'cache')
        record = [call.args[1]['record'] for call in self.db.rpc.call_args_list
                  if call.args[0] == 'finish_learning_credit_request'][-1]
        self.assertEqual(record['input_tokens'], 0)
        self.assertEqual(record['output_tokens'], 0)
        self.assertEqual(record['vision_input_tokens'], 0)
        self.assertEqual(record['status'], 'cached')

    async def test_only_complete_first_answers_enter_review(self):
        for turns, finish, fail, expected in [(1, 'stop', False, True), (1, 'length', False, False),
                                             (1, 'stop', True, False), (2, 'stop', False, False)]:
            self.request.history = []
            self.db.rpc.return_value.execute.return_value.data = {'request_id': 'request', 'turns_used': turns}
            cache = self.env['answer_cache']
            cache.reset_mock()
            async def stream(messages):
                yield SimpleNamespace(content='Answer', usage_metadata=None, response_metadata={'finish_reason': finish})
                if fail:
                    raise RuntimeError('provider failed')
            model = Mock()
            model.bind.return_value.astream = stream
            self.env['deepseek_llm'] = model
            response = await self.env['chat_handler'](self.request, 'student')
            _ = [part async for part in response.body_iterator]
            self.assertEqual(cache.save_candidate.called, expected)
            if turns == 2:
                cache.lookup.assert_not_called()


class LibraryApiTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.profile = Mock()
        self.profile.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{'subscription_tier': 'admin'}]
        self.library = Mock()
        self.db.table.side_effect = lambda name: self.profile if name == 'profiles' else self.library
        app = FastAPI()
        app.include_router(create_answer_library_router(self.db, lambda: 'reviewer'))
        self.client = TestClient(app)
        self.id = '00000000-0000-0000-0000-000000000001'
        self.payload = dict(status='approved', answer='Explanation', chapter='Motion', source_reference='2026 textbook p.10',
                            privacy_checked=True, accuracy_checked=True, expected_updated_at='2026-10-08T00:00:00Z')

    def test_student_cannot_read_or_approve_library(self):
        self.profile.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{'subscription_tier': 'free'}]
        self.assertEqual(self.client.get('/answer-library').status_code, 403)
        self.assertEqual(self.client.patch(f'/answer-library/{self.id}', json=self.payload).status_code, 403)
        self.db.rpc.assert_not_called()

    def test_approval_requires_checks_and_reference(self):
        for change in ({'privacy_checked': False}, {'accuracy_checked': False}, {'source_reference': ' '}, {'chapter': ''}):
            self.assertEqual(self.client.patch(f'/answer-library/{self.id}', json=self.payload | change).status_code, 422)
        self.db.rpc.assert_not_called()

    def test_review_uses_authenticated_reviewer_and_detects_stale_version(self):
        self.db.rpc.return_value.execute.return_value.data = None
        self.assertEqual(self.client.patch(f'/answer-library/{self.id}', json=self.payload).status_code, 409)
        args = self.db.rpc.call_args.args[1]
        self.assertEqual(args['reviewer_id'], 'reviewer')
        self.db.rpc.return_value.execute.return_value.data = {'status': 'approved'}
        self.assertEqual(self.client.patch(f'/answer-library/{self.id}', json=self.payload).json(), {'status': 'approved'})

    def test_reporting_checks_delivery_and_uses_authenticated_reporter(self):
        self.db.rpc.return_value.execute.return_value.data = False
        self.assertEqual(self.client.post(f'/answer-library/{self.id}/report').status_code, 404)
        self.db.rpc.return_value.execute.return_value.data = True
        self.assertEqual(self.client.post(f'/answer-library/{self.id}/report').json(), {'reported': True})
        self.db.rpc.assert_called_with('report_library_answer', {'target_id': self.id, 'reporter_id': 'reviewer'})
