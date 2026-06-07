import os
import uuid
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from langchain_text_splitters import HTMLHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from supabase import create_client, Client

# --- 1. Setup & Environment ---
load_dotenv()
url: str = os.getenv("SUPABASE_URL") 
key: str = os.getenv("SUPABASE_KEY") 

if not url or not key:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env file")

supabase: Client = create_client(url, key)

model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" 
embeddings = HuggingFaceEmbeddings(model_name=model_name)

# --- 2. EPUB Config ---
epub_file_path = "sample_textbook.epub"
book_metadata = {
    "grade_level": 10,
    "subject": "Science"
}

print(f"Loading EPUB: {epub_file_path}")
book = epub.read_epub(epub_file_path)

# Step 1: Split by HTML Headers (The Structure)
headers_to_split_on = [
    ("h1", "unit_name"),
    ("h2", "section_name"),
    ("h3", "sub_section_name"), # <-- Catching the <h3>!
    ("h4", "sub_sub_section_name"),
]
html_splitter = HTMLHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

# Step 2: Split by Character Count (The Granularity stays at 800!)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800, 
    chunk_overlap=100,
    separators=["\n\n", "\n", ".", " ", ""]
)

# --- 3. The Extraction & Cleaning Loop ---
print(f"Processing {book_metadata['grade_level']}th {book_metadata['subject']}...")

final_documents = []

for item in book.get_items():
    if item.get_type() == ebooklib.ITEM_DOCUMENT:
        html_content = item.get_body_content().decode('utf-8')
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Remove unnecessary tags
        for element in soup(["script", "style", "meta", "link", "noscript", "footer", "nav"]):
            element.decompose()
            
        # Flatten the Headers
        for header in soup(["h1", "h2", "h3", "h4", "h5", "h6"]):
            clean_text = header.get_text(separator=" ", strip=True)
            new_header = soup.new_tag(header.name)
            new_header.string = clean_text
            header.replace_with(new_header)
            
        cleaned_html = str(soup)
        
        if not cleaned_html.strip():
            continue
            
        # Hierarchical Split
        html_header_splits = html_splitter.split_text(cleaned_html)
        
        # Secondary Splitting Loop
        for header_chunk in html_header_splits:
            sub_chunks = text_splitter.split_documents([header_chunk])
            
            for chunk in sub_chunks:
                # The html_splitter automatically added unit_name and section_name to chunk.metadata
                chunk.metadata["grade_level"] = book_metadata["grade_level"]
                chunk.metadata["subject"] = book_metadata["subject"]
                final_documents.append(chunk)

# --- 4. Generate Embeddings & Upload to Explicit Columns ---
if final_documents:
    print(f"Created {len(final_documents)} granular chunks. Generating embeddings...")
    
    if len(final_documents) > 10:
        print(f"DEBUG - 10th chunk metadata: {final_documents[10].metadata}")
    
    # Extract text strings to generate embeddings
    texts = [doc.page_content for doc in final_documents]
    embedded_vectors = embeddings.embed_documents(texts)
    
    # Prepare the exact data structure for your SQL columns
    insert_data = []
    for i, doc in enumerate(final_documents):
        insert_data.append({
            "id": str(uuid.uuid4()), 
            "content": doc.page_content,
            "embedding": embedded_vectors[i],
            "grade_level": doc.metadata.get("grade_level"),
            "subject": doc.metadata.get("subject"),
            "unit_name": doc.metadata.get("unit_name", "General Unit"), 
            "section_name": doc.metadata.get("section_name", "General Section"),
            "sub_section_name": doc.metadata.get("sub_section_name", "General Sub-Section") # <-- NEW: Included sub-section
        })
    
    print("Uploading to Supabase...")
    
    # Bulk Insert in batches of 100 to prevent API timeouts
    batch_size = 100
    for i in range(0, len(insert_data), batch_size):
        batch = insert_data[i:i+batch_size]
        supabase.table("documents").insert(batch).execute()
        print(f"Uploaded batch {i//batch_size + 1} of {(len(insert_data) + batch_size - 1) // batch_size}...")

    print(f"Successfully uploaded all chunks for {book_metadata['subject']}! [SUCCESS]")
else:
    print(f"No chunks were created for {book_metadata['subject']}. [FAILED]")
