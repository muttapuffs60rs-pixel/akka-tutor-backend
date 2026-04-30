import os
import requests
import uuid # Successfully imported
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from langchain_text_splitters import HTMLHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from supabase import create_client, Client

# --- 1. Setup & Environment ---
load_dotenv()
url: str = os.getenv("SUPABASE_URL") 
key: str = os.getenv("SUPABASE_KEY") 
supabase: Client = create_client(url, key)

model_name = "paraphrase-multilingual-MiniLM-L12-v2" 
embeddings = HuggingFaceEmbeddings(model_name=model_name)

# --- 2. The Master Catalog ---
textbook_catalog = [
    {
        "url": "https://d1wpyxz35bzzz4.cloudfront.net/tnschools/10-Tamil-TM/10-Tamil-TM.html",
        "grade_level": 10,
        "subject": "Tamil"
    },
    {
        "url": "https://d1wpyxz35bzzz4.cloudfront.net/tnschools/10-eng-n/10-eng-n.html",
        "grade_level": 10,
        "subject": "English"
    },
    {
        "url": "https://d1wpyxz35bzzz4.cloudfront.net/tnschools/10-Science-EM/10-Science-EM.html",
        "grade_level": 10,
        "subject": "Science"
    },
    {
        "url": "https://d1wpyxz35bzzz4.cloudfront.net/tnschools/10-SOCIALSCIENCE-EM/10-SOCIALSCIENCE-EM.html",
        "grade_level": 10,
        "subject": "Social"
    },
    {
        "url": "https://d1wpyxz35bzzz4.cloudfront.net/tnschools/10-MATHS-EM/10-MATHS-EM.html",
        "grade_level": 10,
        "subject": "Maths"
    }
]

# Step 1: Split by HTML Headers (The Structure)
headers_to_split_on = [
    ("h1", "unit_name"),
    ("h2", "section_name"),
    ("h3", "sub_section_name"), # <-- This will perfectly catch the <h3> you just found!
    ("h4", "sub_sub_section_name"),
]
html_splitter = HTMLHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

# Step 2: Split by Character Count (The Granularity stays at 800!)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800, 
    chunk_overlap=100,
    separators=["\n\n", "\n", ".", " ", ""]
)

# --- 3. The Cleaning & Ingestion Loop ---
for book in textbook_catalog:
    print(f"\n--- Processing {book['grade_level']}th {book['subject']} ---")
    
    response = requests.get(book['url'])
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 👇 This should be indented exactly 4 spaces (in line with the 'print' above)
    for element in soup(["script", "style", "meta", "link", "noscript", "footer", "nav"]):
        element.decompose()
        
    # ==========================================
    # NEW MAGIC FIX: Flatten the Headers!
    # ==========================================
    for header in soup(["h1", "h2", "h3", "h4", "h5", "h6"]):
        clean_text = header.get_text(separator=" ", strip=True)
        new_header = soup.new_tag(header.name)
        new_header.string = clean_text
        header.replace_with(new_header)
        
    cleaned_html = str(soup)
    
    # Hierarchical Split
    html_header_splits = html_splitter.split_text(cleaned_html)
    
    final_documents = []

    # Secondary Splitting Loop
    for header_chunk in html_header_splits:
        sub_chunks = text_splitter.split_documents([header_chunk])
        
        for chunk in sub_chunks:
            # The html_splitter automatically added unit_name and section_name to chunk.metadata
            chunk.metadata["grade_level"] = book["grade_level"]
            chunk.metadata["subject"] = book["subject"]
            final_documents.append(chunk)

    # --- 4. Generate Embeddings & Upload to Explicit Columns ---
    # --- 4. Generate Embeddings & Upload ---
    if final_documents:
        print(f"Created {len(final_documents)} granular chunks. Generating embeddings...")
        
        # 🚨 SAFETY CHECK: Print the metadata of the very first chunk to ensure it isn't "General"!
        print(f"🕵️ DEBUG - First chunk metadata: {final_documents[10].metadata}")
        
        # Extract text strings to generate embeddings
        texts = [doc.page_content for doc in final_documents]
        embedded_vectors = embeddings.embed_documents(texts)
        
        # Prepare the exact data structure for your new SQL columns
        insert_data = []
        for i, doc in enumerate(final_documents):
            insert_data.append({
                "id": str(uuid.uuid4()), # <--- UUID generation is safely here now
                "content": doc.page_content,
                "embedding": embedded_vectors[i],
                "grade_level": doc.metadata.get("grade_level"),
                "subject": doc.metadata.get("subject"),
                "unit_name": doc.metadata.get("unit_name", "General Unit"), 
                "section_name": doc.metadata.get("section_name", "General Section") 
            })
        
        print("Uploading to Supabase...")
        
        # Bulk Insert in batches of 100 to prevent API timeouts
        batch_size = 100
        for i in range(0, len(insert_data), batch_size):
            batch = insert_data[i:i+batch_size]
            supabase.table("documents").insert(batch).execute()
            print(f"Uploaded batch {i//batch_size + 1}...")

        print(f"Successfully uploaded all chunks for {book['subject']}! ✅")
    else:
        print(f"No chunks were created for {book['subject']}. ❌")
        
print("\nAll books processed! 🚀")