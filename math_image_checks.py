"""Conservative local glyph checks and geometry consistency checks."""
import csv
import io
import math
import re

import cv2
import numpy as np


def perpendicular_glyphs(image):
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    mask = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, 31, 15)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    found = []
    for index, (x, y, width, height, area) in enumerate(stats[1:], 1):
        if not (12 <= height <= 120 and .65 <= width / height <= 1.6
                and .07 <= area / (width * height) <= .45):
            continue
        glyph = labels[y:y+height, x:x+width] == index
        bar = int(np.argmax(glyph.sum(axis=1)))
        if not (.78 <= bar / height <= .98 and glyph[bar].sum() >= .8 * width):
            continue
        top = glyph[:int(.65 * height)]
        stem = int(np.argmax(top.sum(axis=0)))
        if not (.3 <= stem / width <= .7 and top[:, stem].sum() >= .82 * len(top)):
            continue
        # L has an off-centre stem; 1/I have a flag or upper serif; + has ink
        # below its crossbar. Do not normalize text based on the OCR token alone.
        margin = max(2, round(width * .18))
        outside = top[:, :max(0, stem-margin)].sum() + top[:, stem+margin+1:].sum()
        if outside > .07 * max(1, top.sum()):
            continue
        found.append((int(x), int(y), int(width), int(height)))
    return found


def corrected_tesseract(tsv, glyphs):
    """Use word coordinates to replace only a pixel-verified ambiguous glyph."""
    if not tsv.startswith('level\t'):
        return tsv.strip(), []
    words = [row for row in csv.DictReader(io.StringIO(tsv), delimiter='\t')
             if row.get('text', '').strip()]
    repairs = []
    for gx, gy, gw, gh in glyphs:
        cx, cy = gx + gw/2, gy + gh/2
        candidates = []
        for row in words:
            x, y, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
            token = row['text']
            if not (x <= cx <= x+w and y <= cy <= y+h):
                continue
            if token in ('L', '1', '+', '-', 'T'):
                candidates.append((w*h, row, '⊥'))
            elif re.fullmatch(r'[A-Z]{2}[L1+\-]', token) and cx > x + .6*w:
                candidates.append((w*h, row, token[:-1] + '⊥'))
        if candidates:
            _, row, replacement = min(candidates, key=lambda item:item[0])
            repairs.append(f"{row['text']} → {replacement}")
            row['text'] = replacement
        else:
            # Glyphs are masked before the independent OCR pass so they cannot
            # merge into point names. Reinsert only between nearby baseline words.
            left, right = [], []
            for row in words:
                x,y,w,h = (int(row[k]) for k in ('left','top','width','height'))
                if min(y+h,gy+gh)-max(y,gy) < .3*min(h,gh):
                    continue
                if 0 <= gx-(x+w) <= 2*gh:
                    left.append((gx-(x+w),row))
                if 0 <= x-(gx+gw) <= 2*gh:
                    right.append((x-(gx+gw),row))
            if left and right:
                before=min(left,key=lambda item:item[0])[1]
                after=min(right,key=lambda item:item[0])[1]
                keys=('page_num','block_num','par_num','line_num')
                if all(before[k]==after[k] for k in keys):
                    word=dict(before, text='⊥',left=str(gx),top=str(gy),width=str(gw),height=str(gh))
                    words.append(word)
                    repairs.append(f"pixel glyph → ⊥ between {before['text']} and {after['text']}")
    lines = {}
    for row in words:
        key = tuple(row.get(k, '') for k in ('page_num','block_num','par_num','line_num'))
        lines.setdefault(key, []).append(row)
    return '\n'.join(' '.join(row['text'] for row in sorted(line,key=lambda r:int(r['left'])))
                     for line in lines.values()), repairs


def chord_measurements(text):
    if not re.search(r'\bcircle\b', text, re.I) or not re.search(r'\bradius\b', text, re.I):
        return None
    named = re.search(r'\b([A-Z]{2})\s*and\s*([A-Z]{2})\s*are\s*(?:the\s*)?parallel\s+chords', text)
    if not named:
        return None
    # Restore split point labels, not digits/operators: "L Mis 7cm" -> "LMis 7cm".
    text = re.sub(r'\b([A-Z])\s+([A-Z])(?=\s*(?:is|=))', r'\1\2', text)
    readings = {}
    for label, value, unit in re.findall(
            r'\b([A-Z]{2})\s*(?:=|is)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)\b', text):
        readings.setdefault(label, set()).add((float(value), unit))
    distance = re.search(r'distance\s+between\s+([A-Z]{2})\s*(?:is|=)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)\b', text)
    if not distance:
        return None
    labels = named.groups()
    if len(set(labels[0]+labels[1])) != 4:
        return None
    if any(len(readings.get(label, [])) != 1 for label in labels):
        return None
    a, b = [next(iter(readings[label])) for label in labels]
    d = (float(distance[2]), distance[3])
    if (len({a[1], b[1], d[1]}) != 1 or min(a[0], b[0], d[0]) <= 0
            or not all(math.isfinite(v) for v in (a[0], b[0], d[0]))):
        return None
    if len(readings.get(distance[1], [])) != 1:
        return None
    return labels, (a[0], b[0], d[0]), a[1], distance[1]


def verified_chord_check(primary, secondary):
    """Only supply a check when both independent OCR readings agree on facts."""
    first, second = chord_measurements(primary), chord_measurements(secondary)
    if not first or first != second:
        return ''
    labels, (length_a, length_b, distance), unit, feet = first
    # LM is the chord separation only when the perpendicular feet M/L are
    # established. Two bare point labels or a common-looking diagram are not proof.
    perpendiculars = dict(re.findall(
        r'([A-Z]{2})\s*(?:⊥|is perpendicular to)\s*([A-Z]{2})', secondary))
    segments = [segment for segment, chord in perpendiculars.items() if chord in labels]
    if (len(segments) != 2 or segments[0][0] != segments[1][0]
            or {segments[0][1], segments[1][1]} != set(feet)
            or set(perpendiculars[segment] for segment in segments) != set(labels)):
        return ''
    a, b = length_a/2, length_b/2
    signed_offset = (distance**2 + b*b - a*a) / (2*distance)
    radius = math.hypot(a, signed_offset)
    # Check both original right triangles, including nonnegative physical offsets.
    other = distance-signed_offset
    if not math.isclose(radius*radius, b*b+other*other, rel_tol=1e-9):
        return ''
    arrangement = ('opposite sides of the centre' if signed_offset > 0 and other > 0
                   else 'the same side of the centre' if signed_offset*other < 0
                   else 'one chord through the centre')
    return (f'Local mathematical consistency check: both OCR engines agree on '
            f'{labels[0]}={length_a:g} {unit}, {labels[1]}={length_b:g} {unit}, '
            f'chord separation={distance:g} {unit}. For two parallel chords of a circle, '
            f'half-lengths are {a:g} and {b:g}. Set their signed perpendicular offsets '
            f'to x and x-d, with d={distance:g}: x²+{a:g}²=(x-d)²+{b:g}². '
            f'This gives x={signed_offset:g}, radius={radius:.10g} {unit}, and '
            f'{arrangement}. This calculation uses the chord-length/separation facts, '
            'not a guessed diagram or guessed perpendicular symbol. The sign determines '
            'the arrangement; it is unnecessary to ask the student which side the chords '
            'are on. Explain the calculation and give the answer directly. '
            'This check applies only if the stated distance is the chord separation.')
