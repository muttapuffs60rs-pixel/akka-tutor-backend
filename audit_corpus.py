"""Compare preserved editions; publish only evidenced transcription corrections.

An independent-numbered CC0 transcription is a secondary aid, not an authority
over Project Madurai. Two PM editions agreeing on a reading can establish an
edition-specific correction; disagreements between PM editions stay quarantined.
Original HTML and the previous reading are always retained.
"""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from bs4 import BeautifulSoup

ROOT=Path(__file__).parent/'curriculum'/'canonical'
URL='https://www.projectmadurai.org/pm_etexts/utf8/pmuni0001.html'


def compact(text):
    # Ignore only layout, punctuation, and format characters. Never remove letters,
    # diacritics, or foreign corruption characters to manufacture agreement.
    return ''.join(c for c in unicodedata.normalize('NFC',text)
                   if not c.isspace() and unicodedata.category(c)[0]!='P' and unicodedata.category(c)!='Cf')


def plain_records(raw):
    # Repair only this documented malformed tag in the parse view; raw bytes stay intact.
    if isinstance(raw,bytes): raw=raw.decode('utf-8')
    raw=raw.replace('<font color="blue"\n3.2..1', '<font color="blue">\n3.2..1')
    soup=BeautifulSoup(raw,'html.parser')
    lines=[re.sub(r'\s+',' ',x).strip() for x in soup.get_text('\n',strip=True).splitlines() if x.strip()]
    records=defaultdict(list)
    chapters=[]
    chapter=None
    for i,line in enumerate(lines):
        heading=re.match(r'^\d+[.,]+\s*\d+[.,]+\s*\d+\.?\s+(.+)',line)
        if heading:
            chapter=heading[1];chapters.append(chapter)
        match=re.match(r'^([\u0b80-\u0bff].*?)\s+(\d{1,4})$',line)
        if match and i and re.search('[\u0b80-\u0bff]',lines[i-1]):
            records[int(match[2])].append({'lines':[lines[i-1],match[1]],'chapter_name':chapter,'chapter':len(chapters)})
    return records,chapters


def classify(a,b):
    if a==b:return 'identical'
    if unicodedata.normalize('NFC',a)==unicodedata.normalize('NFC',b):return 'unicode_normalization'
    if re.sub(r'\s+','',a)==re.sub(r'\s+','',b):return 'whitespace_or_line_break'
    if compact(a)==compact(b):return 'punctuation_or_formatting'
    if any(c in a+b for c in ('\ufffd','¡','�')):return 'encoding_or_transcription_corruption'
    changes=[(tag,a[i:j],b[k:l]) for tag,i,j,k,l in SequenceMatcher(None,compact(a),compact(b)).get_opcodes() if tag!='equal']
    if all(tag in ('insert','delete') for tag,_,_ in changes):return 'missing_or_added_text_requires_review'
    return 'spelling_or_word_difference_requires_review'


