import os
import io
import traceback
import base64
import json
from datetime import date
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

from supabase import create_client, Client
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek 
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
import uvicorn

# Ensure your local prompts.py is updated
from prompts import AKKA_TUTOR_SYSTEM_PROMPT

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

# LLM initializations
deepseek_llm = ChatDeepSeek(model='deepseek-v4-flash', api_key=DEEPSEEK_API_KEY)
# Using Gemini 2.0 Flash specifically for Vision/Multimodal tasks
gemini_vision_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=GOOGLE_API_KEY)

app = FastAPI(title="Akka Tutor API - Snap & Learn Edition")

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
    question: str  # Matches Flutter field 'question'
    subject: str
    grade_level: int # Changed to int to match Flutter state
    image_url: Optional[str] = None # Added to support vision from Flutter
    history: Optional[List[str]] = []

class QuizRequest(BaseModel):
    user_id: str
    subject: str
    units: List[str]
    grade_level: str
    num_questions: int = 5

class QuizResponse(BaseModel):
    questions: List[dict] = Field(description="List of MCQs with question, options, and answer")

# ==========================================
# 3. UPDATED ROUTE: ASK (CHATS & VISION)
# ==========================================

@app.post("/ask")
async def chat_handler(data: ChatRequest):
    try:
        # 1. Check Usage Limits
        profile_res = supabase.table("profiles").select("chats_today").eq("id", data.user_id).execute()
        if not profile_res.data: raise HTTPException(status_code=404, detail="User not found")
        
        chats_today = profile_res.data[0].get('chats_today', 0)
        if chats_today >= 20: 
            return {"answer": "Daily limit reached. Please upgrade to Pro!", "show_paywall": True}

        # 2. RAG Logic (Only if no image, or to give context to image)
        query_vector = embeddings.embed_query(data.question)
        rpc_res = supabase.rpc("hybrid_match_documents", {
            "query_embedding": query_vector,
            "query_text": data.question,
            "match_threshold": 0.2,
            "match_count": 3,
            "filter_grade": str(data.grade_level),
            "filter_subject": data.subject
        }).execute()

        context = "\n---\n".join([res['content'] for res in rpc_res.data]) if rpc_res.data else "No specific textbook context found."

        # 3. Decision: DeepSeek (Text) vs Gemini (Vision)
        if data.image_url:
            # MULTIMODAL LOGIC (Gemini 2.0 Flash)
            # Formatting prompt specifically for tutoring context
            vision_prompt = f"""
            SYSTEM: {AKKA_TUTOR_SYSTEM_PROMPT.format(context=context)}
            USER QUESTION: {data.question}
            INSTRUCTIONS: Analyze the image provided. Explain the concept or solve the problem shown.
            Answer in Tanglish. Use point-wise format suitable for TN Public Exams.
            """
            message = HumanMessage(content=[
                {"type": "text", "text": vision_prompt},
                {
                    "type": "image_url", 
                    "image_url": {
                        "url": data.image_url,
                        "detail": "high"  # <--- Rule 3: High Detail added here
                    }
                }
            ])
            response = gemini_vision_llm.invoke([message])
        else:
            # TEXT-ONLY LOGIC (DeepSeek)
            messages = [
                SystemMessage(content=AKKA_TUTOR_SYSTEM_PROMPT.format(context=context)),
                HumanMessage(content=data.question)
            ]
            response = deepseek_llm.invoke(messages)

        # 4. Update limits & profile
        supabase.table("profiles").update({"chats_today": chats_today + 1}).eq("id", data.user_id).execute()

        return {"answer": response.content, "show_paywall": False}

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 4. ROUTE: QUIZ GENERATION
# ==========================================

@app.post("/generate-quiz")
async def generate_quiz(data: QuizRequest):
    try:
        profile_res = supabase.table("profiles").select("quizzes_today").eq("id", data.user_id).execute()
        quizzes_today = profile_res.data[0].get('quizzes_today', 0)
        if quizzes_today >= 5: raise HTTPException(status_code=403, detail="Quiz limit reached")
        
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
        
        context = "\n---\n".join([res['content'] for res in rpc_res.data]) if rpc_res.data else "General Syllabus context"
        
        quiz_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Tutor Akka. Use this Context: {context}. Generate high-quality MCQs for the Samacheer Kalvi exam."), 
            ("human", "Generate {num} MCQs based on the syllabus.")
        ])
        
        chain = quiz_prompt | deepseek_llm.with_structured_output(QuizResponse)
        quiz_data = chain.invoke({"num": data.num_questions, "context": context})
        
        supabase.table("profiles").update({"quizzes_today": quizzes_today + 1}).eq("id", data.user_id).execute()
        
        return quiz_data
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)