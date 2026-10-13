"""Acquire licensed Project Madurai editions; never synthesize missing records.

Run python import_canonical.py. Requires requests, beautifulsoup4 and, on
Windows behind a managed proxy, truststore. Original headers remain intact.
"""
import hashlib
import json
import re
from pathlib import Path
import unicodedata

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent / 'curriculum' / 'canonical'
BASE = 'https://www.projectmadurai.org/pm_etexts/utf8/'


def acquire():
    if (ROOT / 'thirukkural.json').exists():
        raise ValueError('Canonical corpus already exists; use the audit tools to preserve reviewed corrections')
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    ROOT.mkdir(parents=True, exist_ok=True)
    records, chapters, sources = [], [], []
    for part in range(1, 5):
        name = f'pmuni0450_0{part}.html'
        response = requests.get(BASE + name, timeout=60)
        response.raise_for_status()
        raw = response.content
        soup = BeautifulSoup(raw, 'html.parser')
        text = unicodedata.normalize('NFC', soup.get_text('\n', strip=True))
        if 'provided this header' not in text:
            raise ValueError('Source permission header missing')
        # Preserve the complete published edition, including its copyright header.
        (ROOT / name).write_bytes(raw)
        sources.append(dict(url=BASE + name, file=name, sha256=hashlib.sha256(raw).hexdigest(),
                            attribution='Project Madurai; Parimelazhagar commentary',
                            license='Freely distribute with original header intact'))
        # Chapter headings have three dotted indices; sections have only two.
        for heading in soup.select('h3'):
            for line in heading.get_text('\n', strip=True).splitlines():
                match = re.match(r'^\d+\.\d+\.\d+\.?\s+(.+)', line)
                if match:
                    chapters.append(match[1].strip())
        matches = list(re.finditer(r'^[ \t]*(\d{1,4})\.?[ \t]*$', text, re.M))
        for i, match in enumerate(matches):
            number = int(match[1])
            body = text[match.end():matches[i+1].start() if i+1 < len(matches) else len(text)]
            lines = [re.sub(r'\s+', ' ', x).strip() for x in body.splitlines() if x.strip()]
            if len(lines) < 2 or not all(re.search('[\u0b80-\u0bff]', x) for x in lines[:2]):
                raise ValueError(f'Invalid verse {number}')
            glossary = []
            for line in lines[2:]:
                if line.startswith('விளக்கம்') or re.match(r'^\d+\.\d+', line):
                    break
                glossary.append(line)
            records.append(dict(number=number, chapter=(number-1)//10+1,
                                lines=lines[:2], gloss=' '.join(glossary).strip(), source=BASE+name))
        print(f'Acquired part {part}: {len(matches)} verses')
    # A separate public-domain text transcription supplies numbering, not modern
    # commentaries whose underlying rights cannot be inferred from a repo license.
    base = 'https://raw.githubusercontent.com/yuvarajvelmurugan/thirukkural/main/'
    license_response = requests.get(base + 'LICENSE', timeout=60)
    license_response.raise_for_status()
    if 'CC0' not in license_response.text:
        raise ValueError('CC0 source license missing')
    (ROOT / 'CC0-LICENSE.txt').write_bytes(license_response.content)
    response = requests.get(base + 'thirukkural-dataset.json', timeout=60)
    response.raise_for_status()
    dataset = response.json()
    if [r['kural_en'] for r in dataset] != list(range(1, 1331)):
        raise ValueError('Incomplete numbered transcription')
    compact = lambda x: re.sub(r'[^\u0b80-\u0bff]', '', unicodedata.normalize('NFC', x))
    verified, conflicts, published = 0, [], []
    for row in dataset:
        number = row['kural_en']
        candidates = [r for r in records if r['number'] == number]
        matching = [r for r in candidates if compact('\n'.join(r['lines'])) == compact(row['kural'])]
        # Multiple different source readings are never silently resolved.
        status = 'verified' if len(candidates) == 1 and len(matching) == 1 else 'conflict'
        record = dict(number=number, chapter=row['athikaaram_en'], chapter_name=row['athikaaram'],
                      lines=row['kural'].splitlines(), status=status, gloss='', source=base+'thirukkural-dataset.json')
        if record['chapter'] != (number-1)//10+1 or len(record['lines']) != 2:
            raise ValueError(f'Invalid chapter or lines: {number}')
        if status == 'verified':
            verified += 1
            record.update(gloss=matching[0]['gloss'], source=matching[0]['source'])
        else:
            conflicts.append(dict(number=number, reason='Absent, duplicate, or conflicting authoritative transcription',
                                  source_readings=[r['lines'] for r in candidates]))
        published.append(record)
    chapters = [next(r['chapter_name'] for r in published if r['chapter'] == n) for n in range(1,134)]
    output = dict(version='pm-parimelazhagar-2013-import-v1', language='ta',
                  verification='Source transcription with structural checks; not a teacher-reviewed modern gloss',
                  sources=sources, chapters=chapters, records=published,
                  conflicts=conflicts, verified_count=verified)
    (ROOT / 'thirukkural.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Indexed 1330 numbered couplets / 133 chapters; verified {verified}; quarantined {len(conflicts)}')


if __name__ == '__main__':
    acquire()
