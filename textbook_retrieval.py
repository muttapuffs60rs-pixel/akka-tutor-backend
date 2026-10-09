"""Bounded, grade/subject-isolated Tamil lexical retrieval alongside vectors.

Books are read once per cache lifetime, never sent whole to an AI provider.
Original documents are left intact. Exceptions never populate the cache.
"""
from collections import Counter, OrderedDict
import html
import math
import re
import threading
import time
import unicodedata

TAMIL_SUBJECTS = frozenset(('Tamil', 'Advance Tamil', 'Advanced Tamil'))
_CACHE = OrderedDict()
_LOCK = threading.Lock()
CACHE_SECONDS = 900
MAX_CACHED_BOOKS = 8
GRAMMAR_ROOTS = ('பெயரெச்ச', 'வினையெச்ச', 'எழுவாய்', 'விளி',
                 'தொகாநிலை', 'தொகைநிலை', 'வேற்றுமை', 'வினைத்தொகை')

_IGNORE = set('பத்தாம் பதினொன்றாம் பன்னிரண்டாம் ஆறாம் ஏழாம் எட்டாம் ஒன்பதாம் '
              'வகுப்பு வகுப்பில் சிறப்புத் தமிழ் தமிழில் பாடநூலில் பாடநூல் உள்ள '
              'பதில் அளிக்கவும் தருக என்றால் என்ன மற்றும் ஆகியவற்றை ஒவ்வோர் '
              'எடுத்துக்காட்டுடன் விளக்குக விளக்கம் தெளிவாக வரிவரியாக '
              'என்று தொடங்கும் செய்யுளுக்கு பாடலின் மையக்கருத்து ஆகியவற்றைத் '
              'உணர்த்தும் கருத்து செய்யுள் பாடல் தொடர் பொருள் பொருளை பொருளையும் '
              'செய்யுளின் விளக்குங்கள் சிறுகதையில் பாடத்தில் சூழலை '
              'என்னும் அடியின் விதத்தையும் யாவை பணிகள்'.split())


def clean_passage(text):
    text = unicodedata.normalize('NFC', html.unescape(text or ''))
    text = re.sub(r'<[^>]*>|\[if[^\]]*\]|<!\[endif\]|\bendif\?', ' ', text, flags=re.I)
    text = re.sub(r'\b(?:style|o:spid|type|src|o:title|alt)\s*=\s*(?:"[^"]*"|\x27[^\x27]*\x27)', ' ', text)
    text = text.replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')
    # Preserve verse lines; search on whitespace-normalized copies.
    return '\n'.join(re.sub(r'[ \t]+', ' ', line).strip()
                     for line in text.replace('\r', '').splitlines() if line.strip()).strip()


def normalized(text):
    return re.sub(r'\s+', ' ', clean_passage(text)).strip()


def compact(text):
    return re.sub(r'[^\u0b80-\u0bffa-z0-9]', '', normalized(text).lower())


def stem(word):
    # Match joined/spaced compounds and common title/author inflections.
    for root in GRAMMAR_ROOTS:
        if word.startswith(root):
            return root
    word = re.sub(r'த்தொடர்.*$', '', word)
    word = re.sub(r'த்$', '', word)
    for ending, replacement in [('ரின்', 'ர்'), ('ருடைய', 'ர்'), ('த்தின்', 'ம்'),
                                ('த்தை', 'ம்'), ('களின்', ''), ('களை', '')]:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[:-len(ending)] + replacement
    return word


def tokens(text):
    return [stem(w) for w in re.findall(r'[\u0b80-\u0bff]+|[a-z]+', normalized(text).lower())
            if w not in _IGNORE and len(w) >= 4]


def tamil_terms(question):
    return list(dict.fromkeys(tokens(question)))[:24]


def grammar_query(question):
    # Classify the requested task, not words inside the student's examples.
    outside = re.sub(r'[“"‘\x27][^”"’\x27]+[”"’\x27]', ' ', question)
    return bool(re.search(r'இலக்கண|பெயரெச்ச|வினையெச்ச|எழுவாய்|விளித்தொடர்|'
                          r'தொகாநிலை|தொகைநிலை|வேற்றுமை|வினைத்தொகை|grammar', outside, re.I))


def named_work_query(question):
    if grammar_query(question):
        return False
    return bool(re.search(r'[“"‘].+?[”"’]|செய்யு|பாடல|poem|poet', question, re.I))


