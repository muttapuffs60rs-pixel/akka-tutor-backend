import unittest
from unittest.mock import MagicMock
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from referrals import create_referral_router
class ReferralTests(unittest.TestCase):
 def setUp(self):
  self.db=MagicMock()
  def user(authorization: str|None=Header(None)):
   if authorization!='Bearer synthetic': raise HTTPException(401,'Sign in')
   return 'verified-student'
  app=FastAPI(); app.include_router(create_referral_router(self.db,user)); self.client=TestClient(app)
  self.headers={'Authorization':'Bearer synthetic'}
 def test_identity_is_from_auth_not_request(self):
  self.db.rpc.return_value.execute.return_value.data={'code':'SAFE123','history':[]}
  self.assertEqual(self.client.get('/referrals?uid=another',headers=self.headers).status_code,200)
  self.db.rpc.assert_called_once_with('referral_summary',{'uid':'verified-student'})
 def test_claim_normalizes_code_and_ignores_forged_identity(self):
  self.db.rpc.return_value.execute.return_value.data={'success':True}
  self.assertEqual(self.client.post('/referrals/claim',headers=self.headers,json={'code':' abc123 ','uid':'another'}).status_code,200)
  self.db.rpc.assert_called_once_with('claim_referral',{'uid':'verified-student','code_value':'ABC123'})
 def test_requires_auth_and_handles_invalid_and_private_errors(self):
  self.assertEqual(self.client.get('/referrals').status_code,401)
  self.db.rpc.return_value.execute.return_value.data={'error':'Enter a valid friend referral code.'}
  self.assertEqual(self.client.post('/referrals/claim',headers=self.headers,json={'code':'bad'}).status_code,400)
  self.db.rpc.side_effect=RuntimeError('private-database-detail')
  r=self.client.get('/referrals',headers=self.headers)
  self.assertEqual(r.status_code,503); self.assertNotIn('private-database',r.text)
