import copy
import unittest
from unittest.mock import Mock

from reference_resolution import resolve_reference
from curriculum_evidence import resolve_textbook
from educational_accuracy import route_question, validate_reply, arithmetic_answer, corpus, lookup
from source_answers import meaning_preserved, render_source_answer, validate_subject_facts

# Regression evidence supplied by the user, not an imported/verified production
# textbook. This fixture demonstrates behaviour only when review metadata exists.
SOURCE = {
    'id': 'fixture-only', 'board': 'tn', 'grade_level': 6, 'subject': 'Tamil',
    'verification_status': 'verified', 'source_title': 'Class 6 Tamil TEST FIXTURE',
    'source_url': 'https://example.org/fixture-only', 'edition': '2024',
    'content_version': 'fixture-v1', 'section_name': 'அன்புடைமை',
    'selection_ordinal': 7, 'canonical_reference': 'thirukkural:72',
    'content': 'அன்பிலார் எல்லாம் தமக்குரியர் அன்புடையார்\nஎன்பும் உரியர் பிறர்க்கு.',
    'source_meaning': 'அன்பு இல்லாதவர் எல்லாப் பொருளும் தமக்கே என்பார்கள். அன்பு உடையவர்கள் தம் உடம்பும் பிறர்க்கே என்பார்கள்.',
    'simplified_meaning': 'அன்பு இல்லாதவர் எல்லாம் தனக்கே என நினைப்பார். அன்புள்ளவர் தன்னையும் பிறருக்காக அர்ப்பணிப்பார்.',
    'meaning_status': 'verified',
}


def history(*turns):
    return [{'role': 'user', 'content': t} for t in turns]


class EvidenceDB:
    """In-memory database protocol for deterministic integration; no live writes."""
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
    def table(self, name):
        assert name == 'documents'
        self.filters = []
        return self
    def select(self, fields): return self
    def eq(self, key, value):
        self.filters.append((key, value))
        return self
    def limit(self, value): return self
    def execute(self):
        return type('Result', (), {'data': [r for r in self.rows
            if all(str(r.get(k)) == str(v) for k, v in self.filters)]})()


