-- Run as a standalone statement, outside a transaction.
-- Supports grade/subject isolation and paginated textbook verification as the library grows.
CREATE INDEX CONCURRENTLY IF NOT EXISTS documents_grade_subject_id_idx
ON public.documents (grade_level, subject, id);
