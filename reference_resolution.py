"""Resolve reference identity before looking up content, across all subjects.

History supplies intent only. A source ID/lesson/section is authoritative only
after the evidence repository has checked it against the selected curriculum.
"""
from dataclasses import dataclass, field
import re
import unicodedata

WORK = r'(?:திருக்குறள்|திருகுறள்|குறள்|thirukkural|thirukural|tirukkural|kural)'
FOLLOW = re.compile(r'^(?:yes|no|why|explain|more|explain more|explain again|example|give an example|'
    r'ஆம்|ஆமாம்|இல்லை|சரி|மேலும்|விளக்கு|விளக்குக|எளிமையாக(?: விளக்கு| விளக்குங்கள்| சொல்லு)?|'
    r'பொருள்|எடுத்துக்காட்டு|உதாரணம்|இன்னொரு உதாரணம்|அடுத்து)[.!?\s]*$',re.I)
WORDS = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,
    'first':1,'second':2,'third':3,'fourth':4,'fifth':5,'sixth':6,'seventh':7,'eighth':8,
    'ஒன்று':1,'இரண்டு':2,'மூன்று':3,'நான்கு':4,'ஐந்து':5,'ஆறு':6,'ஏழு':7,'எட்டு':8,'ஒன்பது':9,'பத்து':10,
    'முதல்':1,'இரண்டாவது':2,'மூன்றாவது':3,'நான்காவது':4,'ஐந்தாவது':5,'ஆறாவது':6,'ஏழாவது':7,'எட்டாவது':8}
KINDS = {'page_number':r'page|பக்கம்', 'exercise_number':r'exercise|பயிற்சி',
    'question_number':r'question|வினா|கேள்வி', 'lesson_number':r'lesson|பாடம்',
    'chapter_number':r'chapter|அதிகாரம்|அத்தியாயம்'}
TEXTBOOK = r'textbook|my book|பாடநூ|பாடத்தில்|பாடப்பகுதி|செய்யுள் பகுதி|தேர்ந்தெடுக்கப்பட்ட|selected'
CANONICAL = r'canonical|global|original|மூல(?:த்|ம்)?|பொதுவான எண்'

def source_scope(text):
    """Explicit source selectors, never inferred from today's year."""
    result = {}
    year = re.search(r'\b(20\d{2})\s*[-–/]\s*(\d{2}|20\d{2})\b', text)
    if year:
        result['academic_year'] = year[1] + '-' + year[2][-2:]
    edition = re.search(r'(?:edition|reprint|பதிப்பு)\s*[: -]?\s*(20\d{2})|(20\d{2})\s*(?:edition|reprint|பதிப்பு)', text, re.I)
    if edition:
        result['edition'] = edition[1] or edition[2]
    term = re.search(r'(?:term|பருவம்)\s*[-:]?\s*(III|II|I|[123])\b', text, re.I)
    if term:
        result['term'] = 'Term-' + {'1':'I', '2':'II', '3':'III'}.get(term[1].upper(), term[1].upper())
    return result


def normalized(text):
    return unicodedata.normalize('NFC',str(text)).translate(str.maketrans('௦௧௨௩௪௫௬௭௮௯','0123456789')).strip()


def number(text):
    text=normalized(text).lower()
    match=re.search(r'(?<![\d.])(\d+(?:\.\d+)*)(?![\d.])',text)
    if match:
        return match[1]
    return next((str(n) for word,n in WORDS.items() if re.search(r'(?<!\w)'+word+r'(?!\w)',text)),None)


@dataclass
class Reference:
    kind: str | None = None
    number: str | None = None
    scope: str = 'unknown'
    work: str | None = None
    qualifiers: dict = field(default_factory=dict)
    ambiguous: bool = False


