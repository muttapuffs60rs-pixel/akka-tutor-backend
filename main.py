import os, io, asyncio, traceback, requests, uvicorn, easyocr
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
from langchain_deepseek import ChatDeepSeek
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from prompts import AKKA_TUTOR_SYSTEM_PROMPT, AKKA_QUIZ_PROMPT

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

ocr_reader = easyocr.Reader(['en'], gpu=False)

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
    user_id: str
    question: str
    subject: str
    grade_level: int
    image_url: Optional[str] = None
    history: List[dict] = []  # FIXED: Added history back so the backend accepts Flutter's memory payload

class QuizRequest(BaseModel):
    user_id: str
    subject: str
    units: List[str]
    grade_level: int
    num_questions: int = 5

class QuizResponse(BaseModel):
    questions: List[dict] = Field(
        description="List of MCQs with question, options, and answer"
    )

# ==========================================
# 3. HELPERS
# ==========================================

def get_context(query: str, subject: str, grade: int,
                threshold=0.2, count=3):
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
async def chat_handler(data: ChatRequest):
    try:
        # Fetch user profile attributes safely
        profile_res = supabase.table("profiles").select("chats_today, subscription_tier, previous_tier, last_active_date").eq("id", data.user_id).execute()
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
            
            # Force the update in DB so we are in sync
            supabase.table("profiles").update({
                "chats_today": chats_today,
                "subscription_tier": user_tier,
                "previous_tier": prev_tier,
                "last_active_date": today_str
            }).eq("id", data.user_id).execute()

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

        # Handle empty/blank queries smoothly
        clean_question = data.question.strip() if data.question else ""
        
        # --- NEW: CONTEXT-AWARE DATABASE SEARCH ---
        search_query = clean_question
        
        # If it's a short follow up, attach the previous question to the search vector
        if data.history and len(clean_question.split()) < 10:
            last_user_question = ""
            for msg in reversed(data.history):
                if msg.get("role") == "user":
                    last_user_question = msg.get("content", "")
                    break
            
            if last_user_question:
                search_query = f"{last_user_question} {clean_question}"
        
        # Pass the enriched search query to the database
        context = get_context(
            search_query if search_query else "textbook page",
            data.subject,
            data.grade_level
        )

        # Process history array into proper LangChain message objects for continuity
        formatted_history = []
        for msg in data.history:
            if msg.get("role") == "user":
                formatted_history.append(HumanMessage(content=msg.get("content", "")))
            elif msg.get("role") == "assistant":
                formatted_history.append(AIMessage(content=msg.get("content", "")))

        # ==================================
        # IMAGE OCR FLOW
        # ==================================
        if data.image_url and data.image_url.strip():
            await asyncio.sleep(1)
            image = requests.get(data.image_url, timeout=15)

            extracted = ocr_reader.readtext(
                image.content,
                detail=0,
                paragraph=True
            )

            extracted_text = " ".join(extracted) if extracted else "No readable text found."

            system_prompt = f"""
SYSTEM:
{AKKA_TUTOR_SYSTEM_PROMPT.format(context=context)}

TEXTBOOK IMAGE TEXT:
\"\"\"{extracted_text}\"\"\"

STUDENT QUESTION:
{clean_question if clean_question else "Explain the concepts shown in this textbook image section."}

INSTRUCTIONS:
- Explain clearly in Tanglish
- Use TN State Board style
- Give point-wise answers
- Keep it easy for students
"""
            user_msg = clean_question if clean_question else "Explain this image contents."
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
                for chunk in deepseek_llm.stream(messages):
                    if chunk.content:
                        yield chunk.content
                
                # Database Counter Increment Execution (happens after successful stream finishes)
                update_profile(
                    data.user_id,
                    "chats_today", 
                    chats_today + 1
                )
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
async def generate_quiz(data: QuizRequest):
    try:
        quizzes_today = get_profile(data.user_id, "quizzes_today")

        if quizzes_today >= 5:
            raise HTTPException(
                status_code=403,
                detail="Daily quiz limit reached"
            )

        search_query = f"{data.subject} Units: {', '.join(data.units)}"

        context = get_context(
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

        quiz_data = chain.invoke({
            "num": data.num_questions,
            "context": context
        })

        update_profile(
            data.user_id,
            "quizzes_today",
            quizzes_today + 1
        )

        return quiz_data

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 6. SERVER
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