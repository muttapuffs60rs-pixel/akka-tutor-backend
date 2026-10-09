import unittest
from unittest.mock import Mock, call
from textbook_retrieval import tamil_terms, tamil_keyword_passages, TamilBookIndex, clean_passage, named_work_query, _CACHE


class TamilRetrievalTests(unittest.TestCase):
    def test_quoted_new_grammar_examples_retrieve_definitions(self):
        definition = 'முற்றுப் பெறாத வினை, பெயர்ச்சொல்லைக் கொண்டு முடிவது பெயரெச்சத்தொடர் எனப்படும். எடுத்துக்காட்டு கேட்ட பாடல்.'
        index = TamilBookIndex([{'content':definition}])
        for question in ['“வந்த மாணவன்” பெயரெச்சத் தொடர் என்பதை விளக்குக',
                         'இலக்கணம்: “புதிய மாணவன் வந்தான்” பெயரெச்சம் பற்றி விளக்குக']:
            self.assertFalse(named_work_query(question))
            self.assertEqual([r['content'] for r in index.search(question)], [definition])

    def test_grammar_word_inside_unknown_title_does_not_bypass_work_match(self):
        index = TamilBookIndex([{'content':'பெயரெச்சம் என்பது முற்றுப் பெறாத வினை பெயரைக் கொண்டு முடிவது ஆகும்.'}])
        self.assertTrue(named_work_query('“பெயரெச்சம் மலரும் விண்மீன்” செய்யுளை விளக்குக'))
        self.assertEqual(index.search('“பெயரெச்சம் மலரும் விண்மீன்” செய்யுளை விளக்குக'), [])

    def setUp(self):
        _CACHE.clear()
    def test_compound_terms_and_commands(self):
        terms = tamil_terms('தொகாநிலைத் தொடர் எழுவாய்த் தொடர் மற்றும் விளித்தொடர் தமிழில் பதில் அளிக்கவும்')
        self.assertEqual(terms, ['தொகாநிலை', 'எழுவாய்', 'விளி'])

    def test_definitions_rank_above_headings_and_exercises_and_stay_scoped(self):
        db = Mock()
        chain = db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        definition = 'எழுவாயுடன் பெயர், வினை, வினா ஆகிய பயனிலைகள் தொடர்வது எழுவாய்த்தொடர் ஆகும். எடுத்துகாட்டு காவிரி பாய்ந்தது.'
        chain.execute.return_value.data = [
            {'content': 'எழுவாய்த்தொடர்'},
            {'content': 'விடை தேர்ந்தெடுக்க ' + 'எழுவாய் ' * 15},
            {'content': definition},
        ]
        result = tamil_keyword_passages(db, 'எழுவாய்த் தொடர்', 'Tamil', 10)
        self.assertEqual([r['content'] for r in result], [definition])
        self.assertEqual(chain.eq.call_args_list, [call('grade_level', 10), call('subject', 'Tamil')])

    def test_advanced_tamil_pagination_cache_and_grade_isolation(self):
        db = Mock()
        chain = db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        verse = {'content': 'கண்ணுள் மணியைக் கருதிய பேரொளியை\nவிண்ணின் மணியை விளக்கொளியைப் போற்றீரே !',
                 'section_name': 'இடைக்காட்டுச் சித்தர் பாடல்'}
        chain.execute.side_effect = [Mock(data=[{'content':'தலைப்பு'}]*500), Mock(data=[verse]), Mock(data=[])]
        question = '“கண்ணுள் மணியைக் கருதிய பேரொளியை” செய்யுளுக்கு விளக்கம் தருக'
        self.assertEqual(len(tamil_keyword_passages(db, question, 'Advance Tamil', 11)), 1)
        self.assertEqual(len(tamil_keyword_passages(db, question, 'Advance Tamil', 11)), 1)
        self.assertEqual(chain.execute.call_count, 2)
        self.assertEqual(tamil_keyword_passages(db, question, 'Advance Tamil', 12), [])
        self.assertEqual(chain.range.call_args_list[:2], [call(0,499),call(500,999)])
        self.assertIn(call('grade_level',12), chain.eq.call_args_list)

    def test_failed_read_is_not_cached(self):
        db = Mock()
        chain = db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        chain.execute.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            tamil_keyword_passages(db, 'எழுவாய்த்தொடர்', 'Tamil', 10)
        self.assertFalse(_CACHE)

    def test_cleaning_preserves_verse_and_missing_named_poem_is_rejected(self):
        verse = 'கண்ணுள்\u200c மணியைக்\r\nகருதிய பேரொளியை\nவிண்ணின் மணியை விளக்கொளியைப் போற்றீரே !'
        index = TamilBookIndex([{'content':verse,'section_name':'சித்தர் பாடல்'}])
        self.assertEqual(len(index.search('“கண்ணுள் மணியைக் கருதிய பேரொளியை” விளக்குக')),1)
        self.assertIn('\n', clean_passage(verse))
        self.assertEqual(index.search('“அறியாத விண்மீன் பாடல்” விளக்குக'),[])

    def test_other_subject_skips_extra_database_queries(self):
        db = Mock()
        self.assertEqual(tamil_keyword_passages(db, 'Explain atoms', 'Science', 10), [])
        db.table.assert_not_called()

    def test_generic_question_words_do_not_retrieve_unrelated_literature(self):
        story = {'content': 'சோமநாதன் பேசிக் கொண்டிருந்ததைக் கேட்டுக் கொண்டிருந்த நேரம் போக, தான் பேச நேர்ந்தபோதெல்லாம் மகனின் கலியாண விஷயமாகவே பேசினார் பெரியசாமி. அவன் தனக்கொரு கலியாணம் என்பது பற்றி அதுவரை யோசித்ததில்லை. ஆனால், தகப்பனார் பேசுகிற தோரணையைப் பார்த்தால், தனக்கு யோசிக்க அவகாசமே தரமாட்டார் போலிருந்தது. சமாதானச் சூழ்நிலையில் வாழும் ஒரு தேசத்தின் ராணுவ உத்தியோகஸ்தன் கல்யாணம் செய்து கொள்ளலாம். அவ்விதம் திருமணம் புரிந்துகொண்டு எத்தனையோ பேர் குடும்பத்தோடு அங்கேயே வந்து வாழ்கிறார்களே என்பதையெல்லாம் நினைவு கூர்ந்து சரி என்று ஒப்புக்கொண்டான்.'}
        unrelated = {'content': 'நாடகத்தில் காட்சியை வரையறை செய்ய, களம் அவசியம். நாடகம் நிகழும் சூழலை உணர்த்துவது களம் ஆகும்.'}
        index = TamilBookIndex([story, unrelated])
        rows = index.search('சிறுகதையில் சோமநாதன் திருமணம் செய்துகொள்ள ஒப்புக்கொண்ட சூழலை விளக்குக.')
        self.assertEqual([row['content'] for row in rows], [story['content']])
