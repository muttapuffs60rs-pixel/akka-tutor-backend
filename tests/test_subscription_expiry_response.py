import ast
import unittest
from pathlib import Path
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]

class SubscriptionExpiryResponseTests(unittest.TestCase):
    def test_admission_errors_show_subscription_message(self):
        for folder in ('.',):
            tree = ast.parse((ROOT / folder / 'main.py').read_text(encoding='utf-8'))
            block = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                         and ast.unparse(n.test) == "not credit_admission or credit_admission.get('error')")
            module = ast.fix_missing_locations(ast.Module(body=[block], type_ignores=[]))
            code = compile(module, 'admission_response', 'exec')
            for error, status in [('subscription_expired', 403), ('credit_limit', 403), ('credit_busy', 409)]:
                with self.subTest(backend=folder, error=error):
                    with self.assertRaises(HTTPException) as caught:
                        exec(code, {'credit_admission': {'error': error}, 'HTTPException': HTTPException})
                    response = caught.exception
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.headers['X-Chat-Error'], error)
                    if status == 403:
                        self.assertIn('Please subscribe to continue.', response.detail)
                    if error == 'subscription_expired':
                        self.assertIn('Your subscription has expired.', response.detail)
                        self.assertIn('plan tokens are no longer available', response.detail)
            exec(code, {'credit_admission': {'enabled': False}, 'HTTPException': HTTPException})

if __name__ == '__main__':
    unittest.main(verbosity=2)
