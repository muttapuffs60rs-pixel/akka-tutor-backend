import unittest
from unittest.mock import Mock, call
from textbook_retrieval import tamil_terms, tamil_keyword_passages, TamilBookIndex, clean_passage, _CACHE


class TamilRetrievalTests(unittest.TestCase):
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
