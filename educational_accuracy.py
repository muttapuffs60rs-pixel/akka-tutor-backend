"""Source-first routing and conservative pre-display quotation validation.

No models, credentials, network calls or student-content logging at import time.
Canonical records with unresolved transcription conflicts fail closed.
"""
from dataclasses import dataclass
from functools import lru_cache
from fractions import Fraction
import ast
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).parent / 'curriculum' / 'canonical'
WORK = r'(?:திருக்குறள்|திருகுறள்|குறள்|thiru[kc]+u?ral|thirukural|tirukkural|kural)'
FOLLOW = re.compile(r'^(?:yes|no|explain|more|explain more|explain again|example|give an example|'
                    r'ஆம்|ஆமாம்|இல்லை|சரி|மேலும்|விளக்கு|விளக்குக|எளிமையாக விளக்கு|'
                    r'எளிமையாக விளக்குங்கள்|பொருள்|எடுத்துக்காட்டு|செய்யுள் பகுதி)[.!?\s]*$', re.I)
NUMBERS = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,
           'ஒன்று':1,'இரண்டு':2,'மூன்று':3,'நான்கு':4,'ஐந்து':5,'ஆறு':6,'ஏழு':7,'எட்டு':8,'ஒன்பது':9,'பத்து':10,
           'முதல்':1,'இரண்டாவது':2,'மூன்றாவது':3,'நான்காவது':4,'ஐந்தாவது':5,'ஆறாவது':6,'ஏழாவது':7,'எட்டாவது':8}


def normalize(text):
    return unicodedata.normalize('NFC', text).translate(str.maketrans('௦௧௨௩௪௫௬௭௮௯', '0123456789')).strip()


