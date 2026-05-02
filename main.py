import os
import traceback
from datetime import date
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

from supabase import create_client, Client
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek # Updated for native DeepSeek
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
import uvicorn

# Ensure your local prompts.py is updated to say "Tutor Preethi"
from prompts import AKKA_TUTOR_SYSTEM_PROMPT

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
# Only requiring the DeepSeek key now
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

# CLEAN DEEPSEEK INTEGRATION (Replaced ChatOpenAI hack)
llm = ChatDeepSeek(
    model="deepseek-chat", 
    api_key=DEEPSEEK_API_KEY,
    temperature=0.3,
    max_retries=3  # Increased retries since we removed fallbacks
)

# FALLBACK LOGIC: Primary is DeepSeek. If 429 error or down, use Gemini, then GPT.
llm = deepseek_llm.with_fallbacks([gemini_llm, openai_llm])

app = FastAPI(title="Tutor Preethi AI - Standard 10 Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# --- DATA MODELS ---
class ChatRequest(BaseModel):
    user_id: str           
    question: str
    grade_level: int
    subject: str
    is_first_message: bool = False
    history: List[str] = [] 
    image_data: Optional[str] = None 

class QuizQuestion(BaseModel):
    question: str; option_a: str; option_b: str; option_c: str; option_d: str; correct_answer: str; explanation: str

class QuizResponse(BaseModel):
    questions: List[QuizQuestion]

class QuizRequest(BaseModel):
    user_id: str; grade_level: int; subject: str; units: List[str]; section: str = "All Sections"; num_questions: int

class ProfileUpdate(BaseModel):
    user_id: str; full_name: str; grade_level: int

# ==========================================
# 4. CHAT API
# ==========================================

@app.post("/ask")
async def ask_tutor(data: ChatRequest):
    try:
        profile_res = supabase.table('profiles').select('*').eq('id', data.user_id).execute()
        today_str = date.today().isoformat()
        
        if not profile_res.data:
            profile = {"id": data.user_id, "subscription_tier": "free", "questions_today": 0, "last_active_date": today_str}
            supabase.table('profiles').insert(profile).execute()
        else:
            profile = profile_res.data[0]

        if profile.get('last_active_date') != today_str:
            supabase.table('profiles').update({'questions_today': 0, 'last_active_date': today_str}).eq('id', data.user_id).execute()
            profile['questions_today'] = 0

        questions_asked = profile.get('questions_today', 0)
        tier = profile.get('subscription_tier', 'free')
        
        # PRICING LIMITS
        max_q = {'free': 5, 'tier_49': 9999, 'tier_199': 50, 'tier_499': 150, 'admin': 999999}.get(tier, 5)
        
        if questions_asked >= max_q:
            return {
                "answer": "Today's limit reached! Upgrade your plan to keep learning with Tutor Preethi. 🚀",
                "show_paywall": True
            }

        user_grade = data.grade_level if data.grade_level != 0 else 10
        query_vector = embeddings.embed_query(data.question)
        
        rpc_res = supabase.rpc("hybrid_match_documents", {
            "query_embedding": query_vector,
            "query_text": data.question,       
            "match_threshold": 0.3,               
            "match_count": 4,
            "filter_grade": user_grade, 
            "filter_subject": data.subject    
        }).execute()
        
        context = "\n---\n".join([res['content'] for res in rpc_res.data]) or "No context."

        formatted_history = []
        for msg in data.history:
            role = "human" if "You:" in msg else "ai"
            formatted_history.append((role, msg.replace("You:", "").replace("Preethi:", "").strip()))

        system_text = AKKA_TUTOR_SYSTEM_PROMPT.format(
            grade_level=user_grade,
            subject=data.subject,
            greeting_rule="Warm greeting" if data.is_first_message else "Direct answer",
            context=context,
            user_name=profile.get('full_name', 'Student') 
        )

        user_msg = HumanMessage(content=data.question + "\n\nExplain in Tanglish.")
        ai_res = llm.invoke([SystemMessage(content=system_text), *formatted_history, user_msg])
        
        supabase.table('profiles').update({'questions_today': questions_asked + 1}).eq('id', data.user_id).execute()
        
        return {"answer": ai_res.content}

    except Exception as e:
        traceback.print_exc()
        return {"answer": "Oops! Tutor Preethi has a technical issue. Try again later! 💜"}

@app.get("/check-onboarding/{user_id}")
async def check_onboarding(user_id: str):
    try:
        response = supabase.table('profiles').select('onboarding_complete').eq('id', user_id).execute()
        return {"onboarding_complete": bool(response.data and response.data[0].get('onboarding_complete'))}
    except: return {"onboarding_complete": False}

@app.post("/complete-onboarding")
async def complete_onboarding(data: ProfileUpdate):
    try:
        today_str = date.today().isoformat()
        profile_data = {"id": data.user_id, "full_name": data.full_name, "grade_level": data.grade_level, "onboarding_complete": True, "last_active_date": today_str, "subscription_tier": "free", "questions_today": 0, "quizzes_today": 0}
        supabase.table('profiles').upsert(profile_data).execute()
        return {"status": "success"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-quiz")
async def generate_quiz(data: QuizRequest):
    try:
        profile_res = supabase.table("profiles").select("*").eq("id", data.user_id).execute()
        quizzes_today = profile_res.data[0].get('quizzes_today', 0)
        if quizzes_today >= 5: raise HTTPException(status_code=403)
        
        search_query = f"{data.subject} Units: {', '.join(data.units)}"
        query_vector = embeddings.embed_query(search_query)
        
        rpc_res = supabase.rpc("hybrid_match_documents", {
            "query_embedding": query_vector, 
            "query_text": search_query, 
            "match_threshold": 0.3, 
            "match_count": 8, 
            "filter_grade": data.grade_level, 
            "filter_subject": data.subject
        }).execute()
        
        context = "\n---\n".join([res['content'] for res in rpc_res.data])
        quiz_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Tutor Preethi. Use this Context: {context}"), 
            ("human", "Generate {num} MCQs based on the syllabus.")
        ])
        
        # Using structured output for Quiz generation
        chain = quiz_prompt | deepseek_llm.with_structured_output(QuizResponse)
        quiz_data = chain.invoke({"num": data.num_questions, "context": context})
        
        supabase.table("profiles").update({"quizzes_today": quizzes_today + 1}).eq("id", data.user_id).execute()
        return quiz_data.model_dump()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)