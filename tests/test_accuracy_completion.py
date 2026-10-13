import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from reference_resolution import resolve_reference
from curriculum_evidence import resolve_reviewed_source, resolve_textbook
from reviewed_sources import reviewed_database
from learning_context import read_context, write_context, verified_context
from source_answers import render_source_answer
from test_educational_accuracy import EvidenceDB, history, SOURCE
import test_accuracy_pipeline as pipeline


class SourceAndStateTests(unittest.TestCase):
    def test_approved_default_edition_is_narrow_and_does_not_mutate_intent(self):
        ref=resolve_reference('textbook kural 7')
        row=resolve_reviewed_source(EvidenceDB([]),ref,'tn',6,'Tamil')
        self.assertEqual(row['edition'],'2024')
        self.assertEqual(ref.qualifiers,{})
        self.assertIsNone(resolve_reviewed_source(EvidenceDB([]),ref,'tn',7,'Tamil'))
        self.assertIsNone(resolve_reviewed_source(EvidenceDB([]),resolve_reference('2023 edition textbook kural 7'),'tn',6,'Tamil'))
    def test_official_editions_are_separately_scoped(self):
        ref = resolve_reference('2024 edition textbook kural 7')
        rows = [resolve_reviewed_source(EvidenceDB([]), ref, b, 6, 'Tamil') for b in ('tn','cbse')]
        self.assertEqual([r['board'] for r in rows], ['tn','cbse'])
        self.assertEqual([r['pdf_page'] for r in rows], [57,59])
        for row in rows:
            self.assertEqual(row['page_number'],49)
            self.assertEqual(row['canonical_reference'],'thirukkural:72')
            self.assertEqual(len(row['source_sha256']),64)
            self.assertIn('not verified',render_source_answer(row,'meaning'))

    def test_requested_school_year_cannot_be_substituted(self):
        for question in ('2026–27 textbook kural 7','2026-2027 textbook kural 7'):
            ref = resolve_reference(question)
            self.assertEqual(ref.number,'7')
            self.assertEqual(ref.qualifiers['academic_year'],'2026-27')
            self.assertIsNone(resolve_reviewed_source(EvidenceDB([]),ref,'tn',6,'Tamil'))
        ref=resolve_reference('2024 edition textbook kural 7 term II')
        self.assertIsNone(resolve_reviewed_source(EvidenceDB([]),ref,'tn',6,'Tamil'))
        ref=resolve_reference('குறள் 7',history('2026-27 textbook','அன்புடைமை','திருக்குறள்'))
        self.assertEqual(ref.scope,'textbook')
        self.assertEqual(ref.qualifiers['academic_year'],'2026-27')
        self.assertIsNone(resolve_reviewed_source(EvidenceDB([]),ref,'tn',6,'Tamil'))

    def test_partial_page_is_not_served_as_whole_page(self):
        ref=resolve_reference('2024 edition page 49')
        self.assertIsNone(resolve_reviewed_source(EvidenceDB([]),ref,'tn',6,'Tamil'))

    def test_parent_reference_change_clears_children(self):
        turns=history('exercise 1.2 question 7')
        self.assertEqual(resolve_reference('page 49',turns).qualifiers,{})
        ref=resolve_reference('question 3',history('exercise 2.1'))
        self.assertEqual(ref.qualifiers,{'exercise_number':'2.1'})

    def test_source_scope_is_rechecked_even_if_adapter_ignores_filters(self):
        db=Mock()
        db.table.return_value.select.return_value.eq.return_value = db.table.return_value.select.return_value
        db.table.return_value.select.return_value.limit.return_value.execute.return_value.data=[SOURCE]
        ref=resolve_reference('2026-27 textbook kural 7')
        self.assertIsNone(resolve_textbook(db,ref,'tn',6,'Tamil'))

    def test_verified_memory_restores_reference_without_client_history(self):
        ref=resolve_reference('2024 edition textbook kural 7')
        context=verified_context(ref)
        for question in ('பொருள்','எளிமையாக','why?','example'):
            restored=resolve_reference(question,[],context)
            self.assertEqual(restored.number,'7')
            self.assertEqual(restored.qualifiers['edition'],'2024')
        self.assertIsNone(resolve_reference('Explain photosynthesis',[],context).number)

    def test_persisted_memory_ownership_scope_and_expiration(self):
        context=verified_context(resolve_reference('original kural 7'))
        row={'session_id':'session','user_id':'user','board':'tn','grade_level':6,'subject':'Tamil','context':context,'updated_at':datetime.now(timezone.utc).isoformat()}
        db=Mock()
        query=db.table.return_value.select.return_value
        query.eq.return_value=query
        query.execute.return_value.data=[row]
        self.assertEqual(read_context(db,'session','user','tn',6,'Tamil'),context)
        query.eq.assert_any_call('user_id','user')
        self.assertIsNone(read_context(db,'session','user','cbse',6,'Tamil'))
        self.assertIsNone(read_context(db,'other-session','user','tn',6,'Tamil'))
        row['updated_at']=(datetime.now(timezone.utc)-timedelta(days=31)).isoformat()
        self.assertIsNone(read_context(db,'session','user','tn',6,'Tamil'))
        db.table.side_effect=RuntimeError('missing migration')
        self.assertIsNone(read_context(db,'session','user','tn',6,'Tamil'))
        self.assertFalse(write_context(db,'session','user','tn',6,'Tamil',context))


