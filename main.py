import os
import traceback
from datetime import date
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

from supabase import create_client, Client
from langchain_deepseek import ChatDeepSeek 
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
import uvicorn

# Placeholder to keep the app from crashing without the prompts file
try:
    from prompts import AKKA_TUTOR_SYSTEM_PROMPT
except ImportError:
    AKKA_TUTOR_SYSTEM_PROMPT = "You are Tutor Preethi. Context: {context}"

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- LIGHTWEIGHT BYPASS ---
# We comment this out to stay under 512MB for the first deploy
# embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
embeddings = None 

# NATIVE DEEPSEEK ONLY
llm = ChatDeepSeek(
    model="deepseek-chat", 
    api_key=DEEPSEEK_API_KEY,
    temperature=0.3,
    max_retries=3
)

app = FastAPI(title="Tutor Preethi AI - Lightweight Boot")

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

# (Quiz and Profile models remain to keep structure intact)
class QuizQuestion(BaseModel):
    question: str; option_a: str; option_b: str; option_c: str; option_d: str; correct_answer: str; explanation: str
class QuizResponse(BaseModel):
    questions: List[QuizQuestion]
class QuizRequest(BaseModel):
    user_id: str; grade_level: int; subject: str; units: List[str]; section: str = "All Sections"; num_questions: int
class ProfileUpdate(BaseModel):
    user_id: str; full_name: str; grade_level: int

# ==========================================
# 4. CHAT API (STUBBED FOR BOOT)
# ==========================================

@app.post("/ask")
async def ask_tutor(data: ChatRequest):
    return {"answer": "Tutor Preethi is upgrading her brain! Reverting to full mode soon. 💜"}

@app.get("/check-onboarding/{user_id}")
async def check_onboarding(user_id: str):
    return {"onboarding_complete": True}

@app.post("/complete-onboarding")
async def complete_onboarding(data: ProfileUpdate):
    return {"status": "success"}

@app.post("/generate-quiz")
async def generate_quiz(data: QuizRequest):
    return {"questions": []}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)