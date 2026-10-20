"""Exact, concise answers for standalone numeric multiplication requests."""
import re

_PRODUCT = re.compile(r'\s*([+-]?\d{1,18})\s*[*xX×]\s*([+-]?\d{1,18})\s*(?:=\s*)?\??\s*', re.ASCII)


def simple_product(question: str, image_url=None):
    # Text, word problems, explanation requests and images stay with the tutor.
    if image_url:
        return None
    match = _PRODUCT.fullmatch(question or '')
    if not match:
        return None
    left, right = map(int, match.groups())
    return f'{left} × {right} = {left * right:,}'
