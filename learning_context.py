"""Server-only reference memory. Source content is always revalidated on use."""
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from reference_resolution import Reference, KINDS

KINDS_ALLOWED = set(KINDS) | {'canonical_reference_number', 'textbook_sequence_number'}


def read_context(db, session_id, user_id, board, grade, subject):
    try:
        rows = (db.table('chat_learning_context').select('*')
                .eq('session_id', str(session_id)).eq('user_id', user_id).execute().data)
        if not isinstance(rows, list) or len(rows) != 1:
            return None
        row = rows[0]
        if row.get('session_id') != str(session_id) or row.get('user_id') != user_id:
            return None
        if any(row.get(k) != v for k,v in [('board',board),('grade_level',grade),('subject',subject)]):
            return None
        if datetime.fromisoformat(row['updated_at'].replace('Z','+00:00')) < datetime.now(timezone.utc)-timedelta(days=30):
            return None
        context = row['context']
        if not isinstance(context, dict) or context.get('verified') is not True:
            return None
        if context.get('teaching_ids'):
            from reviewed_sources import teaching_records
            allowed = {r['id'] for r in teaching_records()
                       if (r['board'], r['grade_level'], r['subject']) == (board, grade, subject)}
            if (isinstance(context['teaching_ids'], list) and len(context['teaching_ids']) <= 4 and
                    all(isinstance(i, str) and i in allowed for i in context['teaching_ids'])):
                return {'verified': True, 'teaching_ids': context['teaching_ids']}
            return None
        ref = Reference(**context['reference'])
        if ref.kind not in KINDS_ALLOWED or ref.scope not in ('canonical','textbook') or not ref.number or ref.ambiguous:
            return None
        if len(str(context)) > 4000:
            return None
        return context
    except Exception:
        # Missing migration/outage must not confer verification on client history.
        return None


def verified_context(reference, source=None):
    ref = Reference(**asdict(reference))
    if source:
        # Pin only actual resolved source scope, never a guessed current year.
        for key in ('edition','academic_year','term'):
            if source.get(key):
                ref.qualifiers[key] = source[key]
    return {'verified': True, 'reference': asdict(ref)}


def write_context(db, session_id, user_id, board, grade, subject, context):
    try:
        db.table('chat_learning_context').upsert({
            'session_id':str(session_id), 'user_id':user_id, 'board':board,
            'grade_level':grade, 'subject':subject, 'context':context or {},
            'updated_at':datetime.now(timezone.utc).isoformat(),
        }, on_conflict='session_id').execute()
        return True
    except Exception:
        return False
