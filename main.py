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
    vector = embeddings.embed_query(query)

    rpc = supabase.rpc("hybrid_match_documents", {
        "query_embedding": vector,
        "query_text": query,
        "match_threshold": threshold,
        "match_count": count,
        "filter_grade": str(grade),
        "filter_subject": subject
    }).execute()

    return "\n---\n".join(
        r["content"] for r in rpc.data
    ) if rpc.data else "No specific textbook context found."

def get_profile(user_id: str, field: str):
    res = supabase.table("profiles").select(field).eq("id", user_id).execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")

    raw_val = res.data[0].get(field)
    return raw_val if raw_val is not None else 0

def update_profile(user_id: str, field: str, value: int):
    supabase.table("profiles").update({
        field: value
    }).eq("id", user_id).execute()

# ==========================================
# 4. CHAT ROUTE
# ==========================================

@app.post("/ask")
async def chat_handler(data: ChatRequest):
    try:
        # 1. FIXED: Fetch user profile attributes safely
        profile_res = supabase.table("profiles").select("chats_today, tier").eq("id", data.user_id).execute()
        if not profile_res.data:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        user_profile = profile_res.data[0]
        
        # FIXED: Defend against NULL database cell states by falling back safely to 0
        raw_chats = user_profile.get("chats_today")
        chats_today = raw_chats if raw_chats is not None else 0
        
        # FIXED: Safely scrub string formatting variables and capture NULL tiers as free
        raw_tier = user_profile.get("tier")
        user_tier = str(raw_tier).strip().lower() if raw_tier is not None else "free"

        # 2. FIXED: Skip check entirely if user is Admin
        if user_tier != "admin" and chats_today >= 20:
            return {
                "answer": "Daily limit reached. Upgrade to Pro!",
                "show_paywall": True
            }

        context = get_context(
            data.question if data.question.strip() else "textbook page",
            data.subject,
            data.grade_level
        )

        # 3. FIXED: Reconstruct message history for DeepSeek continuity
        formatted_history = []
        for msg in data.history:
            if msg.get("role") == "user":
                formatted_history.append(HumanMessage(content=msg.get("content", "")))
            elif msg.get("role") == "assistant":
                formatted_history.append(AIMessage(content=msg.get("content", "")))

        # ==================================
        # IMAGE OCR FLOW
        # ==================================
        if data.image_url:
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
{data.question if data.question.strip() else "Explain the concepts shown in this textbook image section."}

INSTRUCTIONS:
- Explain clearly in Tanglish
- Use TN State Board style
- Give point-wise answers
- Keep it easy for students
"""
            user_msg = data.question if data.question.strip() else "Explain this image contents."

            # Append context instruction system prompt first, then historical turns, then the latest user query
            messages = [SystemMessage(content=system_prompt)] + formatted_history + [HumanMessage(content=user_msg)]

        # ==================================
        # NORMAL TEXT FLOW
        # ==================================
        else:
            system_prompt = AKKA_TUTOR_SYSTEM_PROMPT.format(context=context)
            messages = [SystemMessage(content=system_prompt)] + formatted_history + [HumanMessage(content=data.question)]

        response = deepseek_llm.invoke(messages)

        update_profile(
            data.user_id,
            "chats_today", 
            chats_today + 1
        )

        return {
            "answer": response.content,
            "show_paywall": False
        }

    except Exception as e:
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