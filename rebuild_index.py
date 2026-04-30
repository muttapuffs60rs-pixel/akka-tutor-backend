import os
from langchain_community.document_loaders import TextLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import CharacterTextSplitter

# 1. Setup the tools
model_name = "sentence-transformers/all-MiniLM-L6-v2"
embeddings = HuggingFaceEmbeddings(model_name=model_name)

# 2. Load your textbook (Ensure your .txt file is in the same folder!)
# Replace 'science_textbook.txt' with your actual filename
loader = TextLoader("10th_science.txt", encoding="utf-8")
documents = loader.load()
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
docs = text_splitter.split_documents(documents)

# 3. Create the NEW vault
print("Building the fresh vault... please wait.")
vector_db = FAISS.from_documents(docs, embeddings)

# 4. Save it with the name your API expects
vector_db.save_local("faiss_index_science")
print("SUCCESS! Your 'faiss_index_science' folder is now perfectly matched to your API.")