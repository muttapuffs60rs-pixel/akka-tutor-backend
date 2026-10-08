"""Supplement semantic retrieval with scoped Tamil terminology matches."""
import re
import unicodedata


def tamil_terms(question):
    words = re.findall(r'[\u0b80-\u0bff]+', unicodedata.normalize('NFC', question))
    ignored = {'பத்தாம்', 'வகுப்பு', 'தமிழ்', 'தமிழில்', 'பதில்', 'அளிக்கவும்',
               'என்றால்', 'என்ன', 'மற்றும்', 'ஆகியவற்றை', 'ஒவ்வோர்',
               'எடுத்துக்காட்டுடன்', 'விளக்குக', 'தொடர்'}
    terms = []
    for word in words:
        if word in ignored or len(word) < 5:
            continue
        # Tamil textbook extraction varies between joined and spaced compounds.
        word = re.sub(r'த்தொடர்.*$', '', word)
        word = re.sub(r'த்$', '', word)
        if len(word) >= 4 and word not in terms:
            terms.append(word)
    return terms[:6]


def normalized(text):
    return re.sub(r'\s+', ' ', text.replace('\u200c', '').replace('\u200d', '')).strip()


def tamil_keyword_passages(database, question, subject, grade):
    if subject != 'Tamil':
        return []
    selected = []
    for term in tamil_terms(question):
        rows = (database.table('documents')
                .select('content, unit_name, section_name, sub_section_name')
                .eq('grade_level', grade).eq('subject', subject)
                .or_(f'content.ilike.%{term}%,section_name.ilike.%{term}%')
                .limit(80).execute().data)
        def score(row):
            content = normalized(row.get('content', ''))
            if len(content) < 65 or '<v:' in content or 'o:spid' in content:
                return -1
            return (4 * (term in content)
                    + 3 * any(w in content for w in ('ஆகும்', 'எனப்படும்', 'என்பது'))
                    + ('எடுத்துகாட்டு' in content or 'எடுத்துக்காட்டு' in content)
                    - 3 * ('DASH' in content or 'விடை' in content))
        for row in sorted(rows, key=score, reverse=True)[:2]:
            content = normalized(row.get('content', ''))
            if score(row) >= 5 and content not in [r['content'] for r in selected]:
                selected.append({**row, 'content': content})
    return selected
