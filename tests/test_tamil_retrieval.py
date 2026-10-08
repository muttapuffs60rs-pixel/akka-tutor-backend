import unittest
from unittest.mock import Mock, call
from textbook_retrieval import tamil_terms, tamil_keyword_passages


class TamilRetrievalTests(unittest.TestCase):
    def test_compound_terms_and_commands(self):
        terms = tamil_terms('தொகாநிலைத் தொடர் எழுவாய்த் தொடர் மற்றும் விளித்தொடர் தமிழில் பதில் அளிக்கவும்')
        self.assertEqual(terms, ['தொகாநிலை', 'எழுவாய்', 'விளி'])

    def test_definitions_rank_above_headings_and_exercises_and_stay_scoped(self):
        db = Mock()
        chain = db.table.return_value.select.return_value
        chain.eq.return_value = chain
        chain.or_.return_value = chain
        chain.limit.return_value = chain
        definition = 'எழுவாயுடன் பெயர், வினை, வினா ஆகிய பயனிலைகள் தொடர்வது எழுவாய்த்தொடர் ஆகும். எடுத்துகாட்டு காவிரி பாய்ந்தது.'
        chain.execute.return_value.data = [
            {'content': 'எழுவாய்த்தொடர்'},
            {'content': 'விடை தேர்ந்தெடுக்க ' + 'எழுவாய் ' * 15},
            {'content': definition},
        ]
        result = tamil_keyword_passages(db, 'எழுவாய்த் தொடர்', 'Tamil', 10)
        self.assertEqual([r['content'] for r in result], [definition])
        self.assertEqual(chain.eq.call_args_list, [call('grade_level', 10), call('subject', 'Tamil')])

    def test_other_subject_skips_extra_database_queries(self):
        db = Mock()
        self.assertEqual(tamil_keyword_passages(db, 'Explain atoms', 'Science', 10), [])
        db.table.assert_not_called()