class EducationalAccuracyTests(unittest.TestCase):
    def test_textbook_seventh_is_72_only_with_verified_mapping(self):
        turns = history('திருக்குறள்', 'செய்யுள் பகுதி', 'அன்புடைமை')
        # Named section is verified metadata in the fixture; user section text is a hint.
        ref = resolve_reference('குறள் 7', turns)
        row = resolve_textbook(EvidenceDB([SOURCE]), ref, 'tn', 6, 'Tamil', turns)
        self.assertEqual(row['canonical_reference'], 'thirukkural:72')
        answer = render_source_answer(row, 'குறள் 7', tamil=True)
        self.assertIn('அன்பிலார்', answer)
        self.assertNotIn('தனக்குவமை', answer)

    def test_explicit_canonical_overrides_textbook(self):
        d = route_question('மூலத் திருக்குறள் எண் 7', history('செய்யுள் பகுதி'), 'Tamil')
        self.assertEqual(d.record['number'], 7)
        self.assertIn('தனக்குவமை', d.answer)

    def test_bare_and_unqualified_numbers_ask_clarification(self):
        for q in ['7', 'குறள் 7', 'குறள் ஏழு']:
            self.assertEqual(route_question(q, [], 'Tamil').kind, 'clarification')

    def test_number_types_stay_distinct(self):
        r = resolve_reference('exercise 1.2 question 7')
        self.assertEqual((r.kind, r.number), ('question_number', '7'))
        self.assertEqual(r.qualifiers, {'exercise_number': '1.2'})
        self.assertEqual(resolve_reference('page 7').kind, 'page_number')
        self.assertEqual(resolve_reference('chapter 7').kind, 'chapter_number')
        self.assertEqual(resolve_reference('lesson 7').kind, 'lesson_number')

    def test_wrong_literal_quotation_is_rejected(self):
        self.assertFalse(validate_reply('“அன்பு இல்லாதவர் செல்வம் வேண்டாம்”', SOURCE['content']))

    def test_correct_verse_wrong_meaning_is_rejected(self):
        self.assertFalse(meaning_preserved('அன்பு இல்லாதவருக்கு செல்வம் பயனற்றது.', SOURCE))
        self.assertFalse(meaning_preserved(SOURCE['content'] + '\nஅன்பு இல்லாதவருக்கு செல்வம் பயனற்றது.', SOURCE))

    def test_reviewed_simplification_preserves_both_teaching_points(self):
        self.assertTrue(meaning_preserved(SOURCE['simplified_meaning'], SOURCE))
        self.assertFalse(meaning_preserved('அன்பு இல்லாதவர் எல்லாம் தனக்கே என நினைப்பார்.', SOURCE))

    def test_followups_keep_reference_without_repeated_greetings(self):
        turns = history('திருக்குறள்', 'yes', 'செய்யுள் பகுதி', 'திருக்குறள்', 'குறள் 7')
        for q in ['பொருள்', 'எளிமையாக விளக்கு', 'எளிமையாக', 'example', 'why?', 'இன்னொரு உதாரணம்']:
            ref = resolve_reference(q, turns)
            self.assertEqual((ref.kind, ref.number), ('textbook_sequence_number', '7'))
        self.assertEqual(resolve_reference('அடுத்து', turns).number, '8')
        self.assertNotIn('வணக்கம்', render_source_answer(SOURCE, 'பொருள்', True))

    def test_missing_mapping_never_substitutes_canonical(self):
        ref = resolve_reference('குறள் 7', history('செய்யுள் பகுதி'))
        self.assertIsNone(resolve_textbook(EvidenceDB([]), ref, 'tn', 6, 'Tamil'))
        d = route_question('குறள் 7', history('செய்யுள் பகுதி'), 'Tamil')
        self.assertEqual(d.kind, 'textbook')
        self.assertNotIn('தனக்குவமை', d.answer)

    def test_edition_conflict_and_unreviewed_rows_fail_closed(self):
        other = dict(SOURCE, edition='different')
        ref = resolve_reference('குறள் 7', history('செய்யுள் பகுதி'))
        self.assertIsNone(resolve_textbook(EvidenceDB([SOURCE, other]), ref, 'tn', 6, 'Tamil'))
        self.assertIsNone(resolve_textbook(EvidenceDB([dict(SOURCE, verification_status='unreviewed')]), ref, 'tn', 6, 'Tamil'))

    def test_board_grade_subject_isolation(self):
        ref = resolve_reference('குறள் 7', history('செய்யுள் பகுதி'))
        for b, g, s in [('cbse', 6, 'Tamil'), ('tn', 9, 'Tamil'), ('tn', 6, 'Science')]:
            self.assertIsNone(resolve_textbook(EvidenceDB([SOURCE]), ref, b, g, s))
        ref = resolve_reference('Explain photosynthesis', history('செய்யுள் பகுதி', 'குறள் 7'))
        self.assertIsNone(ref.number)

    def test_corpus_identity_boundaries_and_blocking(self):
        data = corpus()
        self.assertEqual([r['number'] for r in data['records']], list(range(1, 1331)))
        self.assertEqual(len(data['chapters']), 133)
        for r in data['records']:
            self.assertEqual(r['chapter'], (r['number'] - 1) // 10 + 1)
            self.assertEqual(len(r['lines']), 2)
            if r['status'] != 'verified':
                self.assertIsNone(lookup(r['number']))

    def test_exact_mathematics_and_bad_numeric_claim(self):
        self.assertIn('**1/2**', arithmetic_answer('1/3 + 1/6'))
        self.assertFalse(validate_subject_facts('2 + 3 = 6'))
        self.assertTrue(validate_subject_facts('2 + 3 = 5'))
        self.assertIsNone(arithmetic_answer('1/0'))
        self.assertIsNone(arithmetic_answer('__import__("os")'))

    def test_science_fact_and_contradiction(self):
        self.assertIn('H₂O', route_question('formula of water', [], 'Science').answer)
        self.assertFalse(validate_subject_facts("Water's chemical formula is CO2"))
        self.assertTrue(validate_subject_facts("Water's chemical formula is H₂O"))

    def test_fabricated_citations_and_pages(self):
        for answer in ['See https://made-up.example/book', 'According to your textbook, page 72 says love means wealth.']:
            self.assertFalse(validate_reply(answer, SOURCE['content']))

    def test_no_unverified_meaning_or_invented_example(self):
        row = dict(SOURCE, meaning_status='unreviewed')
        self.assertNotIn(SOURCE['source_meaning'], render_source_answer(row, 'meaning'))
        self.assertIn('not available', render_source_answer(SOURCE, 'example'))

    def test_generic_reviewed_sources_work_across_subjects(self):
        ref = resolve_reference('exercise 1.2 question 7')
        for subject in ('Mathematics', 'Science', 'English', 'Social Science'):
            row = dict(SOURCE, subject=subject, selection_ordinal=None,
                       exercise_number='1.2', question_number='7', canonical_reference=None,
                       content='Test-only passage', source_meaning='Test-only reviewed explanation',
                       simplified_meaning='Test-only simpler explanation')
            found = resolve_textbook(EvidenceDB([row]), ref, 'tn', 6, subject)
            self.assertEqual(found, row)
            self.assertIn(row['source_meaning'], render_source_answer(found, 'explain'))

    def test_no_followup_and_unresolved_literary_meaning(self):
        answer = route_question('no', history('original kural 7'), 'Tamil').answer
        self.assertIn('அடுத்த கேள்வி', answer)
        self.assertEqual(route_question('திருக்குறள் அன்பின் பொருள்', [], 'Tamil').kind, 'clarification')


if __name__ == '__main__':
    unittest.main()
