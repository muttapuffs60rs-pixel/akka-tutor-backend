"""Bound chat prompt size independently of client-side controls."""
MAX_EXCHANGES = 10
MAX_REPLY_TOKENS = 900


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
