import sys

def patch():
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Imports and Security Dependency
    content = content.replace(
        'from fastapi import FastAPI, HTTPException\n',
        'from fastapi import FastAPI, HTTPException, Depends, Security\nfrom fastapi.security import HTTPBearer, HTTPAuthorizationCredentials\n'
    )

    # 2. Update ChatRequest & QuizRequest
    content = content.replace(
        'class ChatRequest(BaseModel):\n    user_id: str\n    question: str',
        'class ChatRequest(BaseModel):\n    question: str'
    )
    content = content.replace(
        'class QuizRequest(BaseModel):\n    user_id: str\n    subject: str',
        'class QuizRequest(BaseModel):\n    subject: str'
    )

    # 3. Update OrderRequest & VerifyPaymentRequest
    content = content.replace(
        'class OrderRequest(BaseModel):\n    amount: int',
        'class OrderRequest(BaseModel):\n    tier_id: str'
    )
    content = content.replace(
        'class VerifyPaymentRequest(BaseModel):\n    razorpay_payment_id: str\n    razorpay_order_id: str\n    razorpay_signature: str\n    user_id: str\n    tier_name: str\n    days: int',
        'class VerifyPaymentRequest(BaseModel):\n    razorpay_payment_id: str\n    razorpay_order_id: str\n    razorpay_signature: str'
    )

    # 4. Insert Security logic before Helpers
    security_block = """
# ==========================================
# 2.5. SECURITY
# ==========================================
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    try:
        user_resp = supabase.auth.get_user(token)
        if not user_resp or not user_resp.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_resp.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

TIER_PRICES = {
    "tier_49_daily": {"amount": 49, "days": 1},
    "tier_199": {"amount": 199, "days": 30},
    "tier_499": {"amount": 499, "days": 30}
}

"""
    content = content.replace(
        '# ==========================================\n# 3. HELPERS\n# ==========================================',
        security_block + '# ==========================================\n# 3. HELPERS\n# =========================================='
    )

    # 5. Patch /ask
    content = content.replace(
        '@app.post("/ask")\nasync def chat_handler(data: ChatRequest):',
        '@app.post("/ask")\nasync def chat_handler(data: ChatRequest, user_id: str = Depends(get_current_user)):'
    )
    content = content.replace('.eq("id", data.user_id)', '.eq("id", user_id)')
    content = content.replace('data.user_id,', 'user_id,')

    # 6. Patch /generate-quiz
    content = content.replace(
        '@app.post("/generate-quiz")\nasync def generate_quiz(data: QuizRequest):',
        '@app.post("/generate-quiz")\nasync def generate_quiz(data: QuizRequest, user_id: str = Depends(get_current_user)):'
    )

    # 7. Patch /create-order
    old_create_order = """@app.post("/create-order")
async def create_order(req: OrderRequest):
    if not razorpay_client:
        raise HTTPException(status_code=500, detail="Razorpay not configured")
    try:
        order_amount = req.amount * 100 # convert to paise
        order_currency = 'INR'
        order_receipt = 'order_rcptid_11'
        notes = {'Shipping address': 'N/A'}
        
        response = razorpay_client.order.create(dict(amount=order_amount, currency=order_currency, receipt=order_receipt, notes=notes))
        return response"""

    new_create_order = """@app.post("/create-order")
async def create_order(req: OrderRequest, user_id: str = Depends(get_current_user)):
    if not razorpay_client:
        raise HTTPException(status_code=500, detail="Razorpay not configured")
    try:
        tier_info = TIER_PRICES.get(req.tier_id)
        if not tier_info:
            raise HTTPException(status_code=400, detail="Invalid tier_id")
            
        order_amount = tier_info['amount'] * 100 # convert to paise
        order_currency = 'INR'
        order_receipt = f'rcpt_{user_id[:8]}'
        notes = {'tier_id': req.tier_id, 'user_id': user_id}
        
        response = razorpay_client.order.create(dict(amount=order_amount, currency=order_currency, receipt=order_receipt, notes=notes))
        return response"""
    
    content = content.replace(old_create_order, new_create_order)

    # 8. Patch /verify-payment
    old_verify_payment = """@app.post("/verify-payment")
async def verify_payment(req: VerifyPaymentRequest):
    if not razorpay_client:
        raise HTTPException(status_code=500, detail="Razorpay not configured")
    try:
        # Verify Signature
        params_dict = {
            'razorpay_order_id': req.razorpay_order_id,
            'razorpay_payment_id': req.razorpay_payment_id,
            'razorpay_signature': req.razorpay_signature
        }
        
        razorpay_client.utility.verify_payment_signature(params_dict)
        
        # Payment is verified, update the user's subscription
        from datetime import datetime, timedelta
        
        if req.tier_name == 'tier_49_daily':
            now = datetime.now()
            expiry = datetime(now.year, now.month, now.day, 23, 59, 59)
        else:
            expiry = datetime.now() + timedelta(days=req.days)
            
        expiry_date = expiry.isoformat()
        
        # Fetch current profile
        res = supabase.table('profiles').select('subscription_tier, previous_tier').eq('id', req.user_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="User not found")
            
        current_tier = res.data[0].get('subscription_tier', 'free')
        previous_tier = res.data[0].get('previous_tier')
        
        if req.tier_name == 'tier_49_daily' and current_tier != 'tier_49_daily' and current_tier != 'free':
            previous_tier = current_tier
            
        if req.tier_name != 'tier_49_daily':
            previous_tier = None
            
        supabase.table('profiles').update({
            'subscription_tier': req.tier_name,
            'subscription_expires_at': expiry_date,
            'previous_tier': previous_tier
        }).eq('id', req.user_id).execute()
        
        return {"status": "success", "message": "Payment verified and subscription updated"}"""

    new_verify_payment = """@app.post("/verify-payment")
async def verify_payment(req: VerifyPaymentRequest, auth_user_id: str = Depends(get_current_user)):
    if not razorpay_client:
        raise HTTPException(status_code=500, detail="Razorpay not configured")
    try:
        # Verify Signature
        params_dict = {
            'razorpay_order_id': req.razorpay_order_id,
            'razorpay_payment_id': req.razorpay_payment_id,
            'razorpay_signature': req.razorpay_signature
        }
        
        razorpay_client.utility.verify_payment_signature(params_dict)
        
        # Fetch order from Razorpay to get the trusted tier_id and user_id
        order = razorpay_client.order.fetch(req.razorpay_order_id)
        notes = order.get('notes', {})
        
        tier_id = notes.get('tier_id')
        order_user_id = notes.get('user_id')
        
        if order_user_id != auth_user_id:
            raise HTTPException(status_code=403, detail="Order user mismatch")
            
        tier_info = TIER_PRICES.get(tier_id)
        if not tier_info:
            raise HTTPException(status_code=400, detail="Invalid tier in order notes")
            
        # Payment is verified, update the user's subscription
        from datetime import datetime, timedelta
        
        if tier_id == 'tier_49_daily':
            now = datetime.now()
            expiry = datetime(now.year, now.month, now.day, 23, 59, 59)
        else:
            expiry = datetime.now() + timedelta(days=tier_info['days'])
            
        expiry_date = expiry.isoformat()
        
        # Fetch current profile
        res = supabase.table('profiles').select('subscription_tier, previous_tier').eq('id', auth_user_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="User not found")
            
        current_tier = res.data[0].get('subscription_tier', 'free')
        previous_tier = res.data[0].get('previous_tier')
        
        if tier_id == 'tier_49_daily' and current_tier != 'tier_49_daily' and current_tier != 'free':
            previous_tier = current_tier
            
        if tier_id != 'tier_49_daily':
            previous_tier = None
            
        supabase.table('profiles').update({
            'subscription_tier': tier_id,
            'subscription_expires_at': expiry_date,
            'previous_tier': previous_tier
        }).eq('id', auth_user_id).execute()
        
        return {"status": "success", "message": "Payment verified and subscription updated"}"""

    content = content.replace(old_verify_payment, new_verify_payment)

    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("Patched main.py successfully")

if __name__ == '__main__':
    patch()
