import unittest
from verify_curriculum_text import compare_passage, formatting_normalize


class CurriculumVerificationTests(unittest.TestCase):
    def compare(self,a,b,**kw):
        return compare_passage(a,b,source_identified=kw.get('source',True),page_identified=kw.get('page',True))['status']

    def test_only_layout_changes_are_accepted(self):
        text='The average speed is distance travelled divided by elapsed time.'
        self.assertEqual(self.compare(text,'Header\n'+text+'\nFooter'),'exact_match')
        self.assertEqual(self.compare(text,text.replace(' ','\n')),'formatting_only')
        self.assertEqual(self.compare(text,text.replace('distance','displacement')),'substantive_discrepancy')

    def test_no_source_or_corrupt_extraction_cannot_pass(self):
        text='A cell is a basic unit of life and has a plasma membrane.'
        self.assertEqual(self.compare(text,text,source=False),'unverifiable')
        self.assertEqual(self.compare(text,text,page=False),'unverifiable')
        self.assertEqual(self.compare(text+'\ufffd',text+'\ufffd'),'unverifiable')

    def test_formula_signs_and_tamil_letters_are_never_erased(self):
        prefix='This sentence supplies enough surrounding context: '
        for a,b in [('H₂O','H₂O₂'),('v = u + at','v = u - at'),('அன்பிலார்','அன்புளார்'),('m²','m³')]:
            self.assertEqual(self.compare(prefix+a,prefix+b),'substantive_discrepancy')
        self.assertNotEqual(formatting_normalize('H₂O'),formatting_normalize('H2O'))
