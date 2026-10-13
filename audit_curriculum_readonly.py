"""Read-only document census. No production imports, RPC writes or model calls.

Raw curriculum snapshots stay in ignored tmp/. Reports contain counts, hashes
and source metadata, never credentials or student records. Counts are not proof
of textbook completeness. Keyset pagination is not a transaction snapshot.
"""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
import ssl
import time
import unicodedata

import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'curriculum/audit-2026-10-13'
CACHE=ROOT/'tmp/curriculum-audit'
FIELDS='id,content,metadata,grade_level,subject,unit_name,section_name,sub_section_name,board,source_url,book_code,language'


def flags(row):
    text=row.get('content') or ''
    return {
        'empty':not text.strip(), 'short_under_40':len(text.strip())<40,
        'replacement_character':'\ufffd' in text,
        'html_or_office_markup':bool(re.search(r'<[/a-zA-Z][^>]*>|\b(?:o:spid|mso-|style=)',text)),
        'control_characters':any(unicodedata.category(c)=='Cc' and c not in '\n\r\t' for c in text),
        'has_tamil':bool(re.search('[\u0b80-\u0bff]',text)),
        'has_latin':bool(re.search('[A-Za-z]',text)),
        'generic_section':not row.get('section_name') or row['section_name'].startswith('General'),
        'missing_source_url':not row.get('source_url'),
        'missing_book_code':not row.get('book_code'),
        'missing_language':not row.get('language'),
        'has_formula_notation':bool(re.search(r'[=²³₀-₉]|\bH2O\b|\bCO2\b',text)),
    }


def run():
    OUT.mkdir(parents=True,exist_ok=True); CACHE.mkdir(parents=True,exist_ok=True)
    settings=dotenv_values(ROOT/'.env')
    endpoint=settings['SUPABASE_URL'].rstrip('/')+'/rest/v1/documents'
    headers={'apikey':settings['SUPABASE_KEY'],'Authorization':'Bearer '+settings['SUPABASE_KEY']}
    started=datetime.now(timezone.utc).isoformat()
    groups=defaultdict(Counter); books=defaultdict(Counter); issues=defaultdict(list)
    seen=defaultdict(Counter); sources=Counter(); metadata_keys=Counter(); raw_digest=hashlib.sha256()
    def get(client,params,count=False):
        for attempt in range(3):
            response=client.get(endpoint,params=params,headers={'Prefer':'count=exact'} if count else {})
            if response.status_code<500: break
            time.sleep(attempt+1)
        response.raise_for_status()
        return response
    with httpx.Client(headers=headers,verify=ssl.create_default_context(),timeout=90) as client:
        before=get(client,{'select':'id','limit':'1'},True).headers.get('content-range')
        last=None; total=0
        with (CACHE/'documents.jsonl').open('w',encoding='utf-8',newline='\n') as dest:
            while True:
                params={'select':FIELDS,'order':'id.asc','limit':1000}
                if last:params['id']='gt.'+last
                rows=get(client,params).json()
                if not rows:break
                for row in rows:
                    encoded=json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n'
                    dest.write(encoded);raw_digest.update(encoded.encode())
                    key=(row.get('board'),row.get('grade_level'),row.get('subject'))
                    group=groups[key];group['chunks']+=1
                    text=row.get('content') or '';group['characters']+=len(text)
                    for name,present in flags(row).items():
                        group[name]+=int(present)
                        if present and len(issues[name])<20:issues[name].append(row['id'])
                    digest=hashlib.sha256(text.encode()).hexdigest()
                    seen[key][digest]+=1
                    meta=row.get('metadata')
                    if isinstance(meta,dict):metadata_keys.update(meta.keys())
                    group['metadata_nonempty']+=bool(meta)
                    for field in ['edition','academic_year','source_sha256','verification_status','page_number']:
                        value=row.get(field) or (meta.get(field) if isinstance(meta,dict) else None)
                        group['has_'+field]+=bool(value)
                    source=row.get('source_url') or ''
                    if source:sources[source]+=1
                    book=(key[0],key[1],key[2],row.get('book_code') or '',row.get('unit_name') or '')
                    books[book][row.get('section_name') or '']+=1
                total+=len(rows);last=rows[-1]['id']
                if total%20000==0:print('Read curriculum rows:',total,flush=True)
                if len(rows)<1000:break
        after=get(client,{'select':'id','limit':'1'},True).headers.get('content-range')
    matrix=[]
    for key,metrics in sorted(groups.items(),key=lambda p:str(p[0])):
        metrics['exact_duplicate_excess']=sum(n-1 for n in seen[key].values())
        matrix.append(dict(board=key[0],grade=key[1],subject=key[2],**metrics))
    report=dict(started_utc=started,finished_utc=datetime.now(timezone.utc).isoformat(),
        operations='GET documents only; no student data or embeddings',before_count=before,after_count=after,
        scanned=total,snapshot_sha256=raw_digest.hexdigest(),coverage=matrix,
        metadata_keys=dict(metadata_keys),issue_example_ids=dict(issues),sources=dict(sources),
        books=[dict(board=k[0],grade=k[1],subject=k[2],book_code=k[3],unit_label=k[4],sections=dict(v)) for k,v in books.items()],
        limitations='Census is not a transaction snapshot. Heuristic flags require review. Unit labels are not necessarily book titles. No completeness or semantic verification claim.')
    (OUT/'database-census.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(matrix[0]));writer.writeheader();writer.writerows(matrix)
    print('Completed:',total,'rows;',len(matrix),'curriculum groups',flush=True)


if __name__=='__main__':run()