class OfficialSourcePipelineTests(unittest.IsolatedAsyncioTestCase):
    setUp = pipeline.AccuracyPipelineTests.setUp
    answer = pipeline.AccuracyPipelineTests.answer
    textbook_db = pipeline.AccuracyPipelineTests.textbook_db

    async def test_adopted_verse_without_gloss_and_conflict_never_invent_meanings(self):
        from educational_accuracy import corpus
        records=corpus()['records']
        adopted=next(r for r in records if r['status']=='verified' and not r['gloss'])
        blocked=next(r for r in records if r['status']!='verified')
        self.env['deepseek_llm']=Mock()
        answer=await self.answer(f"மூலத் திருக்குறள் எண் {adopted['number']}",[])
        self.assertIn(adopted['lines'][0],answer)
        self.assertIn('இன்னும் சரிபார்க்கப்படவில்லை',answer)
        answer=await self.answer(f"மூலத் திருக்குறள் எண் {blocked['number']}",[])
        self.assertNotIn(blocked['lines'][0],answer)
        self.env['deepseek_llm'].bind.assert_not_called()

    async def test_official_source_through_actual_handler(self):
        self.textbook_db([])
        self.env['deepseek_llm']=Mock()
        text=await self.answer('textbook kural 7',[])
        self.assertIn('thirukkural:72',text)
        self.assertIn('2024',text)
        self.assertIn('49',text)
        self.env['deepseek_llm'].bind.assert_not_called()
        text=await self.answer('2026-27 textbook kural 7',[])
        self.assertNotIn('thirukkural:72',text)
        self.assertIn('சரிபார்க்க',text)
        text=await self.answer('2026-27',history('செய்யுள் பகுதி'))
        self.assertNotIn('1999',text)
        self.assertIn('பக்கம்',text)

    async def test_server_memory_survives_empty_history_and_rechecks_source(self):
        from types import SimpleNamespace
        class Memory:
            row = None
            def select(self, _): return self
            def eq(self, *_): return self
            def upsert(self, row, **_):
                self.row = copy.deepcopy(row)
                return self
            def execute(self): return SimpleNamespace(data=[self.row] if self.row else [])
        memory=Memory()
        sessions=self.db.table.return_value
        self.db.table.side_effect=lambda name: memory if name=='chat_learning_context' else EvidenceDB([]) if name=='documents' else sessions
        self.env['deepseek_llm']=Mock()
        first=await self.answer('2024 edition textbook kural 7',[])
        self.assertIn('thirukkural:72',first)
        self.assertTrue(memory.row['context']['verified'])
        follow=await self.answer('பொருள்',[])
        self.assertIn('thirukkural:72',follow)
        # Changing the year invalidates the source; no stale answer is repeated.
        missing=await self.answer('2026-27 textbook kural 7',[])
        self.assertNotIn('thirukkural:72',missing)
        self.assertEqual(memory.row['context'],{})
        self.env['deepseek_llm'].bind.assert_not_called()

    async def test_asgi_http_request_uses_real_queue_and_answer_handler(self):
        import ast
        from pathlib import Path
        from fastapi import FastAPI, Request
        import httpx
        from chat_queue import ChatQueue, run_queued
        path=Path(__file__).resolve().parents[1]/'main.py'
        node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                  if getattr(n,'name',None)=='chat_handler')
        node.decorator_list=[]
        self.env.update(Request=Request,chat_queue=ChatQueue(),run_queued=run_queued)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),self.env)
        app=FastAPI()
        app.dependency_overrides[self.env['get_current_user']]=lambda:'student'
        app.post('/ask')(self.env['chat_handler'])
        self.textbook_db([])
        self.env['deepseek_llm']=Mock()
        payload=self.request.model_dump(mode='json')
        payload.update(question='2024 edition textbook kural 7',subject='Tamil',grade_level=6,history=[])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post('/ask',json=payload)
            self.assertEqual(response.status_code,200)
            self.assertIn('thirukkural:72',response.text)
            self.assertEqual(response.headers['x-answer-source'],'verified')
            self.assertIn('x-queue-wait-ms',response.headers)
            self.assertEqual(self.env['chat_queue'].active,0)
            payload['grade_level']=99
            self.assertEqual((await client.post('/ask',json=payload)).status_code,422)
        self.env['deepseek_llm'].bind.assert_not_called()
