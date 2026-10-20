import unittest
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from signup_help import create_signup_help_router


class SignupHelpTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.query = self.db.table.return_value.select.return_value.eq.return_value.limit.return_value
        app = FastAPI()
        app.include_router(create_signup_help_router(self.db))
        self.client = TestClient(app)

    def post(self, **kwargs):
        return self.client.post("/auth/signup-phone-status",
                                headers={"Origin": "https://arivora.onrender.com"},
                                **kwargs)

    def test_existing_and_unused_number_without_profile_leak(self):
        for rows, expected in [([{"id": "private-id"}], True), ([], False)]:
            self.query.execute.return_value.data = rows
            response = self.post(json={"phone": "9000000000"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"registered": expected})
        self.db.table.return_value.select.return_value.eq.assert_called_with(
            "phone_number", "9000000000")

    def test_failure_is_not_duplicate_and_hides_internal_error(self):
        self.query.execute.side_effect = RuntimeError("private database details")
        response = self.post(json={"phone": "9000000000"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.text)

    def test_validation_origin_and_rate_limit(self):
        self.assertEqual(self.client.post("/auth/signup-phone-status",
                                         json={"phone": "9000000000"}).status_code, 403)
        for payload in [{"phone": "abc"}, {"phone": "9000000000", "email": "x"}]:
            self.assertEqual(self.post(json=payload).status_code, 422)
        self.assertEqual(self.post(content="x" * 257).status_code, 413)
        self.db.table.assert_not_called()
        self.query.execute.return_value.data = []
        for _ in range(57):
            self.assertEqual(self.post(json={"phone": "9000000000"}).status_code, 200)
        self.assertEqual(self.post(json={"phone": "9000000000"}).status_code, 429)
