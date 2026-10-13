"""Shared controlled teaching for reviewed sources in any school subject.

Exact numbered passages retain their curated meaning-preservation baseline.
General teaching uses independent, bounded fact and arithmetic checks; it need
not repeat source wording. Neither path proves arbitrary generated prose.
"""
import re
import unicodedata
from urllib.parse import urlparse


def normalized(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def meaning_preserved(answer, record):
    if record.get('meaning_status') != 'verified':
        return False
    approved = [record.get('source_meaning', ''), record.get('simplified_meaning', '')]
    return bool(answer.strip()) and normalized(answer) in {
        normalized(value) for value in approved if value
    }


def factual_claim_errors(answer, question=''):
    """Independent bounded checks. Absence of an error is not semantic proof.

    These cover the reviewed pilot's critical claims, not arbitrary prose.
    Preserve original output; normalization here is only for matching.
    """
    errors = []
    text = unicodedata.normalize('NFC', answer).translate(str.maketrans('௦௧௨௩௪௫௬௭௮௯₂₃', '012345678923'))
    text = re.sub(r'[*_`“”"‘’]', '', text).replace('–', '-').replace('−', '-')
    words = {'ஐந்து':'5', 'ஏழு':'7', 'பன்னிரண்டு':'12', 'பனிரெண்டு':'12', 'பன்னிரெண்டு':'12',
             'five':'5', 'seven':'7', 'twelve':'12'}
    for word, number in words.items():
        text = re.sub(r'(?<!\w)' + word + r'(?!\w)', number, text, flags=re.I)
    categories = [(r'குறில்(?:கள்)?|short vowels?', 5, set('அ இ உ எ ஒ'.split())),
                  (r'நெடில்(?:கள்)?|long vowels?', 7, set('ஆ ஈ ஊ ஏ ஐ ஓ ஔ'.split())),
                  (r'உயிர்\s*எழுத்து(?:கள்|களின்)?|Tamil vowels?', 12, None)]
    for category, expected, letters in categories:
        for match in re.finditer(r'(?:' + category + r')', text, re.I):
            tail = re.split(r'[.!;]|குறில்|நெடில்', text[match.end():], maxsplit=1)[0][:140]
            count = re.match(r'[\s:—–\-|()=]*(?:(?:எண்ணிக்கை|மொத்தம்|ஆகியவை|எழுத்துகள்|எழுத்துக்கள்|are|count|number|is|total)\s*[:=—-]?\s*)*(\d+)(?!\d)', tail, re.I)
            if count and int(count[1]) != expected:
                errors.append('fact:vowel_count')
            before = text[max(0, match.start()-25):match.start()]
            count_before = re.search(r'(\d+)\s*$', before)
            if count_before and int(count_before[1]) != expected:
                errors.append('fact:vowel_count')
            if letters:
                listed = set(re.findall(r'(?<![\u0b80-\u0bff])[அஆஇஈஉஊஎஏஐஒஓஔ](?![\u0b80-\u0bff])', tail))
                if listed - letters:
                    errors.append('fact:vowel_classification')
    if re.search(r'(?:water(?:\x27s)?(?: chemical)? formula (?:is|=)|water is|formula for water is)\s*H2O2\b', text, re.I):
        errors.append('fact:water_formula')
    if re.search(r'(?:water|H2O)[^\n.!]{0,70}(?:two|2) oxygen', text, re.I):
        errors.append('fact:water_composition')
    if re.search(r'H\s*\+\s*O\s*\+\s*H\s*(?:→|->|=)\s*H2O', text) and not re.search(r'composition|not a reaction|atom arrangement', text, re.I):
        errors.append('fact:composition_not_reaction')
    if re.search(r'(?:sodium|Na)[^\n.!]{0,75}(?:gains?|receives?) (?:an?|one|1) electron[^\n.!]{0,60}(?:positive|Na\+)', text, re.I):
        errors.append('fact:sodium_electron_loss')
    if re.search(r'(?:sodium|Na)[^\n.!]{0,50}loses? (?:two|three|[2-9]) electrons?', text, re.I):
        errors.append('fact:sodium_electron_count')
    if re.search(r'இன்பத்?\s*தமிழ்|இன்பத்தமிழ்|inbathamil', question, re.I):
        if re.search(r'(?:எழுதியவர்|இயற்றியவர்|ஆசிரியர்)\s*[:—-]?\s*(?:பாரதியார்|திருவள்ளுவர்)|author is (?:Bharathiyar|Thiruvalluvar)', text, re.I):
            errors.append('fact:inbathamil_author')
    if re.search(r'average speed[^\n.!]{0,70}(?:never|is not|isn\x27t|always)[^\n.!]{0,35}(?:average|mean) of (?:the )?(?:separate )?speeds', text, re.I):
        if not re.search(r'not generally|not always|equal (?:time|duration)|same (?:time|duration)', text, re.I):
            errors.append('fact:speed_mean_qualification')
    formula = re.search(r"water(?:'s)?\s+(?:chemical\s+)?formula\s+is\s+\*{0,2}([A-Za-z0-9₂₃]+)", answer, re.I)
    if formula and formula[1].translate(str.maketrans('₂₃', '23')).upper() != 'H2O':
        errors.append('fact:water_formula')
    return list(dict.fromkeys(errors))


def mathematical_claim_errors(answer, question=''):
    from educational_accuracy import arithmetic_answer
    from fractions import Fraction
    errors = []
    text = answer.replace('**', '').replace('`', '').replace('–', '-').replace('−', '-')
    # Simple single-distance/single-time problems only; no inference for a
    # multileg journey. Convert supported units before checking final speeds.
    if re.search(r'average speed|speed', question, re.I):
        distances = re.findall(r'(\d+(?:\.\d+)?)\s*(km|metres?|meters?|m)\b', question, re.I)
        times = re.findall(r'(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|hours?|hrs?|h)\b', question, re.I)
        if len(distances) == len(times) == 1:
            d, du = distances[0]; t, tu = times[0]
            seconds = Fraction(t) * (3600 if tu.lower().startswith(('h','hour')) else 60 if tu.lower().startswith('min') else 1)
            if seconds:
                expected = Fraction(d) * (1000 if du.lower() == 'km' else 1) / seconds
                for value, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(km/h|m/s(?:\^?2|²)?|m\s+s-1|met(?:re|er)s? per second)', text, re.I):
                    actual = Fraction(value) * (Fraction(5,18) if unit.lower() == 'km/h' else 1)
                    if unit.endswith(('2','²')) or abs(float(actual-expected)) > max(0.005, abs(float(expected))*0.001):
                        errors.append('math:speed_value_or_unit')


    math_text = text.replace('÷', '/').replace('×', '*')
    for expression, result in re.findall(
            r'(?<![\w.])([0-9]+(?:\s*[+*/-]\s*[0-9]+)+)\s*=\s*(-?\d+(?:/\d+|\.\d+)?)(?![\w.])', math_text):
        calculated = arithmetic_answer(expression)
        if calculated:
            try:
                expected = calculated.split('**')[1]
                if Fraction(expected) != Fraction(result):
                    errors.append('math:equality')
            except (ValueError, ZeroDivisionError):
                errors.append('math:equality')
    return list(dict.fromkeys(errors))


def claim_errors(answer, question=''):
    return factual_claim_errors(answer, question) + mathematical_claim_errors(answer, question)


def validate_subject_facts(answer, question=''):
    """Compatibility entry point; independent fact and arithmetic checks."""
    return not claim_errors(answer, question)


def render_source_answer(record, question, tamil=False):
    if record.get('verification_status') != 'verified':
        raise ValueError('Unverified source')
    source = record.get('source_url', '')
    if urlparse(source).scheme != 'https' or not urlparse(source).netloc or re.search(r'[\s()<>]', source):
        raise ValueError('Invalid source URL')
    title = record['source_title'].replace('[', '').replace(']', '')
    parts = [('**சரிபார்க்கப்பட்ட மூலப் பகுதி:**' if tamil else '**Verified source passage:**'), record['content']]
    if record.get('canonical_reference'):
        parts.append(('மூல எண்: ' if tamil else 'Canonical reference: ') + str(record['canonical_reference']))
    if record.get('selection_ordinal') is not None:
        parts.append(('பாடநூல் வரிசை எண்: ' if tamil else 'Textbook selection: ') + str(record['selection_ordinal']))
    if record.get('meaning_status') == 'verified' and record.get('source_meaning'):
        parts.extend(['**மூல விளக்கம்:**' if tamil else '**Source explanation:**', record['source_meaning']])
        if record.get('simplified_meaning'):
            parts.extend(['**எளிய விளக்கம் (சரிபார்க்கப்பட்டது):**' if tamil else '**Reviewed simple explanation:**', record['simplified_meaning']])
        if re.search(r'example|உதாரணம்|எடுத்துக்காட்டு', question, re.I):
            example = record.get('reviewed_example')
            parts.append(('**கற்றலுக்கான எடுத்துக்காட்டு:**\n' if tamil else '**Teaching example (not source text):**\n') + example if example else
                         ('இந்தப் பகுதிக்கான சரிபார்க்கப்பட்ட எடுத்துக்காட்டு இன்னும் இல்லை.' if tamil else 'A reviewed example for this passage is not available yet.'))
    else:
        parts.append('இந்தப் பகுதியின் விளக்கம் இன்னும் சரிபார்க்கப்படவில்லை; பொருளை ஊகிக்க மாட்டேன்.' if tamil else
                     'A verified explanation is not available for this passage; I will not invent its meaning.')
    parts.append(f'[Source: {title}]({source})')
    parts.append(('பதிப்பு: ' if tamil else 'Edition: ') + str(record['edition']))
    if record.get('term'):
        parts.append(('பருவம் / தொகுதி: ' if tamil else 'Term / volume: ') + record['term'])
    if record.get('page_number'):
        parts.append(('அச்சுப் பக்கம்: ' if tamil else 'Printed page: ') + str(record['page_number']))
    if record.get('academic_year_note'):
        parts.append('இந்த ஆதாரம் 2024 மறுபதிப்பைச் சேர்ந்தது; 2026–27 கல்வியாண்டுக்குப் பொருந்துவது இன்னும் உறுதிப்படுத்தப்படவில்லை.' if tamil else record['academic_year_note'])
    return '\n\n'.join(parts)
