# OCR-only image question replies

The backend now reads every uploaded image with local EasyOCR, then sends
only the extracted text and the student's question to the existing text tutor.
There is no Gemini client, API call, Google key requirement or Google SDK
dependency in this backend. Legacy vision usage columns remain compatible
with the existing database and record zero tokens for successful OCR requests.

OCR has a 25-second deadline, including the local cross-check. Empty or unreadable results return a message
asking for a clearer photo or a typed question. OCR exceptions and timeouts
return an actionable error instead of silently failing. Short readable
questions are accepted; there is no ten-word cutoff.

The tutor prompt makes clear that OCR does not describe diagram geometry
and must request missing measurements or relationships instead of guessing.
The existing English OCR model remains in use. Handwriting, mathematical
symbols, diagram positions and other scripts can be read imperfectly.

Deploy main.py, image_understanding.py and requirements.txt together.
GOOGLE_API_KEY and GEMINI_VISION_MODEL may be removed from the deployed
backend environment; they are no longer read. No production environment
settings or credentials were changed locally.

The companion Flutter patch detects empty/stalled replies and allows longer
image preparation. Release it with the backend for those client improvements.
These changes have not been deployed or verified against the live app.

## Precision improvements

- Normalize camera orientation and cap oversized photos before OCR.
- Preserve bounding boxes and confidence, then reconstruct lines in reading order.
- Run an independent Tesseract English transcription with a five-second limit.
- Keep disagreements visible and mark low-confidence readings. Do not rewrite
  ambiguous mathematical operators or conflicting values into assumed facts.
- Docker installs tesseract-ocr and its English model. On non-Docker installs,
  install Tesseract or set TESSERACT_CMD; EasyOCR remains the fallback.

27 offline route, OCR and reliability tests pass. The two supplied images are
also checked with real local OCR; this is a small fixture set, not a general
accuracy benchmark. Mathematics symbols and diagrams still require confirmation
where the transcriptions do not supply an unambiguous fact.

Images with at least four uncertain readings making up a majority of detected text are rejected with a request for a sharper crop. Confidence is a heuristic, not proof that accepted text is accurate.
