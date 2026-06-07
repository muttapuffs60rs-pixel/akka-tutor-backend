import os
import uuid
import glob
import traceback
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

# --- 2. Parsers ---
headers_to_split_on = [
    ("h1", "unit_name"),
    ("h2", "section_name"),
    ("h3", "sub_section_name"),
    ("h4", "sub_sub_section_name"),
]
html_splitter = HTMLHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800, 
    chunk_overlap=100,
    separators=["\n\n", "\n", ".", " ", ""]
)

def extract_metadata(filename):
    name = filename.replace("Class_12_", "")
    if "_English_Medium" in name:
        subject_part = name.split("_English_Medium")[0]
    elif "_Tamil_Medium" in name:
        subject_part = name.split("_Tamil_Medium")[0]
    else:
        subject_part = name.split("-")[0]
        
    subject = subject_part.replace("_", " ")
    
    if "-Volume_1-" in filename:
        subject += " Volume 1"
    elif "-Volume_2-" in filename:
        subject += " Volume 2"
        
    # Clean up any potential double spaces or weird artifacts
    subject = subject.replace("  ", " ").strip()
    # Correct ampersand if it was replaced incorrectly
    subject = subject.replace("&", "and")
    
    return {"grade_level": 12, "subject": subject}

def process_book(epub_file_path):
    filename = os.path.basename(epub_file_path)
    book_metadata = extract_metadata(filename)
    
    # Skip duplicates like " (1).epub"
    if " (1).epub" in filename:
        print(f"Skipping duplicate file: {filename}")
        return

    print(f"\n======================================")
    print(f"Loading EPUB: {filename}")
    print(f"Parsed Metadata: {book_metadata}")
    
    try:
        book = epub.read_epub(epub_file_path)
    except Exception as e:
        print(f"Failed to read EPUB {filename}: {e}")
        return

    final_documents = []

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            html_content = item.get_body_content().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html_content, "html.parser")
            
            for element in soup(["script", "style", "meta", "link", "noscript", "footer", "nav"]):
                element.decompose()
                
            for header in soup(["h1", "h2", "h3", "h4", "h5", "h6"]):
                clean_text = header.get_text(separator=" ", strip=True)
                new_header = soup.new_tag(header.name)
                new_header.string = clean_text
                header.replace_with(new_header)
                
            cleaned_html = str(soup)
            
            if not cleaned_html.strip():
                continue
                
            html_header_splits = html_splitter.split_text(cleaned_html)
            
            for header_chunk in html_header_splits:
                sub_chunks = text_splitter.split_documents([header_chunk])
                
                for chunk in sub_chunks:
                    chunk.metadata["grade_level"] = book_metadata["grade_level"]
                    chunk.metadata["subject"] = book_metadata["subject"]
                    final_documents.append(chunk)

    if final_documents:
        print(f"Created {len(final_documents)} chunks. Generating embeddings...")
        
        # Batch embedding generation
        texts = [doc.page_content for doc in final_documents]
        
        try:
            embedded_vectors = embeddings.embed_documents(texts)
        except Exception as e:
            print(f"Error generating embeddings for {filename}: {e}")
            return
        
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
                "sub_section_name": doc.metadata.get("sub_section_name", "General Sub-Section")
            })
        
        print("Uploading to Supabase...")
        batch_size = 100
        for i in range(0, len(insert_data), batch_size):
            batch = insert_data[i:i+batch_size]
            try:
                supabase.table("documents").insert(batch).execute()
            except Exception as e:
                print(f"Error uploading batch {i//batch_size} for {filename}: {e}")
        
        print(f"Successfully uploaded {len(final_documents)} chunks for {book_metadata['subject']}! [SUCCESS]")
    else:
        print(f"No chunks were created for {book_metadata['subject']}. [FAILED]")


if __name__ == "__main__":
    directory = r"C:\Users\dines\Downloads\Books\12"
    epub_files = glob.glob(os.path.join(directory, "*.epub"))
    
    print(f"Found {len(epub_files)} EPUB files in {directory}")
    
    for file_path in epub_files:
        try:
            process_book(file_path)
        except Exception as e:
            print(f"CRITICAL ERROR processing {file_path}:")
            traceback.print_exc()
            
    print("\nALL BOOKS PROCESSED!")
