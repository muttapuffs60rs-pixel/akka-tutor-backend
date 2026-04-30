import os
import time
import requests
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import HTMLHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# --- KEY GOES HERE ---
from dotenv import load_dotenv
load_dotenv()
os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY")

# --- MVP SCOPE: Only processing Science ---
SUBJECT_URLS = {
    "Science": "https://d1wpyxz35bzzz4.cloudfront.net/tnschools/10-Science-EM/10-Science-EM.html",
}

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

headers_to_split_on = [
    ("h1", "Book Title"),
    ("h2", "Unit"),
    ("h3", "Chapter"),
    ("h4", "Section"),
]
html_splitter = HTMLHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=300)

print("Starting Bulletproof ETL Pipeline...")

for subject_name, url in SUBJECT_URLS.items():
    print(f"\nProcessing {subject_name}...")
    
    web_response = requests.get(url)
    html_string = web_response.text
    
    header_splits = html_splitter.split_text(html_string)
    chunks = text_splitter.split_documents(header_splits)
    
    print(f"  -> Structurally sliced into {len(chunks)} chunks.")
    
    vector_db = None
    
# THE FIX: Enterprise Retry Logic
    batch_size = 5 
    
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i+batch_size]
        print(f"  -> Uploading batch {i//batch_size + 1} of {(len(chunks)//batch_size) + 1}...")
        
        texts = [doc.page_content for doc in batch]
        metadatas = [doc.metadata for doc in batch]
        
        # Smart loop that will not crash if Google asks us to wait
        success = False
        while not success:
            try:
                if vector_db is None:
                    vector_db = FAISS.from_texts(texts, embeddings, metadatas=metadatas)
                else:
                    vector_db.add_texts(texts, metadatas=metadatas)
                success = True # If it worked, break out of the retry loop
                
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    print("     ⚠️ Google Free Tier limit hit. Sleeping for 60 seconds and retrying this batch...")
                    time.sleep(60)
                else:
                    # If it's a different kind of error, crash and show it
                    raise e
            
        # Standard sleep between successful batches just to be safe
        if i + batch_size < len(chunks):
            time.sleep(5)
            
    vector_db.save_local(f"faiss_index_{subject_name}")
    print(f"✅ Saved faiss_index_{subject_name} to disk.")

print("\nETL Complete! Ready for deployment.")