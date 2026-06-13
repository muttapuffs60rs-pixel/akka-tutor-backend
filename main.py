# pyrefly: ignore [missing-import]
import os, io, asyncio, traceback, requests, uvicorn, easyocr, functools, base64, random, string
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from prompts import AKKA_TUTOR_SYSTEM_PROMPT, AKKA_QUIZ_PROMPT
import razorpay

# ==========================================
# 1. SETUP
# ==========================================

load_dotenv()

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

deepseek_llm = ChatDeepSeek(
    model="deepseek-v4-flash",
    api_key=os.getenv("DEEPSEEK_API_KEY")
)

# Gemini Flash Vision — used as fallback when OCR yields < 10 words (graphs/diagrams)
gemini_vision = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

ocr_reader = easyocr.Reader(['en'], gpu=False)

try:
    razorpay_client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))
    razorpay_client.session.verify = False
    import urllib3
    urllib3.disable_warnings()
except Exception as e:
    print(f"Failed to initialize Razorpay: {e}")
    razorpay_client = None

app = FastAPI(title="Akka Tutor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 2. DATA MODELS
# ==========================================

class ChatRequest(BaseModel):
    question: str
    subject: str
    grade_level: int
    image_url: Optional[str] = None
    history: List[dict] = []  # FIXED: Added history back so the backend accepts Flutter's memory payload

class QuizRequest(BaseModel):
    subject: str
    units: List[str]
    grade_level: int
    num_questions: int = 5

class QuizResponse(BaseModel):
    questions: List[dict] = Field(
        description="List of MCQs with question, options, and answer"
    )

class OrderRequest(BaseModel):
    tier_id: str

class VerifyPaymentRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str


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

# ==========================================
# 3. HELPERS
# ==========================================

@functools.lru_cache(maxsize=1000)
def get_context(query: str, subject: str, grade: int,
                threshold=0.1, count=5):
    try:
        import re
        chunks = []
        
        # 1. EXPLICIT SQL MATCHING (Fixes the "Section 4.11" issue)
        # Vector search is terrible for pure numbers. If the student asks for "4.11.2", explicitly query the DB.
        section_match = re.search(r'\b(\d+\.\d+(?:\.\d+)?)\b', query)
        if section_match:
            sec_num = section_match.group(1)
            try:
                exact_res = supabase.table("documents").select("content, unit_name, section_name, sub_section_name") \
                    .eq("grade_level", grade) \
                    .eq("subject", subject) \
                    .or_(f"section_name.ilike.%{sec_num}%,sub_section_name.ilike.%{sec_num}%,content.ilike.%{sec_num}%") \
                    .limit(3) \
                    .execute()
                    
                if exact_res.data:
                    for meta in exact_res.data:
                        metadata_header = ""
                        if meta.get('unit_name') or meta.get('section_name'):
                            metadata_header = f"[{meta.get('unit_name', '')} -> {meta.get('section_name', '')} -> {meta.get('sub_section_name', '')}]\n"
                        chunks.append(metadata_header + meta.get("content", ""))
            except Exception as e:
                print(f"Exact match lookup failed: {e}")

        # 2. VECTOR SEARCH (Fallback & Context enrichment)
        vector = embeddings.embed_query(query)

        # Cast grade safely to string to defend against internal RPC parsing failures
        rpc = supabase.rpc("hybrid_match_documents", {
            "query_embedding": vector,
            "query_text": query,
            "match_threshold": threshold,
            "match_count": count,
            "filter_grade": str(grade),
            "filter_subject": str(subject)
        }).execute()

        # The RPC only returns 'content' and 'similarity'. 
        # We must look up the structural metadata for these chunks!
        if rpc.data:
            returned_contents = [r["content"] for r in rpc.data if "content" in r]
            # Fetch metadata from documents table where content matches
            meta_res = supabase.table("documents").select("content, unit_name, section_name, sub_section_name").in_("content", returned_contents).execute()
            
            # Create a lookup map
            meta_map = {row["content"]: row for row in meta_res.data}
            
            for r in rpc.data:
                c = r.get("content", "")
                # Prevent duplicates if exact match already found it
                if any(c in existing_chunk for existing_chunk in chunks):
                    continue
                    
                meta = meta_map.get(c, {})
                metadata_header = ""
                if meta.get('unit_name') or meta.get('section_name'):
                    metadata_header = f"[{meta.get('unit_name', '')} -> {meta.get('section_name', '')} -> {meta.get('sub_section_name', '')}]\n"
                chunks.append(metadata_header + c)

        return "\n---\n".join(chunks) if chunks else "No specific textbook context found."
    except Exception as rpc_err:
        print(f"RPC Context lookup error (falling back): {rpc_err}")
        return "No specific textbook context found."

def get_profile(user_id: str, field: str):
    res = supabase.table("profiles").select(field).eq("id", user_id).execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")

    raw_val = res.data[0].get(field)
    return raw_val if raw_val is not None else 0

def update_profile(user_id: str, field: str, value: int):
    supabase.table("profiles").update({
        field: int(value)
    }).eq("id", user_id).execute()

# ==========================================
# 4. CHAT ROUTE
# ==========================================

@app.post("/ask")
async def chat_handler(data: ChatRequest, user_id: str = Depends(get_current_user)):
    try:
        # Prepare context search query early
        clean_question = data.question.strip() if data.question else ""
        search_query = clean_question
        if data.history and len(clean_question.split()) < 10:
            last_user_question = ""
            for msg in reversed(data.history):
                if msg.get("role") == "user":
                    last_user_question = msg.get("content", "")
                    break
            if last_user_question:
                search_query = f"{last_user_question} {clean_question}"

        extracted_text = None
        image_bytes = None
        image_mime = "image/jpeg"
        used_vision_model = False

        if data.image_url and data.image_url.strip():
            await asyncio.sleep(1)
            image_resp = await asyncio.to_thread(requests.get, data.image_url, timeout=15)
            image_bytes = image_resp.content

            # Detect MIME type from Content-Type header (fallback to jpeg)
            content_type = image_resp.headers.get("Content-Type", "")
            if "png" in content_type:
                image_mime = "image/png"
            elif "webp" in content_type:
                image_mime = "image/webp"

            # --- Step 1: Try EasyOCR (fast, good for text-heavy images) ---
            extracted = await asyncio.to_thread(
                ocr_reader.readtext,
                image_bytes,
                detail=0,
                paragraph=True
            )
            ocr_text = " ".join(extracted).strip() if extracted else ""

            # --- Step 2: Hybrid fallback — if OCR yields < 10 words, use Gemini Vision ---
            # Graphs, diagrams, and handwritten math return very little OCR text.
            if len(ocr_text.split()) < 10:
                print(f"[Vision] OCR too sparse ({len(ocr_text.split())} words). Switching to Gemini Vision.")
                used_vision_model = True
                b64_image = base64.b64encode(image_bytes).decode("utf-8")
                vision_prompt = [
                    HumanMessage(content=[
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{image_mime};base64,{b64_image}"}
                        },
                        {
                            "type": "text",
                            "text": (
                                "You are an expert at reading Tamil Nadu State Board school textbook questions. "
                                "Describe the image in detail: include all text, labels, graph shapes, axes, and any visual elements. "
                                "If there are multiple sub-graphs (i), (ii), (iii), etc., describe each one separately. "
                                "Be precise and thorough so another AI can answer the student's question."
                            )
                        }
                    ])
                ]
                vision_response = await asyncio.to_thread(gemini_vision.invoke, vision_prompt)
                extracted_text = vision_response.content
                print(f"[Vision] Gemini description: {extracted_text[:200]}...")
            else:
                extracted_text = ocr_text
                print(f"[OCR] Extracted {len(ocr_text.split())} words from image.")

            search_query = f"{search_query} {extracted_text}"

        # 1. Fire Profile Fetch and Context Fetch concurrently
        def fetch_profile():
            return supabase.table("profiles").select("chats_today, subscription_tier, previous_tier, last_active_date").eq("id", user_id).execute()
        
        profile_task = asyncio.create_task(asyncio.to_thread(fetch_profile))
        
        context_task = asyncio.create_task(asyncio.to_thread(
            get_context,
            search_query if search_query.strip() else "textbook page",
            data.subject,
            data.grade_level
        ))

        profile_res = await profile_task
        if not profile_res.data:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        user_profile = profile_res.data[0]
        
        raw_chats = user_profile.get("chats_today")
        chats_today = int(raw_chats) if raw_chats is not None else 0
        
        raw_tier = user_profile.get("subscription_tier")
        user_tier = str(raw_tier).strip().lower() if raw_tier is not None else "free"

        prev_tier = user_profile.get("previous_tier")
        last_active = user_profile.get("last_active_date")

        from datetime import datetime, timedelta
        
        # Calculate IST (UTC + 5:30)
        ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        today_str = ist_now.strftime('%Y-%m-%d')

        # LAZY RESET LOGIC ON BACKEND
        if last_active != today_str:
            chats_today = 0
            if user_tier == "tier_49_daily":
                user_tier = prev_tier if prev_tier else "free"
                prev_tier = None
            
            # Force the update in DB so we are in sync (fire and forget)
            def update_lazy_reset():
                supabase.table("profiles").update({
                    "chats_today": chats_today,
                    "subscription_tier": user_tier,
                    "previous_tier": prev_tier,
                    "last_active_date": today_str
                }).eq("id", user_id).execute()
            asyncio.create_task(asyncio.to_thread(update_lazy_reset))

        # Enforce accurate subscription package ceilings and custom messaging
        max_allowed_chats = 5  
        limit_message = "Daily limit reached. Upgrade to Pro!"
        
        if user_tier == "tier_199":
            max_allowed_chats = 50
            limit_message = "Your limit per day is over. Upgrade your plan to get more daily questions!"
        elif user_tier == "tier_499":
            max_allowed_chats = 150
            limit_message = "Your limit per day is over. Upgrade your plan to get more daily questions!"
        elif user_tier in ["tier_49_daily", "admin"]:
            max_allowed_chats = 999999  

        # Enforce subscription cap barriers dynamically
        if user_tier not in ["admin", "tier_49_daily"] and chats_today >= max_allowed_chats:
            async def paywall_generator():
                yield f"__PAYWALL__{limit_message}"
            return StreamingResponse(paywall_generator(), media_type="text/plain")

        # 2. Wait for context task only after user passed the paywall
        context = await context_task

        # Process history array into proper LangChain message objects for continuity
        formatted_history = []
        for msg in data.history:
            if msg.get("role") == "user":
                formatted_history.append(HumanMessage(content=msg.get("content", "")))
            elif msg.get("role") == "assistant":
                formatted_history.append(AIMessage(content=msg.get("content", "")))

        # ==================================
        # PROMPT CONSTRUCTION
        # ==================================
        if extracted_text is not None:
            system_prompt = f"""
SYSTEM:
{AKKA_TUTOR_SYSTEM_PROMPT.format(context=context)}

INSTRUCTIONS:
- Explain clearly in Tanglish
- Use TN State Board style
- Give point-wise answers
- Keep it easy for students
"""
            # Tailor the user message based on whether Gemini Vision described the image
            if used_vision_model:
                user_msg = (
                    f"I uploaded an image. A vision AI described its contents as follows:\n\n"
                    f"{extracted_text}\n\n"
                    f"Based on this description, my question is: {clean_question if clean_question else 'Please explain what is shown in this image.'}"
                )
            else:
                user_msg = f"I have uploaded a new image. Here is the text extracted from it:\n\n{extracted_text}\n\nMy question is: {clean_question if clean_question else 'Please explain the contents of this new image.'}"
            # Inject history into the prompt stream
            messages = [SystemMessage(content=system_prompt)] + formatted_history + [HumanMessage(content=user_msg)]

        # ==================================
        # NORMAL TEXT FLOW
        # ==================================
        else:
            system_prompt = AKKA_TUTOR_SYSTEM_PROMPT.format(context=context)
            # Inject history into the prompt stream
            messages = [SystemMessage(content=system_prompt)] + formatted_history + [HumanMessage(content=clean_question)]

        # Define the streaming generator
        async def response_generator():
            try:
                # Call LLM Engine and stream chunks
                async for chunk in deepseek_llm.astream(messages):
                    if chunk.content:
                        yield chunk.content
                
                # Database Counter Increment Execution (happens after successful stream finishes)
                asyncio.create_task(asyncio.to_thread(
                    update_profile,
                    user_id,
                    "chats_today", 
                    chats_today + 1
                ))
            except Exception as stream_e:
                print(f"Streaming Exception: {stream_e}")
                yield f"\n\n[Error generating response: {str(stream_e)}]"

        return StreamingResponse(response_generator(), media_type="text/plain")

    except Exception as e:
        print("--- CRITICAL SERVER EXCEPTION TRACEBACK ---")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 5. QUIZ ROUTE
