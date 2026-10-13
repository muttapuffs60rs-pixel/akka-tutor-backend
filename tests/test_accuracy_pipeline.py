"""Exercise actual perform_chat/stream/accounting with controlled service adapters.
These are fixture integration tests, not live Supabase/provider tests.
"""
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
import test_chat_cost_controls as chat_tests
from test_educational_accuracy import SOURCE, EvidenceDB, history


class AccuracyPipelineTests(unittest.IsolatedAsyncioTestCase):
    setUp = chat_tests.ChatCostTests.setUp

    def textbook_db(self, rows):
        session_query = self.db.table.return_value
        evidence = EvidenceDB(rows)
        self.db.table.side_effect = lambda name: evidence.table(name) if name == 'documents' else session_query

    async def answer(self, question, turns):
        self.request.question = question
        self.request.subject = 'Tamil'
        self.request.grade_level = 6
        self.request.history = turns
        response = await self.env['perform_chat'](self.request, 'student')
        return ''.join([part async for part in response.body_iterator])

    async def test_complete_textbook_conversation_uses_same_72(self):
        self.textbook_db([SOURCE])
        self.env['deepseek_llm'] = Mock()
        turns = history('திருக்குறள்', 'yes', 'செய்யுள் பகுதி', 'திருக்குறள்')
        for question in ['குறள் 7', 'பொருள்', 'எளிமையாக விளக்கு', 'உதாரணம்']:
            text = await self.answer(question, turns)
            self.assertIn('thirukkural:72', text)
            self.assertIn(SOURCE['source_meaning'], text)
            self.assertNotIn('தனக்குவமை', text)
            turns += [{'role': 'user', 'content': question}, {'role': 'assistant', 'content': text}]
        self.env['deepseek_llm'].bind.assert_not_called()
        self.env['get_context'].assert_not_called()

    async def test_missing_source_and_database_error_are_honest(self):
        self.textbook_db([])
        text = await self.answer('குறள் 8', history('செய்யுள் பகுதி'))
        self.assertIn('சரிபார்க்க', text)
        self.db.table.side_effect = lambda name: (_ for _ in ()).throw(RuntimeError('offline')) if name == 'documents' else self.db.table.return_value
        text = await self.answer('குறள் 8', history('செய்யுள் பகுதி'))
        self.assertIn('சரிபார்க்க', text)

    async def test_canonical_and_ambiguous_routes_never_call_model(self):
        self.env['deepseek_llm'] = Mock()
        text = await self.answer('மூலத் திருக்குறள் எண் 7', [])
        self.assertIn('தனக்குவமை', text)
        text = await self.answer('7', [])
        self.assertIn('எதைக் குறிக்கிறது', text)
        self.env['deepseek_llm'].bind.assert_not_called()

    async def test_unnumbered_textbook_request_fails_safely(self):
        self.env['deepseek_llm'] = Mock()
        text = await self.answer('Explain my textbook lesson', [])
        self.assertIn('சரிபார்க்க', text)
        self.env['deepseek_llm'].bind.assert_not_called()

    async def test_image_reference_is_not_a_canonical_record(self):
        self.env['download_chat_image'] = Mock(return_value=(b'image', 'image/jpeg'))
        self.env['ocr_reader'] = Mock()
        self.env['ocr_reader'].readtext.return_value = ['A textbook question asking the student to explain the concept in this passage']
        self.env['TAMIL_SUBJECTS'] = ('Tamil',)
        self.request.image_url = 'https://example.test/image.jpg'
        async def stream(messages):
            yield SimpleNamespace(content='See https://invented.example/page', usage_metadata={'input_tokens':10,'output_tokens':5})
        model = Mock()
        model.bind.return_value.astream = stream
        self.env['deepseek_llm'] = model
        text = await self.answer('குறள் 7', history('செய்யுள் பகுதி'))
        self.assertNotIn('invented.example', text)
        self.assertIn('உறுதிப்படுத்த முடியவில்லை', text)

    async def test_provider_failure_does_not_leak_partial_bad_quote(self):
        async def broken(messages):
            yield SimpleNamespace(content='“made-up quote”', usage_metadata=None)
            raise RuntimeError('provider failure')
        model = Mock()
        model.bind.return_value.astream = broken
        self.env['deepseek_llm'] = model
        self.request.history = []
        response = await self.env['perform_chat'](self.request, 'student')
        text = ''.join([part async for part in response.body_iterator])
        self.assertNotIn('made-up', text)
        self.assertIn('try again', text)

    async def test_retrieval_failure_does_not_claim_textbook_verification(self):
        self.env['get_context'].side_effect = RuntimeError('retrieval down')
        async def stream(messages):
            self.assertIn('No specific textbook edition/page has been verified', messages[0].content)
            yield SimpleNamespace(content='Gravity attracts masses.', usage_metadata={'input_tokens': 10, 'output_tokens': 5}, response_metadata={'finish_reason':'stop'})
        model = Mock()
        model.bind.return_value.astream = stream
        self.env['deepseek_llm'] = model
        response = await self.env['perform_chat'](self.request, 'student')
        self.assertEqual(''.join([p async for p in response.body_iterator]), 'Gravity attracts masses.')