def resolve_reference(question, history=(), active_context=None):
    """No content lookup or model call occurs until this returns an identity.

    active_context must come from a verified repository result, never directly
    from a client payload. Textbook scope survives repeated topic names.
    """
    context=active_context or {}
    stored = context.get('reference') if context.get('verified') else None
    state=Reference(**stored) if isinstance(stored, dict) else Reference(
        scope='textbook' if context.get('verified') else 'unknown', work=context.get('canonical_work'))
    previous_topic=''
    turns=[m['content'] for m in history[-20:] if m.get('role')=='user' and isinstance(m.get('content'),str)]
    for raw in turns+[question]:
        text=normalized(raw)
        follow=bool(FOLLOW.fullmatch(text))
        has_work=bool(re.search(WORK,text,re.I))
        explicit_canonical=bool(re.search(CANONICAL,text,re.I))
        explicit_book=bool(re.search(TEXTBOOK,text,re.I))
        selectors = source_scope(text)
        found={}
        for kind,words in KINDS.items():
            match=re.search(r'(?:'+words+r')\s*(?:number|no\.?|எண்)?\s*(\d+(?:\.\d+)*)',text,re.I)
            if match:
                found[kind]=match[1]
        # Parent qualifiers remain distinct (exercise 1.2, question 7).
        if found:
            primary=next(k for k in ('question_number','exercise_number','page_number','lesson_number','chapter_number') if k in found)
            # Changing a parent replaces its children; never carry exercise 1.2
            # into a new page or chapter simply because it appeared earlier.
            parents = {'question_number': ('chapter_number','lesson_number','exercise_number'),
                       'exercise_number': ('chapter_number','lesson_number'),
                       'lesson_number': ('chapter_number',)}.get(primary, ())
            if state.kind in parents and state.number:
                state.qualifiers[state.kind] = state.number
            state.qualifiers = {k:v for k,v in state.qualifiers.items()
                                if k in parents or k in ('edition','academic_year','term')}
            state.kind,state.number=primary,found[primary]
            state.qualifiers.update({k:v for k,v in found.items() if k!=primary})
            state.scope='canonical' if (primary=='chapter_number' and explicit_canonical and (has_work or state.work=='thirukkural')) else 'textbook'
        if explicit_book:
            state.scope='textbook'
            if state.work=='thirukkural' and state.number and not found:
                state.kind='textbook_sequence_number'
        if explicit_canonical:
            state.scope='canonical'
            if state.work=='thirukkural' and state.number and not found:
                state.kind='canonical_reference_number'
        if has_work:
            state.work='thirukkural'
            work_match = re.search(WORK, text, re.I)
            work_number = number(text[work_match.end():])
            if work_number is not None and not found:
                state.kind='canonical_reference_number' if state.scope=='canonical' else 'textbook_sequence_number' if state.scope=='textbook' else None
                state.number=work_number
            elif previous_topic and previous_topic!='thirukkural' and not explicit_book:
                state=Reference(scope='canonical' if explicit_canonical else 'textbook' if state.scope=='textbook' else 'unknown',
                    work='thirukkural', qualifiers={k:v for k,v in state.qualifiers.items() if k in ('edition','academic_year','term')})
            previous_topic='thirukkural'
        elif re.fullmatch(r'\d+(?:\.\d+)*[?.! ]*',text):
            state.number=number(text)
        elif explicit_canonical and state.work=='thirukkural' and state.number:
            state.kind='canonical_reference_number'
        elif explicit_book and state.work=='thirukkural' and state.number:
            state.kind='textbook_sequence_number'
        elif follow:
            if text=='அடுத்து' and state.number and state.number.isdigit():
                state.number=str(int(state.number)+1)
        elif not found and not explicit_book and not explicit_canonical and not selectors:
            # A substantive new topic clears numeric intent, but never fabricates
            # a textbook identifier from ordinary conversation text.
            # A new topic/section clears the old item, but an established request
            # to study the textbook still cannot become canonical numbering.
            state=Reference(scope='textbook' if state.scope=='textbook' else 'unknown',
                            qualifiers={k:v for k,v in state.qualifiers.items() if k in ('edition','academic_year','term')})
            previous_topic=text[:160]
        if selectors:
            if 'edition' in selectors:
                state.qualifiers.pop('academic_year', None)
            if 'academic_year' in selectors:
                state.qualifiers.pop('edition', None)
            state.qualifiers.update(selectors)
        if state.work=='thirukkural' and state.number and state.kind is None:
            state.kind='canonical_reference_number' if state.scope=='canonical' else 'textbook_sequence_number' if state.scope=='textbook' else None
    state.ambiguous=state.number is not None and state.kind is None
    return state


def clarification(reference, tamil=False):
    if reference.work=='thirukkural':
        return (f'“{reference.number}” என்பது உங்கள் பாடநூலின் வரிசை எண்ணா, அல்லது மூலத் திருக்குறள் எண்ணா?' if tamil else
                f'Does {reference.number} mean the textbook selection number or the original Thirukkural number?')
    return ('இந்த எண் பக்கம், பாடம், பயிற்சி அல்லது வினா—எதைக் குறிக்கிறது?' if tamil else
            'Does this number refer to a page, lesson, exercise or question?')
