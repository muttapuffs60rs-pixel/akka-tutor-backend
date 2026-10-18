import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

class ReferralClaim(BaseModel):
    code: str = Field(min_length=1, max_length=32)

def create_referral_router(database, get_current_user):
    router = APIRouter()
    @router.get('/referrals')
    async def summary(uid: str = Depends(get_current_user)):
        try:
            return await asyncio.to_thread(lambda: database.rpc('referral_summary', {'uid': uid}).execute().data)
        except Exception:
            raise HTTPException(503, 'Referral details are unavailable. Please retry.') from None
    @router.post('/referrals/claim')
    async def claim(body: ReferralClaim, uid: str = Depends(get_current_user)):
        try:
            result = await asyncio.to_thread(lambda: database.rpc('claim_referral', {'uid': uid, 'code_value': body.code.strip().upper()}).execute().data)
        except Exception:
            raise HTTPException(503, 'Could not save the referral. Please retry.') from None
        if result.get('error'):
            raise HTTPException(400, result['error'])
        return result
    return router
