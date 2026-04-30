import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

# --- 1. DUMMY SERVER (FIXED FOR RENDER HEALTH CHECKS) ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    
    def do_HEAD(self): 
        self.send_response(200)
        self.end_headers()

def keep_alive():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

threading.Thread(target=keep_alive, daemon=True).start()
print("--> SUCCESS: Dummy door opened for Render instantly!")

# --- 2. LIGHTWEIGHT IMPORTS ---
print("--> Loading Libraries...")
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY") 

print("--> Connecting to Google Cloud...")
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)

# --- FIX: Matching the exact model used in build_brain.py ---
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

vector_databases = {}

# --- FIX: Limiting to Science for the MVP test ---
SUBJECTS = ["Science"]

print("--> Loading Lightweight Brains from disk...")
for subject in SUBJECTS:
    try:
        vector_databases[subject] = FAISS.load_local(
            folder_path=f"faiss_index_{subject}", 
            embeddings=embeddings, 
            allow_dangerous_deserialization=True
        )
        print(f"    Loaded {subject} successfully.")
    except Exception as e:
        print(f"    ERROR loading {subject}: {e}")

print("--> All databases loaded instantly!")

# --- 3. TELEGRAM BOT LOGIC ---
active_subjects = {}

# --- FIX: The Tanglish Personality Prompt ---
system_prompt = (
    "You are a friendly, expert TN State Board Tutor for 10th Standard. "
    "Use the following pieces of retrieved context to answer the student's question. "
    "CRITICAL INSTRUCTION: You must explain the concepts in 'Tanglish' (Tamil mixed with English, typed in English alphabets). "
    "Keep technical science and math terms in English, but use conversational Tanglish to explain how they work. "
    "Use encouraging phrases like 'Idhu romba simple, kavaniga!', 'Puriyudha?', or 'Super question!'. "
    "If the answer is not in the context, say 'Ennaku exact answer textbook-la kidaikala.' "
    "Keep the answer concise and engaging.\n\n"
    "Context: {context}"
)

prompt_template = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}"),
])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_subjects: del active_subjects[chat_id]
    
    keyboard = [[subject] for subject in SUBJECTS]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        "Vanakkam! I am your All-in-One 10th Standard AI Tutor.\n\nWhich subject would you like to study today?",
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    if user_text in SUBJECTS:
        active_subjects[chat_id] = user_text
        await update.message.reply_text(
            f"Excellent choice! I have loaded the {user_text} syllabus.\n\n💡 Tip: Use the Menu button to change subjects! \n\nWhat is your question?",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return

    if chat_id not in active_subjects:
        await update.message.reply_text("Please select a subject from the Menu first!")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action='typing')
    current_subject = active_subjects[chat_id]

    try:
        retriever = vector_databases[current_subject].as_retriever(search_kwargs={"k": 4})
        question_answer_chain = create_stuff_documents_chain(llm, prompt_template)
        rag_chain = create_retrieval_chain(retriever, question_answer_chain)
        
        response = rag_chain.invoke({"input": user_text})
        await update.message.reply_text(response["answer"])
        
    except Exception as e:
        await update.message.reply_text("Sorry, I encountered an error while thinking.")
        print(f"\nGeneration Error: {e}")

def main():
    print("--> Starting Telegram Bot...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("--> BOT IS LIVE! Send /start on Telegram.")
    app.run_polling(poll_interval=1.0)

if __name__ == '__main__':
    main()