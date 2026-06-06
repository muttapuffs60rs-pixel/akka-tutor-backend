import os, io, asyncio, traceback, requests, uvicorn, easyocr
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
        vector = embeddings.embed_query(query)

        # FIXED: Cast grade safely to string to defend against internal RPC parsing failures
        rpc = supabase.rpc("hybrid_match_documents", {
            "query_embedding": vector,
            "query_text": query,
            "match_threshold": threshold,
            "match_count": count,
            "filter_grade": str(grade),
            "filter_subject": str(subject)
        }).execute()

        return "\n---\n".join(
            r["content"] for r in rpc.data
        ) if rpc.data else "No specific textbook context found."
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
        # 1. Fetch user profile attributes safely (Using subscription_tier to match Supabase)
        profile_res = supabase.table("profiles").select("chats_today, subscription_tier").eq("id", data.user_id).execute()
        if not profile_res.data:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        user_profile = profile_res.data[0]
        
        raw_chats = user_profile.get("chats_today")
        chats_today = int(raw_chats) if raw_chats is not None else 0
        
        # Pull from the correct dictionary key name matching the select query
        raw_tier = user_profile.get("subscription_tier")
        user_tier = str(raw_tier).strip().lower() if raw_tier is not None else "free"

        # FIXED: Enforce accurate subscription package ceilings and custom messaging
        max_allowed_chats = 5  # Default Free Tier
        limit_message = "Daily limit reached. Upgrade to Pro!"
        
        if user_tier == "tier_199":
            max_allowed_chats = 50
            limit_message = "Your limit per day is over. Upgrade your plan to get more daily questions!"
        elif user_tier == "tier_499":
            max_allowed_chats = 150
            limit_message = "Your limit per day is over. Upgrade your plan to get more daily questions!"
        elif user_tier in ["tier_49", "admin"]:
            max_allowed_chats = 999999  # Unlimited day usage

        # Enforce subscription cap barriers dynamically
        if user_tier not in ["admin", "tier_49"] and chats_today >= max_allowed_chats:
            return {
                "answer": limit_message,
                "show_paywall": True
            }

        # Handle empty/blank queries smoothly
        clean_question = data.question.strip() if data.question else ""
        
        context = get_context(
            clean_question if clean_question else "textbook page",
            data.subject,
            data.grade_level
        )

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
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)]

        # ==================================
        # NORMAL TEXT FLOW
        # ==================================
        else:
            system_prompt = AKKA_TUTOR_SYSTEM_PROMPT.format(context=context)
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=clean_question)]

        # Call LLM Engine with absolute type safety
        response = deepseek_llm.invoke(messages)
        ai_response_text = response.content if response and response.content else "No response generated."

        # Database Counter Increment Execution
        update_profile(
            data.user_id,
            "chats_today", 
            chats_today + 1
        )

        return {
            "answer": ai_response_text,
            "show_paywall": False
        }

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

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000))
    )