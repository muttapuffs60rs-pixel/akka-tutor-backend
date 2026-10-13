"""Review quarantined readings against preserved published editions.

Default: write a review report only. --apply adopts only an unambiguous agreement
between two named published editions. Secondary CC0 text is not a deciding vote.
No generated text, fuzzy matches, transliteration or letter substitutions.
TVA pages are research evidence in ignored tmp/tvu, not a redistributed commentary.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from bs4 import BeautifulSoup
from audit_corpus import ROOT, compact, plain_records

THIRD_URL = 'https://www.projectmadurai.org/pm_etexts/utf8/pmuni0017.html'
TVA_URL = 'https://www.tamilvu.org/slet/l2100/l2100pd1.jsp?auth_pub_id=31&bookid=31&pno='
TVA35_URL = 'https://www.tamilvu.org/slet/l2100/l2100pd1.jsp?auth_pub_id=35&bookid=31&pno='


def text_lines(raw):
    return [re.sub(r'\s+', ' ', x).strip() for x in BeautifulSoup(raw, 'html.parser')
            .get_text('\n', strip=True).splitlines() if x.strip()]


def tamil_verse(lines):
    return len(lines) == 2 and all(re.fullmatch(r'[\u0b80-\u0bff\s.,;:!?\"\u2018\u2019\u201c\u201d()\-–—]+', x) for x in lines)


def translation_edition(raw):
    """Check chapter heading, local ordinal AND separately printed global number."""
    rows = defaultdict(list)
    issues = []
    chapter = None
    lines = text_lines(raw)
    for i, text in enumerate(lines):
        heading = re.match(r'^(\d{1,3})\.\s+.* - [A-Za-z]', text)
        if heading:
            chapter = int(heading[1])
        match = re.match(r'^(10|[1-9])\.\s*([\u0b80-\u0bff].*)$', text)
        if not match or i+3 >= len(lines) or not tamil_verse([match[2], lines[i+1]]):
            continue
        printed = re.search(r'(\d{1,4})$', lines[i+3])
        if not printed:
            issues.append({'ordinal':match[1], 'reason':'missing printed global number'})
            continue
        number = int(printed[1])
        if not chapter or number != (chapter-1)*10+int(match[1]) or not 1 <= number <= 1330:
            issues.append({'printed_number':number, 'chapter':chapter, 'reason':'number/ordinal/chapter mismatch'})
            continue
        rows[number].append({'lines':[match[2],lines[i+1]], 'chapter':chapter,
                             'source':THIRD_URL, 'file':'pmuni0017.html'})
    return rows, issues


def tva_edition(raw, chapter):
    rows = defaultdict(list)
    lines = text_lines(raw)
    # An HTTP 200 publisher exception page is not a textbook page.
    if not any(re.match(r'^'+str(chapter)+r'\.\s+[\u0b80-\u0bff]', x) for x in lines):
        return rows
    for i, text in enumerate(lines):
        match = re.match(r'^(10|[1-9])\.\s*([\u0b80-\u0bff].*)$', text)
        if not match or i+3 >= len(lines) or not tamil_verse([match[2],lines[i+1]]):
            continue
        numbers = [int(x) for x in lines[i+2:i+6] if re.fullmatch(r'\d{1,4}',x)]
        expected = (chapter-1)*10+int(match[1])
        if len(numbers) != 1 or numbers[0] != expected:
            continue
        rows[expected].append({'lines':[match[2],lines[i+1]], 'chapter':chapter,
                               'source':TVA_URL+str(chapter)})
    return rows


def commentary_records():
    rows = []
    for part in range(1,5):
        name = f'pmuni0450_0{part}.html'
        text = unicodedata.normalize('NFC', BeautifulSoup((ROOT/name).read_bytes(),'html.parser').get_text('\n',strip=True))
        positions = list(re.finditer(r'^[ \t]*(\d{1,4})\.?[ \t]*$',text,re.M))
        for i, match in enumerate(positions):
            body = text[match.end():positions[i+1].start() if i+1<len(positions) else len(text)]
            lines = [re.sub(r'\s+',' ',x).strip() for x in body.splitlines() if x.strip()]
            if len(lines)<2:
                continue
            gloss=[]
            for line in lines[2:]:
                if line.startswith('விளக்கம்') or re.match(r'^\d+\.\d+',line):
                    break
                gloss.append(line)
            gloss=' '.join(gloss)
            if any(unicodedata.category(c)[0] in ('L','M') and not '\u0b80'<=c<='\u0bff' for c in gloss):
                gloss=''
            rows.append({'number':int(match[1]),'lines':lines[:2], 'gloss':gloss,
                         'source':'https://www.projectmadurai.org/pm_etexts/utf8/'+name,'file':name})
    return rows


def kalaignar_edition(raw, page):
    """Read only printed numbered couplets, never the modern commentary.

    The page offset is a cross-check, not a source of inferred verse numbers.
    Require all five separately printed consecutive global numbers on the page.
    """
    lines=text_lines(raw)
    positions=[(i,int(x[:-1])) for i,x in enumerate(lines) if re.fullmatch(r'\d{1,4}\.',x)]
    expected=list(range((page-23)*5+1,(page-23)*5+6))
    if [n for _,n in positions] != expected or not all(1<=n<=1330 for n in expected):
        return {}
    rows={}
    for i,n in positions:
        verse=lines[i+1:i+3]
        if tamil_verse(verse):
            rows[n]=[{'lines':verse,'chapter':(n-1)//10+1,'source':TVA35_URL+str(page)}]
    return rows


def agreement(candidates):
    groups = defaultdict(list)
    for name, rows in candidates.items():
        # Duplicate identifiers are not independent votes.
        if len(rows)==1 and tamil_verse(rows[0]['lines']):
            groups[compact(''.join(rows[0]['lines']))].append((name, rows[0]))
    accepted=[group for group in groups.values() if len(group)>=2]
    return accepted[0] if len(accepted)==1 else None


def review(apply=False):
    baseline_path=ROOT/'validation-report-v2.json'
    if not baseline_path.exists():
        # Snapshot before any adoption; subsequent audits use this immutable scope.
        baseline_path.write_bytes((ROOT/'validation-report.json').read_bytes())
    baseline=json.loads(baseline_path.read_text(encoding='utf-8'))
    data=json.loads((ROOT/'thirukkural.json').read_text(encoding='utf-8'))
    for source in data['sources']:
        if hashlib.sha256((ROOT/source['file']).read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('Preserved canonical source changed; explicit fresh review required')
    third, issues=translation_edition((ROOT/'pmuni0017.html').read_bytes())
    plain,_=plain_records((ROOT/'pmuni0001.html').read_bytes())
    commentary=commentary_records()
    by_number=defaultdict(list)
    for row in commentary:
        by_number[row['number']].append(row)
    tva={}; receipts=[]
    for path in sorted((ROOT.parents[1]/'tmp/tvu').glob('chapter-*.html')):
        ch=int(path.stem.split('-')[1]); raw=path.read_bytes()
        parsed=tva_edition(raw,ch);tva.update(parsed)
        receipts.append({'url':TVA_URL+str(ch),'sha256':hashlib.sha256(raw).hexdigest(),
                         'parsed_records':sum(map(len,parsed.values()))})
    tva35={}
    for path in sorted((ROOT.parents[1]/'tmp/tva35').glob('page-*.html')):
        page=int(path.stem.split('-')[1]); raw=path.read_bytes()
        parsed=kalaignar_edition(raw,page); tva35.update(parsed)
        receipts.append({'url':TVA35_URL+str(page),'sha256':hashlib.sha256(raw).hexdigest(),
                         'parsed_records':sum(map(len,parsed.values()))})
    findings=[]
    for old in baseline['findings']:
        if old['status']!='blocked':
            continue
        n=old['number'];chapter=(n-1)//10+1
        candidates={'pm_commentary':by_number.get(n,[]),
                    'pm_plain':[dict(r,source='https://www.projectmadurai.org/pm_etexts/utf8/pmuni0001.html')
                                for r in plain.get(n,[]) if r['chapter']==chapter],
                    'pm_translation':third.get(n,[]),'tva':tva.get(n,[]),'tva_kalaignar':tva35.get(n,[])}
        group=agreement(candidates)
        finding={'number':n,'status':'blocked','previous_category':old['category'],
                 'readings':{k:[r['lines'] for r in v] for k,v in candidates.items()}}
        if group:
            fingerprint=compact(''.join(group[0][1]['lines']))
            matching=[r for r in commentary if compact(''.join(r['lines']))==fingerprint and tamil_verse(r['lines'])]
            linked=matching[0] if len(matching)==1 else None
            chosen=linked or next((r for label,r in group if label!='tva'),group[0][1])
            finding.update(status='resolved',agreeing_editions=[label for label,_ in group],
                           source_urls=[r['source'] for _,r in group], adopted_lines=chosen['lines'],
                           commentary_source_number=linked['number'] if linked else None,
                           explanation_available=bool(linked and linked['gloss']))
            if apply:
                record=data['records'][n-1]
                record.setdefault('secondary_transcription',old['secondary_reading'])
                record.update(lines=chosen['lines'],source=chosen['source'],status='verified',
                              gloss=linked['gloss'] if linked else '',
                              commentary_source_number=finding['commentary_source_number'],
                              commentary_status='source_transcription' if finding['explanation_available'] else 'unavailable',
                              verification_basis='Exact letter agreement in two published numbered editions; not semantic review',
                              corroborating_sources=finding['source_urls'])
        elif apply:
            # New independent evidence can expose a second supported reading.
            # Withdraw the earlier adoption instead of retaining stale verified status.
            record=data['records'][n-1]
            record.update(status='conflict',gloss='',commentary_status='unavailable')
            record.pop('corroborating_sources',None)
            record.pop('commentary_source_number',None)
            record.pop('verification_basis',None)
        findings.append(finding)
    report={'reviewed':len(findings),'resolved':sum(f['status']=='resolved' for f in findings),
            'blocked':sum(f['status']=='blocked' for f in findings),
            'commentary_number_displacements':sum(f.get('commentary_source_number') not in (None,f['number']) for f in findings),
            'resolved_without_commentary':sum(f['status']=='resolved' and not f.get('explanation_available') for f in findings),
            'third_edition_records':sum(map(len,third.values())), 'third_edition_issues':issues,
            'tva_receipts':receipts,'findings':findings,
            'limitations':'Textual/numbering evidence only. No fuzzy matching, synthetic correction or TVA modern commentary import. Disagreeing editions remain visible in the audit.'}
    if apply:
        previous_receipts = {r['url']: r['sha256'] for r in data.get('external_review_evidence', [])}
        current_receipts = {r['url']: r['sha256'] for r in receipts}
        if any(current_receipts.get(url) != digest for url, digest in previous_receipts.items()):
            raise ValueError('Publisher evidence changed or is unavailable; explicit fresh review required')
    (ROOT/'dispute-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if apply:
        data['version']='published-edition-crosscheck-v3'
        data['conflicts']=[f for f in findings if f['status']=='blocked']
        data['verified_count']=sum(r['status']=='verified' for r in data['records'])
        if not any(s['file']=='pmuni0017.html' for s in data['sources']):
            data['sources'].append({'url':THIRD_URL,'file':'pmuni0017.html',
                'sha256':hashlib.sha256((ROOT/'pmuni0017.html').read_bytes()).hexdigest(),
                'attribution':'Project Madurai Tamil transcription; translation not imported',
                'license':'Full source file preserved with its distribution header'})
        data['external_review_evidence']=receipts
        (ROOT/'thirukkural.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        replacements={f['number']: f for f in findings}
        latest=dict(baseline,verified=data['verified_count'],blocked=len(data['conflicts']),
                    resolutions={'corrected_with_provenance':baseline['resolutions']['corrected_with_provenance']+report['resolved'],
                                 'blocked':report['blocked']},
                    findings=[replacements.get(f['number'], f) for f in baseline['findings']],
                    continuation_report='dispute-review.json',continuation_resolved=report['resolved'])
        (ROOT/'validation-report.json').write_text(json.dumps(latest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('findings','tva_receipts','third_edition_issues')}))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    review(parser.parse_args().apply)
