import unittest
from unittest.mock import Mock
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from visitor_analytics import create_visitor_router

class VisitorTests(unittest.TestCase):
    def setUp(self):
        self.db=Mock(); app=FastAPI(); app.include_router(create_visitor_router(self.db)); self.client=TestClient(app)
        self.headers={'Origin':'https://arivora.onrender.com'}
        self.body={'event_id':str(uuid4()),'visitor_id':str(uuid4()),'source':'direct'}
    def test_private_minimal_write(self):
        response=self.client.post('/analytics/visit',json=self.body,headers=self.headers)
        self.assertEqual(response.status_code,204)
        args=self.db.rpc.call_args.args[1]
        self.assertEqual(set(args),{'event','visitor','referrer_source'})
        self.assertEqual(len(args['visitor']),64)
        self.assertNotEqual(args['visitor'],self.body['visitor_id'])
    def test_denies_other_origins_and_read_access(self):
        self.assertEqual(self.client.post('/analytics/visit',json=self.body).status_code,403)
        self.assertEqual(self.client.get('/analytics/visit').status_code,405)
        self.db.rpc.assert_not_called()
    def test_rejects_personal_data_invalid_ids_and_large_payloads(self):
        for payload in (self.body|{'email':'x@example.com'},self.body|{'visitor_id':'not-a-uuid'},self.body|{'source':'secret-url'}):
            self.assertEqual(self.client.post('/analytics/visit',json=payload,headers=self.headers).status_code,422)
        self.assertEqual(self.client.post('/analytics/visit',content='x'*1025,headers=self.headers).status_code,413)
        self.db.rpc.assert_not_called()
    def test_rate_limit_and_database_failure(self):
        self.db.rpc.side_effect=RuntimeError('internal credentials')
        response=self.client.post('/analytics/visit',json=self.body,headers=self.headers)
        self.assertEqual(response.status_code,503); self.assertNotIn('credentials',response.text)
        self.db.rpc.side_effect=None
        for _ in range(29): self.client.post('/analytics/visit',json=self.body,headers=self.headers)
        self.assertEqual(self.client.post('/analytics/visit',json=self.body,headers=self.headers).status_code,429)
