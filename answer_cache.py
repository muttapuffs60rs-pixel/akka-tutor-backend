"""Exact, versioned answer reuse. Unreviewed generations are never served."""
import hashlib
import json
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)
GREETING = 'Vanakkam! Iniku enna padikalam? 😊'


def normalize_question(value):
    # Keep line breaks: flattening equations or matrices can change their meaning.
    value = unicodedata.normalize('NFC', value).replace('\r\n', '\n').replace('\r', '\n')
    return '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in value.strip().split('\n'))


def eligible_question(question, history, image_url, turns_used):
    if image_url or turns_used != 1:
        return False
    if any(item.get('role') != 'assistant' or item.get('content') != GREETING for item in history):
        return False
    if not 12 <= len(question) <= 2000:
        return False
    # Conservative screening, not a privacy guarantee. Human review is mandatory.
    if re.search(r'@|https?://|\b\d{7,}\b|\b(my|mine|me|our|previous|above|again|this|that|it|these|those)\b', question, re.I):
        return False
    return True


class AnswerCache:
    def __init__(self, database, syllabus_version, prompt):
        self.db = database
        self.version = syllabus_version.strip()
        self.prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    def identity(self, question, subject, grade, context):
        if not self.version or not context or context == 'No specific textbook context found.':
            return None
        fields = {
            'question': normalize_question(question), 'subject': subject.strip(),
            'grade_level': grade, 'board': 'Tamil Nadu State Board', 'language': 'Tanglish',
            'syllabus_version': self.version, 'prompt_hash': self.prompt_hash,
            'context_hash': hashlib.sha256(context.encode()).hexdigest(),
        }
        fields['cache_key'] = hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return fields

    def lookup(self, identity):
        if identity is None:
            return None
        try:
            rows = self.db.table('answer_library').select('id,answer').eq(
                'cache_key', identity['cache_key']).eq('status', 'approved').limit(1).execute().data
            return rows[0] if rows and rows[0].get('answer', '').strip() else None
        except Exception:
            logger.warning('Answer library lookup unavailable; using normal tutoring')
            return None

    def save_candidate(self, identity, answer):
        if identity is None or not answer.strip() or len(answer) > 16000:
            return
        try:
            # Ignore duplicates so concurrent misses cannot overwrite a review or rejection.
            self.db.table('answer_library').upsert(
                dict(identity, answer=answer, status='pending'),
                on_conflict='cache_key', ignore_duplicates=True).execute()
        except Exception:
            logger.warning('Could not save answer review candidate')