# ==========================================

@app.post("/generate-quiz")
async def generate_quiz(data: QuizRequest, user_id: str = Depends(get_current_user)):
    try:
        quizzes_today = await asyncio.to_thread(get_profile, user_id, "quizzes_today")

        if quizzes_today >= 5:
            raise HTTPException(
                status_code=403,
                detail="Daily quiz limit reached"
            )

        search_query = f"{data.subject} Units: {', '.join(data.units)}"

        context = await asyncio.to_thread(
            get_context,
            search_query,
            data.subject,
            data.grade_level,
            threshold=0.3,
            count=8
        )

        quiz_prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                AKKA_QUIZ_PROMPT + "\n\nContext:\n{context}"
            ),
            (
                "human",
                "Generate {num} MCQs based on syllabus."
            )
        ])

        chain = (
            quiz_prompt
            | deepseek_llm.with_structured_output(QuizResponse)
        )

        quiz_data = await chain.ainvoke({
            "num": data.num_questions,
            "context": context
        })

        asyncio.create_task(asyncio.to_thread(
            update_profile,
            user_id,
            "quizzes_today",
            quizzes_today + 1
        ))

        return quiz_data

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 6. PAYMENTS
# ==========================================

@app.post("/create-order")
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
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/verify-payment")
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
        from datetime import datetime, timedelta, timezone
        
        # IST = UTC + 5:30
        IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(IST)
        
        if tier_id == 'tier_49_daily':
            # Expires at 11:59:59 PM IST today
            expiry = now_ist.replace(hour=23, minute=59, second=59, microsecond=0)
        else:
            # Monthly plans: exactly 30 days from now in IST
            expiry = now_ist + timedelta(days=tier_info['days'])
            
        start_date  = now_ist.isoformat()   # IST timestamp
        expiry_date = expiry.isoformat()    # IST timestamp

        
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
            'subscription_start_date': start_date,   # ← NOW SAVED
            'subscription_expires_at': expiry_date,
            'previous_tier': previous_tier
        }).eq('id', auth_user_id).execute()
        
        return {"status": "success", "message": "Payment verified and subscription updated"}
        
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Payment Signature")
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 7. LIVE QUIZ
# ==========================================

