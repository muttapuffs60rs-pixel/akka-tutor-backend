"""Exact curriculum references require reviewed identity and source metadata."""
from reference_resolution import resolve_reference

COLUMNS = {
    'textbook_sequence_number': 'selection_ordinal',
    'page_number': 'page_number', 'lesson_number': 'lesson_number',
    'chapter_number': 'chapter_number', 'exercise_number': 'exercise_number',
    'question_number': 'question_number',
}


def resolve_textbook(database, reference, board, grade, subject, history=(), **scope):
    if reference is None or reference.kind not in COLUMNS or reference.scope != 'textbook':
        return None
    scope = {**{k:v for k,v in reference.qualifiers.items() if k in ('edition','academic_year','term')}, **scope}
    query = database.table('documents').select('*')
    for key, value in [('board', board), ('grade_level', grade), ('subject', subject),
                       ('verification_status', 'verified'),
                       (COLUMNS[reference.kind], reference.number)]:
        query = query.eq(key, value)
    for kind, value in reference.qualifiers.items():
        if kind in COLUMNS:
            query = query.eq(COLUMNS[kind], value)
    for key in ('edition', 'academic_year', 'term', 'medium', 'source_title', 'section_name', 'unit_name'):
        if scope.get(key):
            query = query.eq(key, scope[key])
    rows = query.limit(101).execute().data
    if not isinstance(rows, list) or len(rows) > 100:
        return None
    # User text can narrow reviewed metadata, but can never mark it verified.
    hints = ' '.join(m.get('content', '') for m in history if m.get('role') == 'user')
    for key in ('source_title', 'section_name', 'unit_name'):
        selected = [r for r in rows if r.get(key) and r[key] in hints]
        if selected:
            rows = selected
    required = ('source_title', 'source_url', 'edition', 'content_version', 'content')
    rows = [r for r in rows if all(r.get(k) for k in required)
            and r.get('verification_status') == 'verified'
            and r.get('board') == board and r.get('grade_level') == grade
            and r.get('subject') == subject
            and (reference.work != 'thirukkural' or str(r.get('canonical_reference','')).startswith('thirukkural:'))
            and str(r.get(COLUMNS[reference.kind])) == reference.number
            and all(str(r.get(COLUMNS.get(k, k))) == str(v) for k,v in reference.qualifiers.items())
            and all(str(r.get(k)) == str(v) for k,v in scope.items() if v)]
    # Multiple pages, editions or selections must be disambiguated, not concatenated.
    if len(rows) != 1:
        return None
    return rows[0]


def resolve_reviewed_source(database, reference, board, grade, subject, history=()):
    """Use the approved 2024 source for the narrowly reviewed Class 6 Tamil scope.

    Explicit requests for another edition/year always override that default.
    This does not imply 2024 coverage of other classes, subjects or selections.
    """
    if (reference and reference.kind == 'textbook_sequence_number' and reference.work == 'thirukkural'
            and board in ('tn','cbse') and grade == 6 and subject == 'Tamil'
            and not reference.qualifiers.get('edition') and not reference.qualifiers.get('academic_year')):
        from dataclasses import replace
        reference = replace(reference, qualifiers={**reference.qualifiers, 'edition':'2024'})
    try:
        row = resolve_textbook(database, reference, board, grade, subject, history)
    except Exception:
        row = None
    if row:
        return row
    if (not reference or reference.kind != 'textbook_sequence_number' or reference.work != 'thirukkural'
            or reference.qualifiers.get('edition') != '2024' or reference.qualifiers.get('academic_year')):
        return None
    from reviewed_sources import reviewed_database
    return resolve_textbook(reviewed_database(), reference, board, grade, subject, history)


def verified_textbook(database, question, board, grade, subject, edition=None, term=None, medium=None):
    """Compatibility entry point, with no inferred seventh-item special case."""
    import json
    ref = resolve_reference(question)
    row = resolve_textbook(database, ref, board, grade, subject,
                          edition=edition, term=term, medium=medium)
    return json.dumps([row], ensure_ascii=False) if row else None