@lru_cache(maxsize=1)
def corpus():
    data = json.loads((ROOT / 'thirukkural.json').read_text(encoding='utf-8'))
    if [r['number'] for r in data['records']] != list(range(1,1331)) or len(data['chapters']) != 133:
        raise ValueError('Canonical corpus is incomplete')
    for record in data['records']:
        if record['chapter'] != (record['number'] - 1) // 10 + 1 or len(record['lines']) != 2:
            raise ValueError('Invalid canonical chapter or verse structure')
        if record['status'] == 'verified' and any(unicodedata.category(c)[0] in ('L', 'M') and not '\u0b80' <= c <= '\u0bff' for c in ''.join(record['lines'])):
            raise ValueError('Invalid verified Tamil transcription')
    for source in data['sources']:
        if hashlib.sha256((ROOT / source['file']).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Canonical source checksum mismatch')
    return data


def lookup(number):
    record = corpus()['records'][number-1] if 1 <= number <= 1330 else None
    if record and record['status'] == 'verified':
        return record
    return None


def search_canonical(query, limit=4):
    query = normalize(query).lower()
    terms = [t for t in re.findall(r'[\u0b80-\u0bff]+|[a-z]+', query) if len(t) >= 3]
    ranked = []
    for record in corpus()['records']:
        if record['status'] != 'verified':
            continue
        verse = ' '.join(record['lines'])
        score = sum(3*(t in verse) + 5*(t in record['chapter_name']) + (t in record['gloss']) for t in terms)
        if score:
            ranked.append((score, record))
    return [r for _, r in sorted(ranked, key=lambda x:x[0], reverse=True)[:limit]]


def number_in(text):
    text = normalize(text).lower()
    match = re.search(r'(?<!\d)(\d{1,5})(?!\d)', text)
    if match:
        return int(match[1])
    return next((value for word, value in NUMBERS.items()
                 if re.search(r'(?<![\w])'+word+r'(?![\w])', text)), None)


def learning_state(history):
    # Summarize only identifiers from user turns. Never elevate assistant guesses
    # into verified evidence. Caller already isolates board/class/subject.
    state = {'topic':'', 'reference':None, 'scope':'global', 'greeted':bool(history)}
    for item in history[-20:]:
        if item.get('role') != 'user' or not isinstance(item.get('content'), str):
            continue
        text = normalize(item['content'])[:2000]
        if FOLLOW.fullmatch(text):
            continue
        if re.fullmatch(r'\d{1,5}', text) and state['topic'] == 'thirukkural':
            state['reference'] = int(text)
        elif re.search(WORK, text, re.I):
            state['topic'] = 'thirukkural'
            if re.search(r'பாடத்தில்|பாடநூலில்|textbook|selected|ஏழாவது', text, re.I):
                state['scope'] = 'textbook'
            elif re.search(r'அதிகாரம்|chapter', text, re.I):
                state['scope'] = 'chapter'
            else:
                state['scope'] = 'global'
            state['reference'] = number_in(text)
        else:
            state.update(topic=text[:160], reference=None, scope='global')
    return state


@dataclass
class Decision:
    kind: str
    query: str
    answer: str = ''
    evidence: str = ''
    record: dict | None = None


def textbook_request(text):
    return bool(re.search(r'\b(page|lesson|exercise|chapter)\s*(?:number\s*)?\d|'
                          r'\b(?:third|seventh) (?:poem|couplet)|'
                          r'பக்கம்|பாடப்பகுதி|பாடம்\s*\d|தேர்ந்தெடுக்கப்பட்ட|'
                          r'^(?:explain|read) (?:my |the )?textbook (?:lesson|passage)[.!? ]*$', text, re.I))


def missing_textbook(tamil):
    return ('உங்கள் பாடநூலின் குறிப்பிட்ட பாடப்பகுதியை இன்னும் சரிபார்க்க முடியவில்லை. '
            'அந்தப் பக்கத்தின் படத்தை அல்லது முழுக் கேள்வியை அனுப்புங்கள். '
            'அதுவரை பொதுவான கருத்தை விளக்க முடியும்.' if tamil else
            'I could not verify that specific textbook passage. Please share the page image or the full question. '
            'I can still explain the general concept.')


def canonical_answer(record, tamil=True):
    quote = '\n'.join(record['lines'])
    gloss = record.get('gloss', '').strip()
    source_name = 'Tamil Virtual Academy' if 'tamilvu.org/' in record['source'] else 'Project Madurai'
    if tamil:
        # Commentary is a historical source, never represented as a modern
        # teacher-reviewed gloss or the student's textbook selection.
        return (f"**குறள் {record['number']} — {record['chapter_name']}**\n\n{quote}\n\n"
                + (f"**பொருள் (பரிமேலழகர் உரை):**\n{gloss}\n\n" if gloss else
                   'இந்தக் குறளுக்கான பொருள் விளக்கம் இன்னும் சரிபார்க்கப்படவில்லை.\n\n') +
                f"[மூலம்: {source_name}]({record['source']})\n\n"
                'இது திருக்குறளின் பொதுவான எண்; உங்கள் பாடநூலில் தேர்ந்தெடுக்கப்பட்ட வரிசை அல்ல. '
                'இந்த உரைக்கான வயதுக்கேற்ற எளிய விளக்கம் இன்னும் சரிபார்க்கப்படவில்லை.')
    return (f"**Thirukkural {record['number']} — {record['chapter_name']}**\n\n{quote}\n\n"
            + (f"Tamil commentary (Parimelazhagar): {gloss}\n\n" if gloss else
               'The verse is verified; its explanation has not yet been verified.\n\n') +
            f"[Source: {source_name}]({record['source']})\n\n"
            'This is the global couplet number. A reviewed simple or English explanation is not available yet.')


def _legacy_topic_route(question, history, subject, language=None):
    text = normalize(question)
    state = learning_state(history)
    tamil = language == 'ta' or (language is None and subject in ('Tamil','Advance Tamil','Advanced Tamil'))
    follow = bool(FOLLOW.fullmatch(text))
    work = bool(re.search(WORK, text, re.I)) or ((follow or re.fullmatch(r'\d{1,5}', text) or
           re.search(r'அதிகாரம்|chapter',text,re.I)) and state['topic']=='thirukkural')
    query = text
    try:
        facts = json.loads((ROOT / 'facts.json').read_text(encoding='utf-8'))['records']
    except (OSError, ValueError, KeyError):
        facts = []
    for fact in facts:
        if fact['status']=='verified' and re.fullmatch(fact['pattern'],text,re.I):
            return Decision('canonical',query,answer=fact['answer_ta' if tamil else 'answer_en']+
                            f"\n\n[Source: {fact['source_title']}]({fact['source']})")
    if follow and state['topic']:
        anchor = (f"திருக்குறள் குறள் {state['reference']}" if state['reference'] else 'திருக்குறள்') if state['topic']=='thirukkural' else state['topic']
        query = f'{anchor} {text}'
    if textbook_request(text) or (work and follow and state['scope']=='textbook'):
        return Decision('textbook', query, answer=missing_textbook(tamil))
    if not work and re.search(r'\b(?:quote|quotation|exact verse)\b|சரியான செய்யுள்|முழுப் பாடல்',text,re.I):
        return Decision('quotation',query,answer=missing_textbook(tamil))
    if not work:
        return Decision('concept', query)
    number = number_in(text)
    if number is None and follow:
        number = state['reference']
    chapter = bool(re.search(r'அதிகாரம்|chapter', text, re.I)) or (follow and state['scope']=='chapter')
    if chapter:
        if number is None:
            return Decision('clarification',query,answer='எந்த அதிகாரத்தின் எண் அல்லது பெயர் வேண்டும்?' if tamil else 'Which chapter number or name?')
        if not 1 <= number <= 133:
            return Decision('clarification',query,answer='திருக்குறளில் 1 முதல் 133 வரை அதிகாரங்கள் உள்ளன.' if tamil else 'Thirukkural chapters are numbered 1–133.')
        try:
            name = corpus()['chapters'][number-1]
            return Decision('canonical',query,answer=f"**அதிகாரம் {number}: {name}**\nகுறள்கள் {(number-1)*10+1}–{number*10}.\nஇது பொதுவான அதிகார எண்; பாடநூல் பாட எண் அல்ல.")
        except (OSError, ValueError, KeyError):
            return Decision('unavailable',query,answer='The verified canonical source is temporarily unavailable.')
    if number is not None:
        try:
            record = lookup(number)
        except (OSError, ValueError, KeyError):
            record = None
        if not record:
            return Decision('unavailable',query,answer=('இந்தக் குறளின் சரியான உரையை இப்போது உறுதிப்படுத்த முடியவில்லை. '
                'உறுதிப்படுத்தாத செய்யுளை வழங்க மாட்டேன். குறள் எண்ணைச் சரிபார்க்கவும் அல்லது நூலின் படத்தை அனுப்பவும்.' if tamil else
                'I cannot verify that numbered couplet right now. Please check the number or share a source image.'))
        if follow and text.lower() in ('no','இல்லை'):
            return Decision('canonical',query,answer='சரி. வேறு கேள்வியைச் சொல்லுங்கள்.' if tamil else 'Okay. Share your next question.')
        if follow:
            return Decision('explanation',query,evidence=json.dumps(record,ensure_ascii=False),record=record)
        return Decision('canonical',query,answer=canonical_answer(record,tamil),record=record)
    # A topic introduction is useful even without a particular school textbook.
    if follow:
        if text.lower() in ('no','இல்லை'):
            return Decision('canonical',query,answer='சரி. வேறு எந்தக் கருத்தை அறிய விரும்புகிறீர்கள்?' if tamil else 'Okay. Share the topic you would like to learn next.')
        if 'செய்யுள்' in text:
            return Decision('canonical',query,answer='குறள் என்பது இரண்டு அடிகளைக் கொண்ட செய்யுள் வடிவம். திருக்குறளின் பொதுவான எண்ணைக் கூறினால் அதன் உரையைப் பார்க்கலாம். பாடநூலில் தேர்ந்தெடுக்கப்பட்ட குறளைப் பார்க்க அந்தப் பக்கத்தை அனுப்பலாம்.' if tamil else
                'A kural is a two-line verse. A global couplet number identifies its canonical text; a textbook selection needs the matching page.')
        return Decision('canonical',query,answer='ஒவ்வொரு அதிகாரத்திலும் 10 குறள்கள் உள்ளன. குறள்கள் நல்லொழுக்கம், கல்வி, நட்பு போன்ற வாழ்க்கைக் கருத்துகளைச் சுருக்கமாகக் கூறுகின்றன.' if tamil else
            'Each chapter contains ten couplets. They express ideas about conduct, learning, friendship and other aspects of life in two lines.')
    if re.fullmatch(WORK+r'(?:\s*(?:meaning|என்றால் என்ன|என்ன))?[?.!\s]*',text,re.I):
        return Decision('canonical',query,answer=('திருக்குறள் என்பது திருவள்ளுவர் இயற்றிய அறநூல். இதில் 133 அதிகாரங்களும் 1330 குறள்களும் உள்ளன. '
            'அறம், பொருள், இன்பம் ஆகிய மூன்று பகுதிகளில் வாழ்க்கைக்கு உதவும் கருத்துகள் கூறப்படுகின்றன.\n\n'
            'ஒரு குறிப்பிட்ட குறளின் எண்ணைக் கூறினால் அதன் பொருளைப் பார்க்கலாம்.' if tamil else
            'Thirukkural, by Thiruvalluvar, contains 1,330 couplets in 133 chapters, grouped into virtue, wealth and love. '
            'Share a couplet number to explore its meaning.'))
    try:
        records = search_canonical(text)
    except (OSError, ValueError, KeyError):
        records = []
    return Decision('literature',query,evidence=json.dumps(records,ensure_ascii=False) if records else '')


def attribution_claim_errors(answer, evidence):
    if re.search(r'https?://[^\s)\]]+|\[cite[^\]]*\]', answer):
        # Citations are added by the server, never by generation.
        return ['attribution:generated_citation']
    if re.search(r'(?:according to|as stated in)\s+(?:your |the )?(?:textbook|chapter)|பாடநூலில்|பக்கம்\s*\d+|page\s*\d+', answer, re.I):
        return ['attribution:unverified_page_or_textbook']
    if not evidence and re.search(r'பாடநூலில்|பாடத்தில் உள்ளது|பாடத்தில் இல்லை|your textbook|according to .*textbook|குறள்:\s*\n', answer, re.I):
        return ['attribution:missing_source']
    return []


def curriculum_claim_errors(answer, record=None, sources=()):
    from reference_resolution import source_scope
    for chapter in re.findall(r'\bchapter\s+(\d+)\b', answer, re.I):
        if not sources or chapter not in {str(s['chapter_number']) for s in sources}:
            return ['curriculum:chapter_not_supported']
    scope = source_scope(answer)
    for key, value in scope.items():
        if not sources or value not in {s.get(key) for s in sources}:
            return ['curriculum:edition_or_term_not_supported']
    if record:
        # Explanation-only generation: the server already delivered the verse.
        if re.search(r'குறள்\s*\d+', answer) and re.search(r'குறள்\s*(\d+)', answer)[1] != str(record['number']):
            return ['curriculum:canonical_identity_conflict']
        if re.search(r'பாடநூலில்|உங்கள் பாடம்|your textbook|page\s*\d', answer, re.I):
            return ['curriculum:canonical_is_not_textbook_selection']
    return []


def quotation_claim_errors(answer, evidence, record=None, question=''):
    # Literary/source quotation claims remain exact. Emphasis, ordinary words,
    # worked mathematics and explicitly generated examples are not quotations.
    literary = bool(record or re.search(r'poem|verse|couplet|குறள்|செய்யுள்|பாடல|இன்பத்தமிழ்', question, re.I))
    explicit_quote = bool(re.search(r'quot(?:e|ation)|verbatim|exact words|கவிஞர் கூற|எழுதிய வரி|மேற்கோள்|(?:textbook|poem|verse) (?:says|reads)', answer, re.I))
    standalone_quote = not question and bool(re.fullmatch(r'\s*[“"].+[”"]\s*[.!]?\s*', answer, re.S))
    if literary or explicit_quote or standalone_quote:
        quotes = re.findall(r'[“"]([^”"]{4,})[”"]', answer)
        quotes += re.findall(r"(?<!\w)[‘']([^’'\n]{4,})[’'](?!\w)", answer)
        quotes += re.findall(r'^>\s*(.+)$', answer, re.M)
        for quoted in quotes:
            if ' '.join(normalize(quoted).split()) not in ' '.join(normalize(evidence).split()):
                return ['quotation:not_in_source']
    return []


def reply_errors(answer, evidence, record=None, question='', subject='', sources=()):
    """Independent diagnostics for the existing pre-display gate; not a proof."""
    from source_answers import factual_claim_errors, mathematical_claim_errors
    return (factual_claim_errors(answer, question) + mathematical_claim_errors(answer, question) +
            curriculum_claim_errors(answer, record, sources) + attribution_claim_errors(answer, evidence) +
            quotation_claim_errors(answer, evidence, record, question))


def validate_reply(answer, evidence, record=None, question='', subject='', sources=()):
    return not reply_errors(answer, evidence, record, question, subject, sources)


def arithmetic_answer(question):
    """Small exact rational arithmetic, without eval or exponent/resource hazards."""
    match = re.fullmatch(r'(?:calculate|what is|compute|கணக்கிடு)?\s*([\d\s()+*/.−-]{3,100})\s*[=?]?', question.strip(), re.I)
    if not match or not re.search(r'[+*/−-]',match[1]):
        return None
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float) and abs(node.value)<10**12:
            return Fraction(ast.get_source_segment(expression, node))
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            return visit(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
            a,b=visit(node.left),visit(node.right)
            return {ast.Add:lambda:a+b,ast.Sub:lambda:a-b,ast.Mult:lambda:a*b,ast.Div:lambda:a/b}[type(node.op)]()
        raise ValueError('Unsupported arithmetic')
    try:
        expression = match[1].replace('−','-').strip()
        value=visit(ast.parse(expression,mode='eval').body)
        return f"{match[1].strip()} = **{value}**"
    except (ValueError,SyntaxError,ZeroDivisionError):
        return None


def route_question(question, history, subject, language=None, active_context=None):
    """Resolve number semantics before deterministic lookup; never guess the scope."""
    from reference_resolution import resolve_reference, clarification, source_scope
    ref = resolve_reference(question, history, active_context)
    tamil = language == 'ta' or (language is None and subject in ('Tamil', 'Advance Tamil', 'Advanced Tamil'))
    if question.strip().lower().rstrip('.!?') in ('no', 'இல்லை') and ref.number:
        return Decision('clarification', question, answer='சரி. உங்கள் அடுத்த கேள்வியைச் சொல்லுங்கள்.' if tamil else 'Okay. Share your next question.')
    if not ref.number and source_scope(question) and ref.scope == 'textbook':
        return Decision('clarification', question, answer=(
            'அந்தப் பதிப்பில் எந்தப் பக்கம், பாடம் அல்லது செய்யுள் வரிசை வேண்டும்?' if tamil else
            'Which page, lesson or selection in that edition would you like to study?'))
    if ref.number is not None:
        if ref.ambiguous:
            return Decision('clarification', question, answer=clarification(ref, tamil))
        if ref.scope == 'textbook':
            answer = missing_textbook(tamil)
            if ref.kind == 'question_number' and not any(k in ref.qualifiers for k in ('chapter_number','exercise_number','page_number')):
                answer = (f'கேள்வி {ref.number} எந்தப் பாடம் அல்லது பயிற்சியில் உள்ளது? முழுக் கேள்வியை அல்லது பக்கப் படத்தை அனுப்புங்கள்.' if tamil else
                          f'Which chapter and exercise contains question {ref.number}? Please share the full question or page image.')
            return Decision('textbook', question, answer=answer, record={'reference': ref})
        if ref.work == 'thirukkural' and ref.kind == 'canonical_reference_number':
            try:
                record = lookup(int(ref.number))
            except (OSError, ValueError, KeyError, TypeError):
                record = None
            if not record:
                return Decision('unavailable', question, answer=missing_textbook(tamil))
            # Do not let an unreviewed paraphrase replace the historical meaning.
            return Decision('canonical', question, answer=canonical_answer(record, tamil), record=record)
        if ref.kind == 'chapter_number' and ref.scope == 'canonical':
            return _legacy_topic_route('திருக்குறள் அதிகாரம் ' + ref.number, [], subject, language)
    decision = _legacy_topic_route(question, history, subject, language)
    # Legacy topic assistance may still propose a numbered record from incomplete
    # context. Only the resolver above can authorise that exact identity.
    if decision.record:
        return Decision('clarification', question, answer=clarification(ref, tamil))
    if decision.kind == 'literature':
        # Search similarity is not proof that the intended verse was resolved,
        # nor that a newly generated interpretation preserves its meaning.
        return Decision('clarification', question, answer=(
            'எந்தக் குறளின் பொருள் வேண்டும்? மூலக் குறள் எண்ணை அல்லது பாடநூல் பக்கத்தைத் தெரிவியுங்கள்.' if tamil else
            'Which couplet do you mean? Please specify the original number or the textbook page.'))
    return decision
