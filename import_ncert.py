"""Resumable NCERT English-medium ingestion with board-scoped verification."""
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
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
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
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
    books = json.loads((ROOT / 'curriculum/ncert_manifest.json').read_text())
    report = json.loads(args.report.read_text()) if args.report.exists() else {}
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2)
    model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                                local_files_only=True, device='cuda' if torch.cuda.is_available() else 'cpu')
    while True:
        for book in books:
            for chapter in range(1, book['chapters'] + 1):
                key = f"{book['code']}{chapter:02}"
                path = args.books / str(book['grade']) / book['code'] / (key + '.pdf')
                if not path.exists():
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if report.get(key, {}).get('sha256') == digest:
                    continue
                rows, pages = parse(path, book, chapter)
                for start in range(0, len(rows), 100):
                    batch = rows[start:start + 100]
                    vectors = model.encode([r['content'] for r in batch], batch_size=32, show_progress_bar=False)
                    for row, vector in zip(batch, vectors):
                        row['embedding'] = vector.tolist()
                    for attempt in range(5):
                        try:
                            db.table('documents').upsert(batch, on_conflict='id', ignore_duplicates=True).execute()
                            break
                        except Exception:
                            if attempt == 4:
                                raise
                            time.sleep(2 ** attempt)
                stored = []
                for offset in range(0, len(rows) + 1000, 1000):
                    result = (db.table('documents').select('id').eq('board', 'cbse')
                              .eq('book_code', book['code']).eq('section_name', f"{book['code']} chapter {chapter}")
                              .order('id').range(offset, offset + 999).execute().data)
                    stored.extend(r['id'] for r in result)
                    if len(result) < 1000:
                        break
                if set(r['id'] for r in rows) - set(stored):
                    raise RuntimeError('Verification failed for ' + key)
                report[key] = dict(grade=book['grade'], subject=book['subject'], book=book['title'],
                                   pages=pages, chunks=len(rows), sha256=digest, verified=True)
                args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
                print('VERIFIED', key, len(rows), 'chunks; total chapters', len(report), flush=True)
        if not args.watch or len(report) == sum(b['chapters'] for b in books):
            break
        time.sleep(15)


if __name__ == '__main__':
    main()
