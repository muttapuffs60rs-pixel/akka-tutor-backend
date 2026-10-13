import json
import unittest

from audit_disputed import agreement, translation_edition, tva_edition, kalaignar_edition, tamil_verse, ROOT
from educational_accuracy import canonical_answer, corpus, lookup


class DisputedAuditTests(unittest.TestCase):
    def test_no_majority_when_two_editions_support_each_reading(self):
        a = {'lines': ['அகர முதல', 'எழுத்தெல்லாம்']}
        b = {'lines': ['ஆதி பகவன்', 'முதற்றே உலகு']}
        self.assertIsNone(agreement({'a':[a], 'b':[a], 'c':[b], 'd':[b]}))
        self.assertIsNone(agreement({'a':[a, a], 'b':[a]}))
        self.assertEqual(len(agreement({'a':[a], 'b':[a]})), 2)

    def test_foreign_corruption_cannot_be_ignored(self):
        self.assertFalse(tamil_verse(['அகர¡ முதல', 'எழுத்தெல்லாம்']))
        self.assertFalse(tamil_verse(['அகரx முதல', 'எழுத்தெல்லாம்']))

    def test_number_chapter_and_ordinal_must_agree(self):
        raw='<p>2. அன்பு - Love</p><p>1. அகர முதல</p><p>எழுத்தெல்லாம்</p><p>English</p><p>Translation 11</p>'
        self.assertIn(11, translation_edition(raw)[0])
        self.assertFalse(translation_edition(raw.replace('Translation 11','Translation 12'))[0])
        raw='<p>2. அன்பு</p><p>1. அகர முதல</p><p>எழுத்தெல்லாம்</p><p>பொருள்</p><p>11</p>'
        self.assertIn(11, tva_edition(raw, 2))
        self.assertFalse(tva_edition(raw, 3))
        self.assertFalse(tva_edition('<p>java.lang.NullPointerException</p>', 2))

    def test_missing_commentary_is_explicit_and_never_mislabeled(self):
        row={'number':126,'chapter_name':'அடக்கம்','lines':['அகர முதல','எழுத்தெல்லாம்'],
             'gloss':'','source':'https://www.tamilvu.org/example'}
        answer=canonical_answer(row, False)
        self.assertIn('explanation has not yet been verified', answer)
        self.assertIn('Tamil Virtual Academy', answer)
        self.assertNotIn('Parimelazhagar', answer)
        self.assertNotIn('பரிமேலழகர்', canonical_answer(row, True))

    def test_kalaignar_requires_printed_consecutive_numbers(self):
        raw=''.join(f'<p>{n}.</p><p>அகர முதல</p><p>எழுத்தெல்லாம்</p><p>பொருள்</p>' for n in range(46,51))
        self.assertEqual(set(kalaignar_edition(raw,32)),set(range(46,51)))
        self.assertFalse(kalaignar_edition(raw,33))
        self.assertFalse(kalaignar_edition(raw.replace('48.','49.'),32))

    def test_every_adopted_record_has_exact_evidence_and_consistent_status(self):
        data=corpus()
        review=json.loads((ROOT/'dispute-review.json').read_text(encoding='utf-8'))
        report=json.loads((ROOT/'validation-report.json').read_text(encoding='utf-8'))
        if data['version'] != 'published-edition-crosscheck-v3':
            self.skipTest('continued audit has not been applied')
        self.assertEqual(review['reviewed'], 296)
        self.assertEqual(data['verified_count'] + review['blocked'], 1330)
        self.assertEqual(sum(f['status']=='blocked' for f in report['findings']), review['blocked'])
        for finding in review['findings']:
            row=lookup(finding['number'])
            if finding['status']=='blocked':
                self.assertIsNone(row)
            else:
                self.assertIsNotNone(row)
                self.assertEqual(row['lines'], finding['adopted_lines'])
                self.assertGreaterEqual(len(finding['agreeing_editions']), 2)
                self.assertEqual(bool(row['gloss']), finding['explanation_available'])


if __name__=='__main__':
    unittest.main()
