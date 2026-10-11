"""Resumable NCERT English-medium ingestion with board-scoped verification."""
print("Loading ingestion dependencies", flush=True)
import ssl
import httpx
from supabase.lib.client_options import SyncClientOptions
from huggingface_hub import set_client_factory
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import pymupdf
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from supabase import create_client

ROOT = Path(__file__).parent


def parse(path, book, chapter):
    rows = []
    doc = pymupdf.open(path)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    total = bad = 0
    for page_number, page in enumerate(doc, 1):
        text = page.get_text(sort=True).strip()
        total += len(text)
        bad += text.count('\ufffd')
        if len(text) < 40:
            continue
        for index, chunk in enumerate(splitter.split_text(text)):
            identity = f"cbse|en|{book['grade']}|{book['code']}|{chapter}|{page_number}|{index}|{chunk}"
            rows.append(dict(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)), board='cbse', language='en',
                grade_level=book['grade'], subject=book['subject'], book_code=book['code'],
                source_url=f"https://ncert.nic.in/textbook/pdf/{book['code']}{chapter:02}.pdf",
                unit_name=book['title'], section_name=f"{book['code']} chapter {chapter}",
                sub_section_name=f'PDF page {page_number}', content=chunk))
    if not rows or total < 100 or bad / max(total, 1) > .02:
        raise ValueError('Extraction quality check failed: ' + str(path))
    return rows, len(doc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--books', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    print('Connecting database', flush=True)
    ssl_context = ssl.create_default_context()
    set_client_factory(lambda: httpx.Client(verify=ssl_context, follow_redirects=True, timeout=60))
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'], options=SyncClientOptions(httpx_client=httpx.Client(verify=ssl_context, timeout=120), auto_refresh_token=False, persist_session=False))
    books = json.loads((ROOT / 'curriculum/ncert_manifest.json').read_text())
    report = json.loads(args.report.read_text()) if args.report.exists() else {}
    print('Loading embedding runtime', flush=True)
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2)
    model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                                local_files_only=True, device='cuda' if torch.cuda.is_available() else 'cpu')
    if torch.cuda.is_available():
        import numpy as np
        probe = ['A plant needs sunlight.', 'Numbers and equations describe patterns.']
        reference = model.encode(probe)
        model.half()
        candidate = model.encode(probe).astype(np.float32)
        cosine = (reference*candidate).sum(1)/(np.linalg.norm(reference,axis=1)*np.linalg.norm(candidate,axis=1))
        if min(cosine) < .9999:
            raise RuntimeError('Embedding precision verification failed')
    print('Embedding model ready', flush=True)
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

    def retry(operation):
        for attempt in range(5):
            try:
                return operation()
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2**attempt)

    def upload(book, chapter, key, rows, pages, digest):
        for start in range(0, len(rows), 200):
            batch = rows[start:start+200]
            retry(lambda: db.table('documents').upsert(batch, on_conflict='id', ignore_duplicates=True).execute())
        stored = []
        # Use primary-key lookups rather than sorting/scanning the growing corpus.
        for offset in range(0, len(rows), 100):
            ids = [row['id'] for row in rows[offset:offset+100]]
            result = retry(lambda: db.table('documents').select('id').eq('board','cbse')
                           .in_('id',ids).execute().data)
            stored.extend(r['id'] for r in result)
        if set(r['id'] for r in rows)-set(stored):raise RuntimeError('Verification failed: '+key)
        return key,dict(grade=book['grade'],subject=book['subject'],book=book['title'],pages=pages,chunks=len(rows),sha256=digest,verified=True)

    def record(futures):
        for future in futures:
            key,result=future.result()
            report[key]=result
            temporary = args.report.with_suffix('.tmp')
            temporary.write_text(json.dumps(report,indent=2),encoding='utf-8')
            temporary.replace(args.report)
            print('VERIFIED',key,result['chunks'],'chunks; total chapters',len(report),flush=True)

    # Bound uploads to four workers; model inference stays on the main thread.
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending=set()
        for book in books:
            for chapter in book.get('chapter_ids',range(1,book['chapters']+1)):
                key=f"{book['code']}{chapter:02}"
                path=args.books/str(book['grade'])/book['code']/(key+'.pdf')
                if not path.exists():raise FileNotFoundError(path)
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                if report.get(key,{}).get('verified') and report[key].get('sha256')==digest:continue
                rows,pages=parse(path,book,chapter)
                vectors=model.encode([r['content'] for r in rows],batch_size=32,show_progress_bar=False)
                for row,vector in zip(rows,vectors):row['embedding']=vector.tolist()
                pending.add(pool.submit(upload,book,chapter,key,rows,pages,digest))
                if len(pending)>=8:
                    done,pending=wait(pending,return_when=FIRST_COMPLETED);record(done)
        if pending:record(wait(pending)[0])


if __name__ == '__main__':
    main()
