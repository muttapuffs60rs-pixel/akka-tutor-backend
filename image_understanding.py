"""Local OCR with layout ordering and an independent transcription check."""
import asyncio
import io
import os
from pathlib import Path
import shutil
import subprocess
from statistics import median

import numpy as np
from PIL import Image, ImageOps
from fastapi import HTTPException

OCR_TIMEOUT = 25


def ordered_text(results):
    """Keep words on a common baseline together before sorting left to right."""
    boxes, plain, uncertain = [], [], []
    for result in results or []:
        if isinstance(result, str):
            plain.append(result.strip())
            continue
        points, text, confidence = result
        if not text.strip():
            continue
        xs, ys = zip(*points)
        boxes.append((min(xs), min(ys), max(xs), max(ys), text.strip(), float(confidence)))
        if confidence < .75:
            uncertain.append(text.strip())
    rows = []
    for box in sorted(boxes, key=lambda b: (b[1]+b[3])/2):
        centre = (box[1]+box[3])/2
        candidates = [row for row in rows if abs(centre-median((b[1]+b[3])/2 for b in row))
                      <= .5 * median(b[3]-b[1] for b in row)]
        if candidates:
            min(candidates, key=lambda row: abs(centre-median((b[1]+b[3])/2 for b in row))).append(box)
        else:
            rows.append([box])
    text = '\n'.join(' '.join(b[4] for b in sorted(row, key=lambda b:b[0])) for row in rows)
    return text or '\n'.join(plain), uncertain


def tesseract_path():
    configured = os.getenv('TESSERACT_CMD')
    if configured:
        return configured
    found = shutil.which('tesseract')
    if found:
        return found
    windows = Path(os.getenv('ProgramFiles', 'C:/Program Files')) / 'Tesseract-OCR/tesseract.exe'
    return str(windows) if windows.is_file() else None


def extract_image(image_bytes, reader):
    with Image.open(io.BytesIO(image_bytes)) as source:
        if source.width * source.height > 16_000_000:
            raise ValueError('Image resolution exceeds OCR limit')
        image = ImageOps.exif_transpose(source).convert('RGB')
    # Avoid a huge phone photo dominating CPU time, while retaining printed detail.
    image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    results = reader.readtext(np.array(image), detail=1, paragraph=False)
    primary, uncertain = ordered_text(results)
    if len(uncertain) >= 4 and len(uncertain) > len(results) / 2:
        raise HTTPException(422,
            'Too much of this image is unclear to read reliably. Please crop to the '
            'question and upload a sharper photo, or type the question and measurements.',
            headers={'X-Chat-Error': 'image_unreadable'})
    secondary = ''
    command = tesseract_path()
    if command:
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        try:
            result = subprocess.run([command, 'stdin', 'stdout', '--psm', '6', '-l', 'eng'],
                input=buffer.getvalue(), capture_output=True, timeout=5,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0:
                secondary = result.stdout.decode('utf-8', errors='replace').strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not any(character.isalnum() for character in primary + secondary):
        raise HTTPException(422,
            'I could not read any text in this image. Please upload a clearer photo '
            'or type the question, including diagram labels and measurements.',
            headers={'X-Chat-Error': 'image_unreadable'})
    text = primary or secondary
    if primary and secondary and primary != secondary:
        text += '\n\nIndependent local OCR cross-check (not additional question text):\n' + secondary
    if uncertain:
        text += '\n\nOCR uncertain readings: ' + '; '.join(uncertain[:15])
    text += ('\n\nOCR accuracy note: transcription confidence does not establish correctness. '
             'Check both readings where available. Never silently resolve conflicting numbers '
             'or interpret L, 1, + or - as a perpendicular symbol. Ask the student to confirm '
             'any missing or conflicting fact needed to solve the problem. '
             'OCR labels do not establish diagram relationships.')
    return text


async def understand_image(image_bytes, reader):
    try:
        return await asyncio.wait_for(asyncio.to_thread(extract_image, image_bytes, reader), OCR_TIMEOUT)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503,
            'I could not read the image right now. Please try again or type the question.',
            headers={'X-Chat-Error': 'image_unavailable'}) from error
