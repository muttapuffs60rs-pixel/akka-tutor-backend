"""Recorded-provider replay + held-out variants; all executions here are offline.

The actual handler, evidence selection and pre-display guard run unchanged.
Auth, billing, storage and generation are controlled adapters, not live tests.
"""
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_chat_cost_controls as chat_tests
from chat_cost_controls import retrieval_query
from educational_accuracy import validate_reply, route_question, reply_errors
from reviewed_sources import teaching_matches, teaching_evidence, teaching_records
from source_answers import claim_errors
from textbook_retrieval import TamilBookIndex

ROOT = Path(__file__).resolve().parents[1]
BASELINE = {r['id']:r for r in json.loads((ROOT/'curriculum/audit-2026-10-13/real-pilot-results.json').read_text(encoding='utf-8'))['results']}
def raw(id):
    return BASELINE[id]['provider_calls'][0]['generated_answer']


class ClaimTests(unittest.TestCase):
    def test_recorded_grammar_failure_independent_of_quotes(self):
        answer = raw('ta07')
        for value in [answer, answer.replace('"',''), answer.replace('**',''), answer.replace(':',' — '),
                      'குறில்: 7; நெடில்: 5', 'குறில் ஏழு. நெடில் ஐந்து.',
                      '| குறில் | ௭ |\n| நெடில் | ௫ |', 'There are seven short vowels and five long vowels.',
                      '“குறில்” — “7”; “நெடில்” — “5”', 'குறில்\n7\nநெடில்\n5']:
            with self.subTest(value=value):
                self.assertFalse(validate_reply(value, 'source', question='உயிர் எழுத்துகள் எத்தனை?'))
                self.assertIn('fact:vowel_count', claim_errors(value))

    def test_correct_and_paraphrased_classifications(self):
        for answer in ['குறில் 5: அ, இ, உ, எ, ஒ. நெடில் 7: ஆ, ஈ, ஊ, ஏ, ஐ, ஓ, ஔ.',
                       'குறில் ஐந்து; நெடில் ஏழு. மொத்தம் 12 உயிரெழுத்துகள்.',
                       'Tamil has twelve vowels: five short vowels and seven long vowels.',
                       'அகரம் குறுகிய ஒலியைக் கொண்டது. ஆ நீண்டு ஒலிக்கிறது.']:
            self.assertTrue(validate_reply(answer, 'source', question='உயிரெழுத்துகள்'))
        self.assertFalse(validate_reply('குறில் 5: அ, இ, உ, எ, ஐ.', 'source'))

    def test_actual_math_response_now_passes(self):
        self.assertTrue(validate_reply(raw('sc03'), '', question=BASELINE['sc03']['question']))

    def test_speed_errors_and_units(self):
        q = 'A cyclist covers 240 metres in 40 seconds. What is its average speed?'
        for answer in ['240 ÷ 40 = 7 m/s', 'The average speed is 6 m/s².', 'Speed = 6 km/h.']:
            self.assertFalse(validate_reply(answer, '', question=q))
        for answer in ['240 ÷ 40 = 6 m/s.', 'The answer is "6 metres per second".', 'Speed = 21.6 km/h.', '"240 ÷ 40 = 6 m/s"']:
            self.assertTrue(validate_reply(answer, '', question=q))
        self.assertFalse(validate_reply('12 × 3 = 35', ''))
        self.assertTrue(validate_reply('12 × 3 = 36', ''))

    def test_quotes_and_attribution(self):
        for answer in ['The poem says “invented bright verse”.', 'According to your textbook, speed is 5 m/s.',
                       'See page 52 for proof.', 'See https://invented.example/book']:
            self.assertFalse(validate_reply(answer, 'source', question='Explain this poem'))
        self.assertTrue(validate_reply('The word "uniform" means the same throughout.', 'source', question='Explain mixtures'))
        self.assertFalse(validate_reply('The source quotation is "arbitrary new text".', 'source'))
        self.assertFalse(validate_reply("The source quotation is 'arbitrary new text'.", 'source'))
        self.assertFalse(validate_reply('The poem says “invented line\nand another line”.', 'source'))
        self.assertFalse(validate_reply('Here is the verse:\n> invented bright verse', 'source', question='Explain the poem'))

    def test_science_critical_claims(self):
        for answer in ['Water is H₂O₂.', 'Water has two hydrogen atoms and two oxygen atoms.',
                       'Sodium gains one electron to become positive.',
                       'Average speed is not the average of separate speeds.', 'H + O + H → H₂O']:
            self.assertFalse(validate_reply(answer, 'source'), answer)
        for answer in ['Water is H₂O. It has two hydrogen atoms and one oxygen atom.',
                       'Sodium loses one electron to become positive.',
                       'Average speed is not generally the mean of speeds. Equal time intervals give the arithmetic mean.',
                       'H + O + H → H₂O is a composition sketch, not a reaction equation.']:
            self.assertTrue(validate_reply(answer, 'source'), answer)

    def test_intent_boundaries(self):
        for q in ['வளர்தமிழ் பாடத்தில் தமிழ் காலத்திற்கு ஏற்ப எவ்வாறு வளர்கிறது?',
                  'What is a homogeneous mixture? Give a textbook example.']:
            self.assertEqual(route_question(q, [], 'Tamil' if 'தமிழ்' in q else 'Science').kind, 'concept')
        self.assertEqual(route_question('Explain question 7 on page 52 of my textbook', [], 'Science').kind,'textbook')

    def test_followup_chains_and_new_topic(self):
        history = [{'role':'user','content':'உயிர் எழுத்துகள் எத்தனை?'},
                   {'role':'user','content':'அவற்றுக்கு எடுத்துக்காட்டு கொடு'},
                   {'role':'user','content':'இன்னும் எளிமையாக விளக்கு'}]
        for q in ['அவற்றின் பொருள் என்ன?', 'அடுத்தது என்ன?', 'Why?', 'What about the second one?', 'What is the difference between them?']:
            self.assertIn('உயிர் எழுத்துகள்', retrieval_query(q, history))
        self.assertEqual(retrieval_query('What is a cell membrane?', history), 'What is a cell membrane?')
        q='Explain the cell membrane and how it works.'
        self.assertEqual(retrieval_query(q,history),q)
        q='வளர்தமிழ் பற்றி விளக்கு. அது எவ்வாறு வளர்கிறது?'
        self.assertEqual(retrieval_query(q,history),q)
        history.append({'role':'user','content':'What is a cell membrane?'})
        self.assertNotIn('உயிர்', retrieval_query('Why?',history))

    def test_topic_source_boundaries(self):
        for board,grade,subject,q in [('cbse',6,'Tamil','உயிரெழுத்துகள்'),('tn',9,'Science','sodium'),
                  ('tn',6,'Tamil','2026-27 உயிரெழுத்துகள்'),('tn',6,'Tamil','2023 edition இன்பத்தமிழ்'),
                  ('tn',6,'Tamil','Term II இன்பத்தமிழ்')]:
            self.assertEqual(teaching_matches(q,board,grade,subject),[])
        self.assertEqual(teaching_matches('How does sodium become charged?', 'cbse',9,'Science')[0]['id'],'cbse9-sodium')
        self.assertEqual(teaching_matches('Who wrote இன்பத்தமிழ்?', 'tn',6,'Tamil')[0]['id'],'tn6-inbathamil')

    def test_title_and_author_adjacent_section(self):
        rows = json.loads((ROOT/'curriculum/reliability-2026-10-13/tamil-retrieval-fixture.json').read_text(encoding='utf-8'))
        for question in ['இன்பத்தமிழ் பாடலை எழுதியவர் யார்?', 'இன்பத்தமிழ் ஆசிரியர் பற்றி கூறு']:
            found = TamilBookIndex(rows).search(question)
            self.assertTrue(any('இயற்பெயர்' in r['content'] for r in found))
            self.assertTrue(all('இன்பத்தமிழ்' in r['section_name'] for r in found))


