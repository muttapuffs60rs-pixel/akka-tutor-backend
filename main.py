# pyrefly: ignore [missing-import]
import os, io, asyncio, traceback, requests, uvicorn, easyocr, functools, base64, random, string, time
from typing import List, Optional
from uuid import UUID
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
from prompts import AKKA_QUIZ_PROMPT, TUTOR_CACHE_PROMPT, build_tutor_prompt
from image_security import download_chat_image
from chat_cost_controls import bounded_history, clip_text, MAX_REPLY_TOKENS
from answer_cache import AnswerCache, eligible_question
from answer_library_api import create_answer_library_router
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
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    timeout=90, max_retries=0, stream_usage=True,
    extra_body={"thinking": {"type": "disabled"}}
)

# Gemini Flash Vision — used as fallback when OCR yields < 10 words (graphs/diagrams)
gemini_vision = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    max_output_tokens=700, max_retries=0, timeout=90
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
    expose_headers=["X-Answer-Source", "X-Answer-Id", "X-Chat-Turns-Used"],
)

# ==========================================
# 2. DATA MODELS
# ==========================================

class ChatRequest(BaseModel):
    session_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    subject: str = Field(min_length=1, max_length=100)
    grade_level: int = Field(ge=6, le=12)
    image_url: Optional[str] = Field(default=None, max_length=2048)
    history: List[dict] = Field(default_factory=list, max_length=20)

class QuizRequest(BaseModel):
    subject: str
    units: List[str]
    grade_level: int = Field(ge=6, le=12)
    num_questions: int = Field(default=5, ge=1, le=25)
    section: str = "All Sections"

class QuizQuestion(BaseModel):
    question: str
    options: List[str] = Field(min_length=4, max_length=4)
    correct_answer: str
    explanation: str

