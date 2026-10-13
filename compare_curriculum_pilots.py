"""Compare read-only pilot snapshots to preserved PDFs; write local evidence only."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import re

import pymupdf
from verify_curriculum_text import compare_passage, formatting_normalize

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/'tmp/curriculum-audit'
OUT=ROOT/'curriculum/audit-2026-10-13'


def run():
    ingestion=json.loads((ROOT/'curriculum/ncert_ingestion_report.json').read_text())
    downloads=json.loads((CACHE/'official-downloads.json').read_text())
    current={r['url']:r.get('sha256') for r in downloads if r['status']=='downloaded'}
    pdfs={};sources=[]
    for path in sorted((ROOT.parent/'ncert-books/9/iesc1').glob('*.pdf')):
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        url='https://ncert.nic.in/textbook/pdf/'+path.name
        doc=pymupdf.open(path);pages=[p.get_text(sort=True).strip() for p in doc]
        matched=ingestion[path.stem]['sha256']==digest
        pdfs[url]=(pages,matched,digest)
        sources.append(dict(url=url,path=str(path.resolve()),sha256=digest,pages=len(pages),
            ingestion_receipt_match=matched,current_official_download_match=current.get(url)==digest if url in current else None,
            extracted_pages_with_replacement_character=sum('\ufffd' in p for p in pages)))
    science=[]
    for row in json.loads((CACHE/'cbse-9-Science.json').read_text(encoding='utf-8')):
        source=pdfs.get(row.get('source_url'));page=re.fullmatch(r'PDF page (\d+)',row.get('sub_section_name') or '')
        n=int(page[1]) if page else 0
        valid=bool(source and 1<=n<=len(source[0]))
        result=compare_passage(row['content'],source[0][n-1] if valid else '',
            source_identified=bool(source and source[1]),page_identified=valid)
        science.append(dict(id=row['id'],source_url=row.get('source_url'),pdf_page=n,**result))
    tn_path=ROOT/'tmp/pdfs/official-class6-Term-I.pdf'
    doc=pymupdf.open(tn_path);tn_pages=[p.get_text(sort=True) for p in doc]
    normalized=[formatting_normalize(p) for p in tn_pages]
    tamil=[]
    for row in json.loads((CACHE/'tn-6-Tamil.json').read_text(encoding='utf-8')):
        text=row['content'];ntext=formatting_normalize(text)
        hits=[n+1 for n,p in enumerate(normalized) if len(ntext)>=40 and ntext in p]
        tamil.append(dict(id=row['id'],status='unverifiable',candidate_term1_pdf_pages=hits,
            original_sha256=hashlib.sha256(text.encode()).hexdigest(),reason='No stored source/edition/page identity; candidate text matches are not verification'))
    result={'date':'2026-10-13','extractor':'PyMuPDF '+pymupdf.VersionBind,
            'normalization':'Unicode NFC + whitespace only; no letter/formula repairs',
            'science_counts':dict(Counter(r['status'] for r in science)),
            'science_source_inventory':sources,'science_records':science,
            'tamil_counts':dict(Counter(r['status'] for r in tamil)),
            'tamil_term1_candidate_matches':sum(bool(r['candidate_term1_pdf_pages']) for r in tamil),
            'tamil_reference_pdf_sha256':hashlib.sha256(tn_path.read_bytes()).hexdigest(),
            'tamil_reference_pages_with_replacement_character':sum('\ufffd' in p for p in tn_pages),
            'tamil_records':tamil,
            'limitations':'Extraction matches are not glyph, equation, table, diagram, meaning or completeness verification. No database row is promoted.'}
    (OUT/'pilot-text-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:v for k,v in result.items() if k.endswith('counts') or k=='tamil_term1_candidate_matches'})


if __name__=='__main__':run()
