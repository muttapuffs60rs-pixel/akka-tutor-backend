"""Tiny versioned excerpt repository; never a claim of entire-book coverage."""
import json
from pathlib import Path
from types import SimpleNamespace
from functools import lru_cache
import re


@lru_cache(maxsize=1)
def teaching_records():
    """Local source-checked paraphrases, never promoted production chunks."""
    path = Path(__file__).parent / 'curriculum/reviewed/pilot-teaching.json'
    rows = json.loads(path.read_text(encoding='utf-8'))['records']
    for row in rows:
        if (row['verification_status'] != 'source_checked' or
                not re.fullmatch('[a-f0-9]{64}', row['source_sha256']) or
                not row['pdf_pages'] or not row['source_facts']):
            raise ValueError('Incomplete reviewed teaching evidence')
    return rows


def teaching_matches(query, board, grade, subject):
    """Exact topic aliases within one curriculum. No semantic identity guess."""
    from reference_resolution import source_scope
    scope = source_scope(query)
    matches = []
    for row in teaching_records():
        if (row['board'], row['grade_level'], row['subject']) != (board, grade, subject):
            continue
        if (scope.get('academic_year') or (scope.get('edition') and str(scope['edition']) != row['edition']) or
                (scope.get('term') and scope['term'] != row['term'])):
            continue
        if any(re.search((r'(?<!\w)' + re.escape(alias) + r'(?!\w)') if re.search('[a-zA-Z]', alias)
                         else re.escape(alias), query, re.I) for alias in row['aliases']):
            matches.append(row)
    return matches[:4]


def teaching_evidence(rows):
    return '\n\n'.join(
        f"Source-checked facts (paraphrases, not verbatim): {r['section_name']}; "
        f"{r['source_title']}; chapter {r['chapter_number']}; printed pages {r['printed_pages']}.\n" +
        '\n'.join(r['source_facts']) + '\nTeaching derivations (not printed quotations):\n' +
        '\n'.join(r['teaching_derivations']) for r in rows)


def teaching_citations(rows):
    heading = 'முக்கிய கருத்துகளுக்கான ஆதாரம்:' if rows and rows[0]['subject'] == 'Tamil' else 'Source basis for the core facts:'
    return '\n\n' + heading + '\n' + '\n'.join(
        f"[Source: {r['source_title']}, {r['section_name']}" +
        (f", pp. {', '.join(map(str,r['printed_pages']))}" if r['printed_pages'] else '') + f"]({r['source_url']})"
        for r in {r['id']:r for r in rows}.values())


class ReviewedDatabase:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.maximum = 101

    def table(self, name):
        if name != 'documents':
            raise ValueError('Unsupported source table')
        return ReviewedDatabase(self.rows)

    def select(self, fields):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self

    def execute(self):
        rows = [r for r in self.rows if all(str(r.get(k)) == str(v) for k,v in self.filters)]
        return SimpleNamespace(data=rows[:self.maximum])


def reviewed_database():
    path = Path(__file__).parent / 'curriculum/reviewed/class6-tamil-p49.json'
    rows = json.loads(path.read_text(encoding='utf-8'))['records']
    from educational_accuracy import lookup
    import re
    for row in rows:
        if not re.fullmatch('[a-f0-9]{64}', row.get('source_sha256','')):
            raise ValueError('Missing source fingerprint')
        if row.get('academic_year') is not None or row.get('edition') != '2024':
            raise ValueError('Bundled source edition changed without review')
        canonical = row.get('canonical_reference','')
        if canonical.startswith('thirukkural:'):
            record = lookup(int(canonical.split(':')[1]))
            if not record or row['content'] != '\n'.join(record['lines']):
                raise ValueError('Canonical mapping does not agree with source text')
    return ReviewedDatabase(rows)
