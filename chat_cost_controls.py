"""Bound chat prompt size independently of client-side controls."""
MAX_EXCHANGES = 10
MAX_REPLY_TOKENS = 900


def retrieval_query(question, history):
    """Only carry a previous topic into genuinely referential follow-ups."""
    import re
    question = question.strip()
    referential = re.search(
        r'\b(it|its|this|that|these|those|they|them|their)\b|'
        r'^(explain (more|again)|give (an? )?examples?|why|how so)[?.! ]*$|'
        r'(இது|அது|இதை|அதை|இவற்றை|அவற்றை)', question, re.IGNORECASE)
    if referential:
        previous = next((m.get('content', '') for m in reversed(history)
                         if m.get('role') == 'user'), '')
        if previous:
            return f'{previous} {question}'
    return question


def clip_text(text: str, max_bytes: int) -> str:
    return text.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')


def bounded_history(history):
    # Three recent exchanges; keep the complete transcript in storage/UI.
    return [
        {'role': item['role'], 'content': clip_text(item.get('content', ''), 1500)}
        for item in history[-6:]
        if item.get('role') in ('user', 'assistant')
        and isinstance(item.get('content', ''), str)
    ]
