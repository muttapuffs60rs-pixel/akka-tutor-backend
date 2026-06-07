import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

query = "Explain Section 4.11"
vector = embeddings.embed_query(query)

rpc = supabase.rpc("hybrid_match_documents", {
    "query_embedding": vector,
    "query_text": query,
    "match_threshold": 0.2, 
    "match_count": 3,
    "filter_grade": "10",
    "filter_subject": "Science"
}).execute()

print(f"Results for '{query}': {len(rpc.data)}")
for i, r in enumerate(rpc.data):
    metadata_header = f"[{r.get('unit_name', '')} -> {r.get('section_name', '')} -> {r.get('sub_section_name', '')}]\n"
    print(f"\n--- MATCH {i+1} ---")
    print(metadata_header)
    print(r.get("content")[:200] + "...")