def audit(download=False):
    current=json.loads((ROOT/'thirukkural.json').read_text(encoding='utf-8'))
    if current.get('version') == 'published-edition-crosscheck-v3':
        raise ValueError('Use audit_disputed.py for the current corpus; refusing to overwrite the continued audit')
    path=ROOT/'pmuni0001.html'
    if download or not path.exists():
        import requests
        try:
            import truststore;truststore.inject_into_ssl()
        except ImportError:pass
        response=requests.get(URL,timeout=60);response.raise_for_status()
        if 'provided this header' not in response.text:raise ValueError('Missing distribution permission')
        path.write_bytes(response.content)
    data=json.loads((ROOT/'thirukkural.json').read_text(encoding='utf-8'))
    plain,chapters=plain_records(path.read_bytes())
    if len(chapters)!=133:raise ValueError(f'Unexpected chapter count {len(chapters)}')
    findings=[]
    original_conflicts=data.get('initial_conflicts',data['conflicts'])
    data['initial_conflicts']=original_conflicts
    for conflict in original_conflicts:
        n=conflict['number'];record=data['records'][n-1]
        before=record.get('secondary_transcription',record['lines'])
        pm=conflict['source_readings'];other=plain.get(n,[])
        category='missing_authoritative_identifier' if not pm else 'duplicate_authoritative_identifier' if len(pm)>1 else classify('\n'.join(before),'\n'.join(pm[0]))
        finding={'number':n,'category':category,'secondary_reading':before,'commentary_readings':pm,
                 'plain_edition_readings':[r['lines'] for r in other],'status':'blocked'}
        if len(pm)==len(other)==1 and compact('\n'.join(pm[0]))==compact('\n'.join(other[0]['lines'])) and other[0]['chapter']==record['chapter']:
            # Retrieve the gloss from the preserved commentary, not from the CC0
            # repository's contemporary translations of uncertain authorship.
            part=1 if n<=380 else 2 if n<=730 else 3 if n<=1080 else 4
            soup=BeautifulSoup((ROOT/f'pmuni0450_0{part}.html').read_bytes(),'html.parser')
            text=unicodedata.normalize('NFC',soup.get_text('\n',strip=True))
            match=re.search(r'^[ \t]*'+str(n)+r'\.?[ \t]*$',text,re.M)
            rest=text[match.end():] if match else ''
            stop=re.search(r'^[ \t]*\d{1,4}\.?[ \t]*$',rest,re.M)
            body=rest[:stop.start()] if stop else rest
            lines=[re.sub(r'\s+',' ',line).strip() for line in body.splitlines() if line.strip()]
            gloss=[]
            for line in lines[2:]:
                if line.startswith('விளக்கம்') or re.match(r'^\d+\.\d+',line):break
                gloss.append(line)
            if gloss:
                record.update(lines=pm[0],gloss=' '.join(gloss),status='verified',
                    source=f'https://www.projectmadurai.org/pm_etexts/utf8/pmuni0450_0{part}.html',
                    secondary_transcription=before,verification_basis='Two preserved Project Madurai editions agree',
                    corroborating_source=URL,chapter_name=other[0]['chapter_name'])
                finding.update(status='corrected_with_provenance',resolution='Adopted agreeing PM edition text; retained differing secondary reading')
        findings.append(finding)
    # Chapter boundaries are independently checked against headings in the plain
    # edition, rather than inferred only by dividing the canonical number by ten.
    boundaries=[]
    for chapter in range(1,134):
        for n in ((chapter-1)*10+1,chapter*10):
            rows=plain.get(n,[])
            if len(rows)!=1 or rows[0]['chapter']!=chapter:boundaries.append(n)
    data['conflicts']=[f for f in findings if f['status']=='blocked']
    data['verified_count']=sum(r['status']=='verified' for r in data['records'])
    data['version']='pm-edition-crosscheck-v2'
    if not any(s['file']==path.name for s in data['sources']):
        data['sources'].append({'url':URL,'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
          'attribution':'Project Madurai 1998–2000; Unicode revision 2021','license':'Freely distribute with original header intact'})
    report={'total':len(data['records']),'initial_discrepancies':len(original_conflicts),
      'verified':data['verified_count'],'blocked':len(data['conflicts']),
      'categories':dict(Counter(f['category'] for f in findings)),
      'resolutions':dict(Counter(f['status'] for f in findings)),
      'plain_edition_duplicate_ids':[n for n,rows in plain.items() if len(rows)>1],
      'plain_edition_missing_ids':[n for n in range(1,1331) if n not in plain],
      'chapter_boundary_exceptions':boundaries,'findings':findings,
      'limitations':'Agreement establishes these published edition readings, not a universal critical edition or human review of all meanings.'}
    (ROOT/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'thirukkural.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='findings'},ensure_ascii=True))


if __name__=='__main__':audit()