class LiveQuizCreate(BaseModel):
    title: str
    questions: List[dict]

class StudentAnswerRequest(BaseModel):
    question_id: str
    submitted_answer: str
    student_name: str

def _generate_session_code() -> str:
    """Generate a unique 6-char alphanumeric code, retried on collision."""
    chars = string.ascii_uppercase + string.digits
    for _ in range(10):
        code = ''.join(random.choices(chars, k=6))
        existing = supabase.table('quiz_sessions').select('id').eq('session_code', code).execute()
        if not existing.data:
            return code
    raise RuntimeError("Could not generate unique session code")

@app.post("/live-quiz/create")
async def create_live_quiz(data: LiveQuizCreate, teacher_id: str = Depends(get_current_user)):
    try:
        session_code = _generate_session_code()
        session = supabase.table('quiz_sessions').insert({
            'session_code': session_code,
            'teacher_id': teacher_id,
            'title': data.title,
            'status': 'waiting',
            'current_question_index': -1
        }).execute()
        session_id = session.data[0]['id']

        questions = []
        for i, q in enumerate(data.questions):
            questions.append({
                'session_id': session_id,
                'question_text': q['question_text'],
                'question_type': q['question_type'],
                'options': q.get('options'),
                'correct_answer': q['correct_answer'],
                'points': q.get('points', 1),
                'sort_order': q.get('sort_order', i)
            })
        supabase.table('quiz_questions').insert(questions).execute()

        return {
            'session_id': session_id,
            'session_code': session_code,
            'title': data.title,
            'question_count': len(data.questions)
        }
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/live-quiz/{code}")
async def get_live_quiz(code: str, user_id: str = Depends(get_current_user)):
    try:
        session = supabase.table('quiz_sessions').select('*').eq('session_code', code.upper()).execute()
        if not session.data:
            raise HTTPException(status_code=404, detail="Session not found")
        s = session.data[0]
        is_teacher = s['teacher_id'] == user_id

        questions_res = supabase.table('quiz_questions').select('*').eq('session_id', s['id']).order('sort_order').execute()
        q_list = []
        for q in questions_res.data:
            item = {k: q[k] for k in ('id', 'question_text', 'question_type', 'options', 'sort_order', 'points')}
            if is_teacher:
                item['correct_answer'] = q['correct_answer']
            q_list.append(item)

        return {**s, 'questions': q_list, 'is_teacher': is_teacher}
    except HTTPException:
        raise
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/live-quiz/{code}/start")
async def start_live_quiz(code: str, teacher_id: str = Depends(get_current_user)):
    try:
        session = supabase.table('quiz_sessions').select('id,teacher_id,status').eq('session_code', code.upper()).execute()
        if not session.data:
            raise HTTPException(status_code=404, detail="Session not found")
        s = session.data[0]
        if s['teacher_id'] != teacher_id:
            raise HTTPException(status_code=403, detail="Only the teacher can start this quiz")
        if s['status'] != 'waiting':
            raise HTTPException(status_code=400, detail="Quiz already started")
        supabase.table('quiz_sessions').update({
            'status': 'active', 'current_question_index': 0
        }).eq('id', s['id']).execute()
        return {"status": "active", "current_question_index": 0}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/live-quiz/{code}/next")
