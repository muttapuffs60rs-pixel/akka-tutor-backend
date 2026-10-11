BEGIN;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS board text NOT NULL DEFAULT 'tn';
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS book_code text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS language text NOT NULL DEFAULT 'en';
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS board text NOT NULL DEFAULT 'tn';
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS grade_level integer;
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS subject text;
CREATE INDEX IF NOT EXISTS documents_board_grade_subject_idx ON public.documents(board,grade_level,subject);
CREATE OR REPLACE FUNCTION public.match_board_documents(query_embedding vector, query_text text, match_threshold double precision, match_count integer, filter_grade integer, filter_subject text, filter_board text)
RETURNS TABLE(content text, similarity double precision)
LANGUAGE sql STABLE AS $$
SELECT d.content, (1-(d.embedding <=> query_embedding))::float
FROM public.documents d
WHERE d.board=filter_board AND d.grade_level=filter_grade AND d.subject=filter_subject
AND ((1-(d.embedding <=> query_embedding))>match_threshold OR d.content ILIKE '%'||query_text||'%')
ORDER BY CASE WHEN d.content ILIKE '%'||query_text||'%' THEN 1.0 ELSE 0.0 END + (1-(d.embedding <=> query_embedding)) DESC
LIMIT least(greatest(match_count,0),25);
$$;
-- Legacy callers remain State Board only, including older mobile builds.
CREATE OR REPLACE FUNCTION public.hybrid_match_documents(query_embedding vector, query_text text, match_threshold double precision, match_count integer, filter_grade integer, filter_subject text)
RETURNS TABLE(content text, similarity double precision)
LANGUAGE sql STABLE AS $$
SELECT * FROM public.match_board_documents(query_embedding,query_text,match_threshold,match_count,filter_grade,filter_subject,'tn');
$$;
NOTIFY pgrst, 'reload schema';
COMMIT;