class TeachingPipelineTests(unittest.IsolatedAsyncioTestCase):
    setUp = chat_tests.ChatCostTests.setUp
    evidence = []

    async def scenario(self, id, question, generated, expected, board='cbse', subject='Science', history=None, allowed=True):
        self.request.question=question; self.request.board=board
        self.request.grade_level=6 if board=='tn' else 9
        self.request.subject=subject; self.request.history=history or []
        self.db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data=[{'board':board,'grade_level':None,'subject':None}]
        self.env['TAMIL_SUBJECTS']=('Tamil',)
        seen=[]
        async def stream(messages):
            seen.append(messages)
            yield SimpleNamespace(content=generated, usage_metadata={'input_tokens':100,'output_tokens':30}, response_metadata={'finish_reason':'stop'})
        model=Mock(); model.bind.return_value.astream=stream; self.env['deepseek_llm']=model
        started=time.perf_counter()
        actual_sources=[]; actual_queries=[]
        def capture_matches(*args):
            rows=teaching_matches(*args); actual_sources.extend(rows); actual_queries.append(args[0]); return rows
        with patch('reviewed_sources.teaching_matches',side_effect=capture_matches):
            response=await self.env['perform_chat'](self.request,'student')
            displayed=''.join([p async for p in response.body_iterator])
        elapsed=time.perf_counter()-started
        sources=actual_sources
        self.evidence.append(dict(id=id,mode='offline actual-handler / controlled provider', question=question,
            board=board,grade=self.request.grade_level,subject=subject,edition=sorted({r['edition'] for r in sources}),
            expected_educational_concept=expected,retrieval_queries=actual_queries,retrieved_sources=[r['id'] for r in sources],
            source_relevance='bounded exact topic match' if sources else 'none established',
            generated_answer=generated if seen else None,displayed_answer=displayed,
            expected_generated_accuracy='supported critical claims' if allowed else 'deliberate invalid claim',
            explanation_accuracy='critical assertions only; not independent educator review',
            context_retention=bool(sources) if history else 'not applicable',
            guard_decision='displayed' if generated and generated in displayed else 'local correction/clarification or rejection',
            guard_diagnostics=reply_errors(generated,teaching_evidence(sources),question=question,subject=subject,sources=sources) if seen else [],
            response_latency_seconds=elapsed))
        self.assertIn(expected,displayed)
        if not allowed:
            self.assertNotIn(generated,displayed)
        if seen:
            self.assertEqual(seen[0][-1].content,question)
        return displayed, seen

    async def test_recorded_correct_math_displayed(self):
        await self.scenario('sc03-replay',BASELINE['sc03']['question'],raw('sc03'),'5 m/s')

    async def test_recorded_wrong_grammar_with_and_without_quotes_blocked(self):
        for i,answer in enumerate([raw('ta07'),raw('ta07').replace('"','')]):
            await self.scenario('ta07-replay-'+str(i),BASELINE['ta07']['question'],answer,'உறுதிப்படுத்த முடியவில்லை','tn','Tamil',allowed=False)

    async def test_useful_reviewed_topics_and_heldouts(self):
        cases=[('author','இன்பத்தமிழ் பாடலை எழுதியவர் யார்?','இன்பத்தமிழ் பாடலை இயற்றியவர் பாரதிதாசன்.','பாரதிதாசன்','tn','Tamil'),
          ('author-heldout','இன்பத்தமிழ் ஆசிரியர் பெயர் என்ன?','இன்பத்தமிழ் பாடலை இயற்றியவர் பாரதிதாசன்.','பாரதிதாசன்','tn','Tamil'),
          ('valartamil',BASELINE['ta06']['question'],'தமிழ் புதிய அறிவியல், தொழில்நுட்பச் சொற்களால் வளர்கிறது.','வளர்கிறது','tn','Tamil'),
          ('valartamil-heldout','வளர்தமிழ் மொழியின் மாற்றத்தை எப்படிக் காட்டுகிறது?','தமிழில் புதிய இலக்கிய வடிவங்களும் கணினித் தமிழும் வளர்கின்றன.','கணினித்','tn','Tamil'),
          ('vowels','உயிரெழுத்துகள் எத்தனை வகை?','குறில் 5: அ, இ, உ, எ, ஒ. நெடில் 7: ஆ, ஈ, ஊ, ஏ, ஐ, ஓ, ஔ.','நெடில் 7','tn','Tamil'),
          ('mixture',BASELINE['sc06']['question'],'A homogeneous mixture has uniform composition. Sugar dissolved in water is an example.','uniform composition','cbse','Science'),
          ('mixture-heldout','Explain homogeneous mixtures with a textbook example.','A homogeneous mixture has uniform composition, such as sugar dissolved in water.','sugar','cbse','Science'),
          ('sodium','How does sodium form a positive ion?','Sodium loses one electron, forming Na⁺ with 11 protons and 10 electrons.','loses one electron','cbse','Science'),
          ('sodium-heldout','Why is the charge on a sodium ion positive?','Sodium loses one electron, leaving more protons than electrons.','loses one electron','cbse','Science'),
          ('water','Explain a water molecule.','H₂O means two hydrogen atoms and one oxygen atom.','one oxygen','cbse','Science'),
          ('speed-reasoning',BASELINE['sc02']['question'],'Average speed is total distance divided by total time. The mean of separate speeds applies for equal time intervals.','equal time','cbse','Science'),
          ('speed-heldout','A runner covers 240 m in 40 s. What is the speed?','240 ÷ 40 = 6 m/s, or "6 metres per second".','6 m/s','cbse','Science'),
          ('membrane','Explain the cell membrane.','The cell membrane selectively allows substances to pass.','selectively','cbse','Science'),
          ('distance','Compare distance and displacement.','Distance is path length; displacement is the net change in position with direction.','direction','cbse','Science')]
        for id,q,answer,expected,b,s in cases:
            with self.subTest(id=id):
                displayed,seen=await self.scenario(id,q,answer,expected,b,s)
                self.assertTrue(seen)
                self.assertIn('[Source:',displayed)
                self.assertIn('Source-checked facts',seen[0][0].content)

    async def test_followup_retrieves_topic_and_keeps_original_question(self):
        h=[{'role':'user','content':'உயிர் எழுத்துகள் எத்தனை?'}, {'role':'user','content':'அவற்றின் பொருள் என்ன?'}]
        _,seen=await self.scenario('ta08-followup','அவற்றுக்கு எடுத்துக்காட்டு கொடு','குறில்: அ, இ. நெடில்: ஆ, ஈ.','நெடில்','tn','Tamil',h)
        self.assertFalse(seen)
        self.assertIn('குறில் எழுத்துகள் 5',self.evidence[-1]['displayed_answer'])
        _,seen=await self.scenario('velocity-followup','How is it different from average velocity?',
            'Average velocity uses displacement and direction; average speed uses distance.','displacement',history=[{'role':'user','content':'What is average speed?'}])
        self.assertIn('cbse',self.evidence[-1]['board'])

    async def test_bad_speed_and_unsupported_citations_blocked(self):
        for id,answer in [('wrong-speed','The average speed is 8 m/s.'),('wrong-unit','The speed is 5 m/s².'),
                          ('fake-page','According to your textbook page 52, speed is 5 m/s.')]:
            await self.scenario(id,BASELINE['sc03']['question'],answer,'could not verify',allowed=False)

    async def test_recorded_precision_issues_rejected_and_examples_grounded(self):
        for id in ['sc02','sc07']:
            await self.scenario(id+'-precision-replay',BASELINE[id]['question'],raw(id),'could not verify',allowed=False)
        displayed,seen=await self.scenario('ta08-original-replay',BASELINE['ta08']['question'],raw('ta08'),'அ–ஆ','tn','Tamil',
            [{'role':'user','content':BASELINE['ta07']['question']}])
        self.assertFalse(seen)
        self.assertNotIn('ஔவியம்',displayed)

    async def test_false_source_identity_and_chemistry_blocked(self):
        for id,question,answer in [
            ('water-wrong','What is in a water molecule?','Water is H₂O₂.'),
            ('sodium-wrong','How does sodium form a positive ion?','Sodium gains one electron to become positive.'),
            ('wrong-chapter','How does sodium form a positive ion?','In chapter 1, sodium loses one electron.'),
            ('wrong-edition','Explain a homogeneous mixture.','The 2024 edition explains that it has uniform composition.')]:
            await self.scenario(id,question,answer,'could not verify',allowed=False)

    async def test_chapter_and_exact_question_clarification(self):
        _,seen=await self.scenario('chapter-conflict',BASELINE['sc09']['question'],'unused','chapter 9')
        self.assertFalse(seen)
        _,seen=await self.scenario('question-reference','Explain question 7 on page 52 of my textbook.','unused','share')
        self.assertFalse(seen)
        _,seen=await self.scenario('missing-question-parent','Explain question 7.','unused','Which chapter and exercise')
        self.assertFalse(seen)

    async def test_stored_topic_and_explicit_change(self):
        with patch('learning_context.read_context',return_value={'verified':True,'teaching_ids':['tn6-vowels']}):
            _,seen=await self.scenario('stored-topic','அவற்றுக்கு எடுத்துக்காட்டு கொடு','குறில்: அ, இ. நெடில்: ஆ, ஈ.','நெடில்','tn','Tamil')
            self.assertFalse(seen)
            self.assertIn('குறில் எழுத்துகள் 5',self.evidence[-1]['displayed_answer'])
            _,seen=await self.scenario('new-topic','வளர்தமிழ் பற்றி விளக்கு','தமிழ் காலத்திற்கு ஏற்ப வளர்கிறது.','வளர்கிறது','tn','Tamil')
            self.assertNotIn('குறில் எழுத்துகள் 5',seen[0][0].content)

    @classmethod
    def tearDownClass(cls):
        if os.environ.get('ARIVORA_WRITE_RELIABILITY_EVIDENCE') == '1':
            (ROOT/'curriculum/reliability-2026-10-13/handler-results.json').write_text(json.dumps(
                {'mode':'Offline; no new paid calls or production writes','results':cls.evidence},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
