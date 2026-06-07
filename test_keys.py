import os
from dotenv import load_dotenv
from supabase import create_client
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

vector = embeddings.embed_query("Explain Section 4.11")

rpc = supabase.rpc("hybrid_match_documents", {
    "query_embedding": vector,
    "query_text": "Explain Section 4.11",
    "match_threshold": 0.2, 
    "match_count": 3,
    "filter_grade": "10",
    "filter_subject": "Science"
}).execute()

if rpc.data:
    print("KEYS:", rpc.data[0].keys())
else:
    print("No data.")