class QuizResponse(BaseModel):
    questions: List[QuizQuestion] = Field(
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

answer_cache = AnswerCache(supabase, os.getenv("ANSWER_CACHE_SYLLABUS_VERSION", ""), TUTOR_CACHE_PROMPT + "|concise-900-v1")
app.include_router(create_answer_library_router(supabase, get_current_user))

TIER_PRICES = {
    "tier_49_daily": {"amount": 49, "days": 1},
    "tier_199": {"amount": 199, "days": 30},
    "tier_499": {"amount": 499, "days": 30}
}

# ==========================================
# 3. HELPERS
# ==========================================

@functools.lru_cache(maxsize=1000)
def _get_context_cached(query: str, subject: str, grade: int,
                        threshold, count, cache_epoch):
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
            meta_map = {}
            try:
                meta_res = supabase.table("documents").select("content, unit_name, section_name, sub_section_name") \
                    .eq("grade_level", grade).eq("subject", subject) \
                    .in_("content", returned_contents).execute()
                meta_map = {row["content"]: row for row in meta_res.data}
            except Exception:
                # Chapter labels are optional; preserve successfully retrieved textbook text.
                print("Textbook chapter labels unavailable; using retrieved passages")

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

        if not chunks:
            raise LookupError("No textbook matches")
        return "\n---\n".join(chunks)
    except Exception:
        # Exceptions must escape the LRU function so outages never become cached answers.
        raise


def get_context(query: str, subject: str, grade: int, threshold=0.1, count=5):
    for attempt in range(2):
        try:
            return _get_context_cached(query, subject, grade, threshold, count, int(time.time() // 300))
        except LookupError:
            break
        except Exception as error:
            print(f"Textbook lookup attempt {attempt + 1} failed: {type(error).__name__}")
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

def increment_profile(user_id: str, field: str):
    try:
        supabase.rpc("increment_profile_field", {
            "target_user_id": user_id,
            "field_name": field
        }).execute()
    except Exception as e:
        print(f"Error incrementing {field}: {e}")

def get_daily_profile(user_id: str):
    """Reset both daily counters atomically in the database using the IST date."""
    profile = supabase.rpc("reset_daily_usage", {"target_user_id": user_id}).execute().data
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    return profile

@app.get("/profile")
async def current_profile(user_id: str = Depends(get_current_user)):
    return await asyncio.to_thread(get_daily_profile, user_id)

# ==========================================
# 4. CHAT ROUTE
# ==========================================

@app.post("/ask")
async def chat_handler(data: ChatRequest, user_id: str = Depends(get_current_user)):
    reservation = await asyncio.to_thread(lambda: supabase.rpc("reserve_chat_request", {
        "target_user_id": user_id, "target_session_id": str(data.session_id)
    }).execute().data)
    errors = {
        "profile": (404, "User profile not found"),
        "session": (404, "Conversation not found"),
        "conversation_limit": (409, "This conversation has reached 10 questions. Start a new chat."),
        "daily_limit": (403, "Daily question allowance reached. Try again tomorrow."),
    }
    if not reservation or "error" in reservation:
        status, message = errors.get((reservation or {}).get("error"), (503, "Usage limits unavailable"))
        raise HTTPException(status_code=status, detail=message)
    request_id = reservation["request_id"]
    usage = {}
    vision_usage = {}
    answer_cache_id = None
    response_source = "ai"

    async def save_usage(status):
        # Missing metadata stays NULL: never report an interrupted request as free.
        record = {"status": status, "answer_cache_id": answer_cache_id, "response_source": response_source,
                  "input_tokens": usage.get("input_tokens"),
                  "output_tokens": usage.get("output_tokens"),
                  "vision_input_tokens": vision_usage.get("input_tokens"),
                  "vision_output_tokens": vision_usage.get("output_tokens")}
        try:
            await asyncio.to_thread(lambda: supabase.table("ai_chat_requests").update(record).eq("id", request_id).execute())
        except Exception:
            # Keep the original reservation so an accounting failure cannot reopen quota.
            print(f"Usage reconciliation needed for request {request_id}")

    try:
        cache_eligible = eligible_question(data.question, data.history, data.image_url, reservation["turns_used"])
        data.history = bounded_history(data.history)
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
            image_bytes, image_mime = await asyncio.to_thread(
                download_chat_image, data.image_url, os.getenv("SUPABASE_URL", "")
            )

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
                vision_usage.update(vision_response.usage_metadata or {})
                print(f"[Vision] Gemini description: {extracted_text[:200]}...")
            else:
                extracted_text = ocr_text
                print(f"[OCR] Extracted {len(ocr_text.split())} words from image.")

            search_query = f"{search_query} {extracted_text}"

        if extracted_text is not None:
            extracted_text = clip_text(extracted_text, 6000)
        context = await asyncio.to_thread(
            get_context, clip_text(search_query, 8000), data.subject, data.grade_level
        )
        context = clip_text(context, 12000)
        cache_identity = answer_cache.identity(clean_question, data.subject, data.grade_level, context) if cache_eligible else None
        cached = await asyncio.to_thread(answer_cache.lookup, cache_identity) if cache_identity else None
        if cached:
            response_source = "cache"
            answer_cache_id = cached["id"]
            usage.update(input_tokens=0, output_tokens=0)
            vision_usage.update(input_tokens=0, output_tokens=0)
            await save_usage("cached")

            async def cached_response():
                yield cached["answer"]

            return StreamingResponse(cached_response(), media_type="text/plain", headers={
                "X-Answer-Source": "cache", "X-Answer-Id": str(answer_cache_id),
                "X-Chat-Turns-Used": str(reservation["turns_used"]),
            })

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
{build_tutor_prompt(context, data.grade_level, data.subject)}

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
            system_prompt = build_tutor_prompt(context, data.grade_level, data.subject)
            # Inject history into the prompt stream
            messages = [SystemMessage(content=system_prompt)] + formatted_history + [HumanMessage(content=clean_question)]

        messages[0].content += "\nKeep the answer concise, usually under 200 words. Finish the explanation within the reply limit."

        # Define the streaming generator
        async def response_generator():
            status = "interrupted"
            answer_parts = []
            finish_reason = None
            try:
                async for chunk in deepseek_llm.bind(max_tokens=MAX_REPLY_TOKENS).astream(messages):
                    finish_reason = (getattr(chunk, "response_metadata", None) or {}).get("finish_reason") or finish_reason
                    if chunk.usage_metadata:
                        for key in ("input_tokens", "output_tokens"):
                            usage[key] = usage.get(key, 0) + chunk.usage_metadata.get(key, 0)
                    if chunk.content:
                        answer_parts.append(chunk.content)
                        yield chunk.content
                status = "complete" if usage else "usage_missing"
                # Never collect a truncated, failed, or context-dependent reply for sharing.
                if cache_identity and finish_reason == "stop":
                    await asyncio.to_thread(answer_cache.save_candidate, cache_identity, "".join(answer_parts))
            except Exception:
                status = "failed"
                yield "\n\n[The reply could not be completed. Please try again.]"
            finally:
                await asyncio.shield(save_usage(status))

        return StreamingResponse(response_generator(), media_type="text/plain",
                                 headers={"X-Answer-Source": "ai", "X-Chat-Turns-Used": str(reservation["turns_used"])})

    except BaseException as error:
        await asyncio.shield(save_usage("failed"))
        if isinstance(error, (HTTPException, asyncio.CancelledError)):
            raise
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Unable to prepare the tutor reply")

# ==========================================
# 5. QUIZ ROUTE
# ==========================================

@app.post("/generate-quiz")
async def generate_quiz(data: QuizRequest, user_id: str = Depends(get_current_user)):
    reservation_date = None
    try:
        # Reserve a slot under a database row lock so parallel requests cannot bypass the cap.
        reservation_date = await asyncio.to_thread(
            lambda: supabase.rpc("reserve_daily_quiz", {"target_user_id": user_id}).execute().data
        )
        if not reservation_date:
            raise HTTPException(
                status_code=403,
                detail="Daily quiz limit reached"
            )

        search_query = f"{data.subject} Units: {', '.join(data.units)}"
        if data.section != "All Sections":
            search_query += f" Section: {data.section}"

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
                AKKA_QUIZ_PROMPT
            ),
            (
                "human",
                "Generate {num_questions} MCQs based on syllabus."
            )
        ])

        chain = (
            quiz_prompt
            | deepseek_llm.with_structured_output(QuizResponse)
        )

        quiz_data = await chain.ainvoke({
            "num_questions": data.num_questions,
            "grade_level": data.grade_level,
            "subject": data.subject,
            "context": context
        })

        if len(quiz_data.questions) != data.num_questions or any(
            q.correct_answer not in q.options for q in quiz_data.questions
        ):
            raise HTTPException(status_code=502, detail="Could not generate a valid quiz. Please try again")

        # Keep the existing app's separate option fields during staged client rollout.
        return {"questions": [
            {**q.model_dump(), **dict(zip(
                ("option_a", "option_b", "option_c", "option_d"), q.options
            ))}
            for q in quiz_data.questions
        ]}

    except BaseException as e:
        if reservation_date:
            try:
                await asyncio.to_thread(lambda: supabase.rpc("release_daily_quiz", {
                    "target_user_id": user_id, "usage_date": reservation_date
                }).execute())
            except Exception:
                print("Failed to release quiz reservation")
        if isinstance(e, (HTTPException, asyncio.CancelledError)):
            raise
        if not isinstance(e, Exception):
            raise
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Could not generate quiz. Please try again")

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
        # Check subscription details for free tier limit checks
        profile_res = supabase.table("profiles").select("subscription_tier").eq("id", teacher_id).execute()
        if not profile_res.data:
            raise HTTPException(status_code=404, detail="Teacher profile not found")
        
        user_tier = str(profile_res.data[0].get("subscription_tier", "free")).strip().lower()
        if user_tier != "admin":
            from datetime import datetime, timedelta
            ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
            
            if user_tier == "free":
                # Count quizzes created by this teacher in the current calendar month (IST)
                first_day = ist_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                first_day_iso = first_day.strftime('%Y-%m-%dT%H:%M:%S+05:30')
                
                existing = supabase.table('quiz_sessions')\
                    .select('id', count='exact')\
                    .eq('teacher_id', teacher_id)\
                    .gte('created_at', first_day_iso)\
                    .execute()
                
                created_count = existing.count or 0
                if created_count >= 1:
                    raise HTTPException(
                        status_code=403,
                        detail="Unpaid users can only host 1 live quiz per month. Upgrade to Pro for unlimited hosting!"
                    )
            elif user_tier in ["tier_199", "tier_499"]:
                # Count quizzes created by this teacher today in IST
                limit = 3 if user_tier == "tier_199" else 5
                start_of_today = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
                start_of_today_iso = start_of_today.strftime('%Y-%m-%dT%H:%M:%S+05:30')
                
                existing = supabase.table('quiz_sessions')\
                    .select('id', count='exact')\
                    .eq('teacher_id', teacher_id)\
                    .gte('created_at', start_of_today_iso)\
                    .execute()
                
                created_count = existing.count or 0
                if created_count >= limit:
                    raise HTTPException(
                        status_code=403,
                        detail=f"As a {user_tier.replace('_', ' ').title()} user, you can only host {limit} live quizzes per day. Upgrade plan to increase limits!"
                    )

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

        # Check student participation limit
        if not is_teacher:
            profile_res = supabase.table("profiles").select("subscription_tier").eq("id", user_id).execute()
            if not profile_res.data:
                raise HTTPException(status_code=404, detail="Student profile not found")
            
            user_tier = str(profile_res.data[0].get("subscription_tier", "free")).strip().lower()
            if user_tier != 'admin':
                from datetime import datetime, timedelta
                ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                
                if user_tier == "free":
                    first_day = ist_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    first_day_iso = first_day.strftime('%Y-%m-%dT%H:%M:%S+05:30')
                    
                    # Fetch all responses by this student this month
                    existing_responses = supabase.table('quiz_responses')\
                        .select('session_id')\
                        .eq('student_id', user_id)\
                        .gte('created_at', first_day_iso)\
                        .execute()
                    
                    # Get unique session IDs
                    unique_session_ids = {r['session_id'] for r in existing_responses.data} if existing_responses.data else set()
                    
                    # If they haven't joined this session yet and have already used their 3 free slots
                    if s['id'] not in unique_session_ids and len(unique_session_ids) >= 3:
                        raise HTTPException(
                            status_code=403,
                            detail="Unpaid users can only participate in 3 live quizzes per month. Upgrade to Pro for unlimited access!"
                        )
                elif user_tier in ["tier_199", "tier_499"]:
                    # Paid users: daily unique session limits
                    limit = 10 if user_tier == "tier_199" else 15
                    start_of_today = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
                    start_of_today_iso = start_of_today.strftime('%Y-%m-%dT%H:%M:%S+05:30')
                    
                    # Fetch all responses by this student today
                    existing_responses = supabase.table('quiz_responses')\
                        .select('session_id')\
                        .eq('student_id', user_id)\
                        .gte('created_at', start_of_today_iso)\
                        .execute()
                    
                    unique_session_ids = {r['session_id'] for r in existing_responses.data} if existing_responses.data else set()
                    
                    if s['id'] not in unique_session_ids and len(unique_session_ids) >= limit:
                        raise HTTPException(
                            status_code=403,
                            detail=f"As a {user_tier.replace('_', ' ').title()} user, you can only participate in {limit} unique live quizzes per day. Upgrade plan to increase limits!"
                        )

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

        question = supabase.table('quiz_questions').select('correct_answer,question_type,sort_order').eq('id', data.question_id).eq('session_id', s['id']).execute()
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
