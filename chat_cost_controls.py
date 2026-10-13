"""Bound chat prompt size independently of client-side controls."""
MAX_EXCHANGES = 10
MAX_REPLY_TOKENS = 900
MAX_LITERATURE_TOKENS = 1800  # Shared cap for reasoning plus visible answer.


def chat_model_options(subject, question):
    from textbook_retrieval import TAMIL_SUBJECTS, named_work_query
    if subject in TAMIL_SUBJECTS and named_work_query(question):
        return {'max_tokens': MAX_LITERATURE_TOKENS,
                'extra_body': {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low'}}
    return {'max_tokens': MAX_REPLY_TOKENS}


def retrieval_query(question, history):
    """Only carry a previous topic into genuinely referential follow-ups."""
    import re
    question = question.strip()
    def is_followup(text):
        introduction = re.split(r'\band\b|\bhow\b|\bwhy\b|[.!?]', text, maxsplit=1, flags=re.I)[0]
        if (re.match(r'^(?:what (?:is|are)|explain|describe|tell me about)\s+'
                    r'(?!(?:it|its|their|this|that|these|those|them|more|again|how|why)\b)'
                    r'(?!(?:the )?(?:first|second|next) one\b)\w', text, re.I) and
                not re.search(r'\b(?:it|its|their|this|that|these|those|them)\b', introduction, re.I)):
            return False
        if re.match(r'^(?!(?:அது|இது)\s)[\u0b80-\u0bff]+\s+பற்றி', text):
            return False
        return re.search(
        r'\b(it|its|this|that|these|those|they|them|their)\b|'
        r'^(explain (more|again)|give (an? )?examples?|why|how so)[?.! ]*$|'
        r'^(?:what about the (?:first|second|next) one|what next)[?.! ]*$|'
        r'^(?:இன்னும் எளிமையாக விளக்கு|அடுத்தது என்ன)[?.! ]*$|'
        r'(இது|அது|இதை|அதை|இவற்றை|அவற்றை|அவற்றுக்கு|இவற்றுக்கு|அவற்றின்|இவற்றின்)', text, re.IGNORECASE)
    if is_followup(question):
        # Walk through a chain to the latest substantive user topic. Assistant
        # guesses are never retrieval anchors. Stop at an explicit topic change.
        chain = []
        for item in reversed(history[-20:]):
            if item.get('role') != 'user':
                continue
            previous = item.get('content', '').strip()
            if not previous:
                continue
            chain.append(previous[:1500])
            if not is_followup(previous):
                return ' '.join(reversed(chain[-3:])) + ' ' + question
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
