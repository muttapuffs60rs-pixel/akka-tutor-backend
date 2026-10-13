"""Conservative local text comparison, never a production verification write.

An extraction match is not a semantic, formula-layout or completeness verdict.
Raw inputs and immutable source receipts must be retained by the caller.
"""
import hashlib
import re
import unicodedata
from difflib import SequenceMatcher


def formatting_normalize(text):
    # NFC and whitespace only. Do not remove signs, punctuation or Tamil marks,
    # fold sub/superscripts, reorder equations, or repair letters automatically.
    return ' '.join(unicodedata.normalize('NFC',text).split())


def complete_span(passage,page):
    """Do not accept a partial word/formula: H₂O must not match H₂O₂."""
    def word(c):return unicodedata.category(c)[0] in 'LMN'
    start=0
    while (index:=page.find(passage,start))>=0:
        end=index+len(passage)
        left=index==0 or not (word(page[index-1]) and word(passage[0]))
        right=end==len(page) or not (word(page[end]) and word(passage[-1]))
        if left and right:return True
        start=index+1
    return False


def compare_passage(original, page_text, *, source_identified, page_identified):
    result={'original_sha256':hashlib.sha256(original.encode()).hexdigest(),
            'page_extraction_sha256':hashlib.sha256(page_text.encode()).hexdigest(),
            'status':'unverifiable','semantic_review':'not_performed'}
    if not source_identified or not page_identified:
        return dict(result,reason='Source edition/page identity has not been established')
    if len(original.strip())<40 or not page_text.strip() or '\ufffd' in original+page_text:
        return dict(result,reason='Empty, short or damaged text requires inspection')
    if complete_span(original,page_text):
        return dict(result,status='exact_match',reason='Exact substring in identified page extraction')
    passage= formatting_normalize(original)
    page=formatting_normalize(page_text)
    if complete_span(passage,page):
        return dict(result,status='formatting_only',reason='NFC/whitespace difference only')
    # A score is diagnostic, never a threshold for promoting content to verified.
    match=SequenceMatcher(None,passage,page,autojunk=False).find_longest_match()
    return dict(result,status='substantive_discrepancy',reason='Text differs at supplied source/page; inspect original rendering',
                longest_exact_span_fraction=round(match.size/max(len(passage),1),4))