class TamilBookIndex:
    def __init__(self, rows):
        self.rows = []
        seen = set()
        for row in rows:
            body = clean_passage(row.get('content', ''))
            if (len(compact(body)) < 35 or body in seen or
                    re.search(r'\b(?:alt|style|o:title|o:spid|src)\s*=|\.(?:png|emz|jpg)"', body)):
                continue
            if any(w in normalized(body) for w in ('பாடத்தலைப்புகள்', 'பக்க எண்')):
                continue
            seen.add(body)
            title = ' '.join(row.get(k) or '' for k in ('unit_name', 'section_name', 'sub_section_name'))
            self.rows.append((dict(row, content=body), Counter(tokens(body)), set(tokens(title)),
                              compact(body), compact(title)))
        self.frequency = Counter()
        for _, body, title, _, _ in self.rows:
            self.frequency.update(set(body) | title)

    def search(self, question, count=6):
        terms = tamil_terms(question)
        grammar = grammar_query(question)
        grammar_terms = set(terms) & set(GRAMMAR_ROOTS) if grammar else set()
        phrases = [compact(p) for p in re.findall(r'[“"‘\x27]([^”"’\x27]+)[”"’\x27]', question)
                   if len(compact(p)) >= 10]
        if grammar:
            # Novel examples need the grammatical definitions, not an exact
            # quotation match. Preserve strict matching for literary works.
            phrases = []
        phrase_matches = [any(p in body or p in title for p in phrases)
                          for _, _, _, body, title in self.rows]
        if phrases and not any(phrase_matches):
            return []
        ranked = []
        for i, (row, body, title, compact_body, compact_title) in enumerate(self.rows):
            matched = set(t for t in terms if t in body or t in title)
            if grammar_terms and not grammar_terms.intersection(matched):
                continue
            if not matched and not phrase_matches[i]:
                continue
            score = sum(math.log(1 + len(self.rows) / (1 + self.frequency[t])) *
                        (min(body[t], 2) + 0.5 * (t in title)) for t in matched)
            if phrases:
                if not phrase_matches[i]:
                    continue
                score += 60 if any(p in compact_body for p in phrases) else 30
            text = normalized(row['content'])
            if grammar_terms:
                # Prefer the definition of the requested category over a subtype
                # or a paragraph that merely mentions that category.
                definitions = sum(bool(re.search(re.escape(t) +
                    r'(?:த்)?(?:த்தொடர்கள்|த்தொடர்|தொடர்கள்|தொடர்)?(?:எனப்படும்|ஆகும்)',
                    compact_body)) for t in grammar_terms)
                score += 40 * definitions
            score += min(5, len(text) / 200)
            if any(w in text for w in ('ஆகும்', 'எனப்படும்', 'என்பது')):
                score += 5
            if any(w in text for w in ('தேர்ந்தெடுக்க', 'DASH', 'டேஷ்', 'பொருத்துக',
                                      'யாவை', 'யாது', 'எழுதுக')):
                score *= 0.2
            if score >= 3:
                ranked.append((score, matched, row))
        ranked.sort(key=lambda r: r[0], reverse=True)
        if not phrases and named_work_query(question) and ranked and len(ranked[0][1]) >= 2:
            section = ranked[0][2].get('section_name')
            if section and not section.startswith('General'):
                # Once the work is identified, keep its verse/author passages together.
                ranked = [r for r in ranked if r[2].get('section_name') == section]
        selected, covered = [], set()
        while ranked and len(selected) < count:
            best = max(range(len(ranked)), key=lambda i: ranked[i][0] +
                       2 * sum(math.log(1 + len(self.rows) / (1 + self.frequency[t]))
                               for t in ranked[i][1] - covered))
            score, matched, row = ranked.pop(best)
            if selected and score < max(3, selected[0][0] * 0.2):
                continue
            selected.append((score, row))
            covered.update(matched)
        return [row for _, row in selected]


def tamil_keyword_passages(database, question, subject, grade):
    if subject not in TAMIL_SUBJECTS:
        return []
    key = (id(database), grade, subject)
    with _LOCK:
        now = time.monotonic()
        cached = _CACHE.get(key)
        if cached and now - cached[0] < CACHE_SECONDS:
            _CACHE.move_to_end(key)
            index = cached[1]
        else:
            rows = []
            for offset in range(0, 20000, 500):
                batch = (database.table('documents')
                         .select('id, content, unit_name, section_name, sub_section_name')
                         .eq('grade_level', grade).eq('subject', subject)
                         .order('id').range(offset, offset + 499).execute().data)
                rows.extend(batch)
                if len(batch) < 500:
                    break
            else:
                raise RuntimeError('Tamil book exceeds index limit')
            index = TamilBookIndex(rows)
            _CACHE[key] = (time.monotonic(), index)
            _CACHE.move_to_end(key)
            while len(_CACHE) > MAX_CACHED_BOOKS:
                _CACHE.popitem(last=False)
    return index.search(question)