async def next_question(code: str, teacher_id: str = Depends(get_current_user)):
    try:
        session = supabase.table('quiz_sessions').select('id,teacher_id,status,current_question_index').eq('session_code', code.upper()).execute()
        if not session.data:
            raise HTTPException(status_code=404, detail="Session not found")
        s = session.data[0]
        if s['teacher_id'] != teacher_id:
            raise HTTPException(status_code=403, detail="Only the teacher can advance the quiz")
        if s['status'] != 'active':
            raise HTTPException(status_code=400, detail="Quiz is not active")

        q_count = supabase.table('quiz_questions').select('id', count='exact').eq('session_id', s['id']).execute()
        total = q_count.count or 0
        next_index = s['current_question_index'] + 1

        if next_index >= total:
            supabase.table('quiz_sessions').update({
                'status': 'completed', 'current_question_index': next_index
            }).eq('id', s['id']).execute()
            return {"status": "completed", "current_question_index": next_index}

        supabase.table('quiz_sessions').update({'current_question_index': next_index}).eq('id', s['id']).execute()
        return {"status": "active", "current_question_index": next_index}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/live-quiz/{code}/complete")
async def complete_live_quiz(code: str, teacher_id: str = Depends(get_current_user)):
    try:
        session = supabase.table('quiz_sessions').select('id,teacher_id').eq('session_code', code.upper()).execute()
        if not session.data:
            raise HTTPException(status_code=404, detail="Session not found")
        s = session.data[0]
        if s['teacher_id'] != teacher_id:
            raise HTTPException(status_code=403, detail="Only the teacher can end this quiz")
        supabase.table('quiz_sessions').update({'status': 'completed'}).eq('id', s['id']).execute()
        return {"status": "completed"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/live-quiz/{code}/answer")
async def submit_answer(code: str, data: StudentAnswerRequest, student_id: str = Depends(get_current_user)):
    try:
        session = supabase.table('quiz_sessions').select('id,status,current_question_index').eq('session_code', code.upper()).execute()
        if not session.data:
            raise HTTPException(status_code=404, detail="Session not found")
        s = session.data[0]
        if s['status'] != 'active':
            raise HTTPException(status_code=400, detail="Quiz is not active")

        question = supabase.table('quiz_questions').select('correct_answer,question_type,sort_order').eq('id', data.question_id).execute()
        if not question.data:
            raise HTTPException(status_code=404, detail="Question not found")
        q = question.data[0]

        if q['sort_order'] != s['current_question_index']:
            raise HTTPException(status_code=400, detail="This question is not currently active")

        submitted = data.submitted_answer.strip()
        correct = q['correct_answer'].strip()
        if q['question_type'] == 'fill_blank':
            is_correct = submitted.lower() == correct.lower()
        else:
            is_correct = submitted == correct

        try:
            supabase.table('quiz_responses').insert({
                'session_id': s['id'],
                'student_id': student_id,
                'student_name': data.student_name,
                'question_id': data.question_id,
                'submitted_answer': submitted,
                'is_correct': is_correct
            }).execute()
        except Exception:
            raise HTTPException(status_code=409, detail="Already answered this question")

        return {"is_correct": is_correct, "correct_answer": correct}
    except HTTPException:
        raise
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/live-quiz/{code}/leaderboard")
async def get_leaderboard(code: str, user_id: str = Depends(get_current_user)):
    try:
        session = supabase.table('quiz_sessions').select('id').eq('session_code', code.upper()).execute()
        if not session.data:
            raise HTTPException(status_code=404, detail="Session not found")
        result = supabase.rpc('get_session_leaderboard', {'target_session_id': session.data[0]['id']}).execute()
        return {"leaderboard": result.data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 8. SERVER
# ==========================================

@app.get("/health-load")
async def health_load():
    """Safe endpoint for load testing server capacity."""
    # Simulate an average database lookup and processing latency
    await asyncio.sleep(0.5)
    return {"status": "ok", "message": "Load test simulated delay successful."}

# Application
if __name__ == "__main__":
    uvicorn.run(
        "main:app",  # Fixed string format to enable reload
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True  # Added reload for local development testing
    )