import unittest
from unittest.mock import MagicMock
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from profile_activity import create_profile_activity_router


class ProfileActivityTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.query = self.db.table.return_value
        for method in ('select', 'eq', 'gt', 'order', 'range'):
            getattr(self.query, method).return_value = self.query
        self.query.execute.return_value.data = [{
            'id': str(i), 'session_id': 'owned-session', 'created_at': '2026-10-18T10:00:00Z',
            'learning_credits_charged': 3000, 'topup_credits_charged': 100,
            'response_source': 'cache', 'provider_secret': 'must never return',
        } for i in range(21)]

        def user(authorization: str | None = Header(None)):
            if authorization != 'Bearer synthetic-token':
                raise HTTPException(401, 'Sign in required')
            return 'signed-in-student'
        app = FastAPI()
        app.include_router(create_profile_activity_router(self.db, user))
        self.client = TestClient(app)
        self.headers = {'Authorization': 'Bearer synthetic-token'}

    def test_scopes_history_to_authenticated_user_and_pages_without_leaking_fields(self):
        response = self.client.get('/profile/activity?offset=20&user_id=somebody-else', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['items']), 20)
        self.assertTrue(body['has_more'])
        self.query.eq.assert_called_once_with('user_id', 'signed-in-student')
        self.query.range.assert_called_once_with(20, 40)
        self.assertEqual(set(body['items'][0]), {'id','created_at','session_id','credits_used','topup_credits_used','kind'})
        self.assertNotIn('provider_secret', response.text)
        self.assertEqual(body['items'][0]['kind'], 'Saved textbook answer')

    def test_requires_sign_in_and_bounds_pagination(self):
        self.assertEqual(self.client.get('/profile/activity').status_code, 401)
        for offset in (-1, 10001):
            self.assertEqual(self.client.get(f'/profile/activity?offset={offset}', headers=self.headers).status_code, 422)
        self.db.table.assert_not_called()

    def test_empty_history_and_private_error_handling(self):
        self.query.execute.return_value.data = []
        self.assertEqual(self.client.get('/profile/activity', headers=self.headers).json(), {'items': [], 'has_more': False})
        self.query.execute.side_effect = RuntimeError('private database configuration')
        response = self.client.get('/profile/activity', headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private database configuration', response.text)
