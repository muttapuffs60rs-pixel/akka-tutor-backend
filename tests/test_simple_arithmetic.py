import unittest
from simple_arithmetic import simple_product

class SimpleProductTests(unittest.TestCase):
    def test_exact_concise_answer(self):
        for q in ('1357*1357=', '1357 × 1357', ' 1357 x 1357 ? '):
            self.assertEqual(simple_product(q), '1357 × 1357 = 1,841,449')
    def test_signed_and_zero(self):
        self.assertEqual(simple_product('-12*3'), '-12 × 3 = -36')
        self.assertEqual(simple_product('0*999'), '0 × 999 = 0')
    def test_does_not_override_explanation_or_other_problems(self):
        for q in ('Explain 1357*1357', '1357*1357 step by step', 'x*x', '2*3+4', '2.5*4', '12 apples times 3', '9'*19+'*2', '__import__("os")'):
            self.assertIsNone(simple_product(q))
        self.assertIsNone(simple_product('2*3', 'photo.png'))

if __name__ == '__main__': unittest.main()
