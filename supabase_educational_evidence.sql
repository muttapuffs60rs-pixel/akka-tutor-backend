-- Optional metadata extension of existing RAG; no paid services or new embeddings.
-- Run after supabase_board_curriculum.sql. Existing rows remain unreviewed.
BEGIN;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS source_title text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS edition text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS academic_year text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS term text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS medium text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS content_version text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS verification_status text NOT NULL DEFAULT 'unreviewed';
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS page_number integer;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS lesson_number integer;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS selection_ordinal integer;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS canonical_reference text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS chapter_number text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS exercise_number text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS question_number text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS source_meaning text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS meaning_status text NOT NULL DEFAULT 'unreviewed';
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS simplified_meaning text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS reviewed_example text;
CREATE INDEX IF NOT EXISTS documents_verified_reference_idx ON public.documents
 (board,grade_level,subject,edition,term,page_number,lesson_number,selection_ordinal)
 WHERE verification_status='verified';
-- Existing security migrations retain ownership of documents access. Verification
-- must only be written by the privileged ingestion process, never the client.
REVOKE INSERT, UPDATE, DELETE ON public.documents FROM anon, authenticated;
-- Kept outside client-editable chat_sessions. Never trust client-written
-- verification state. The handler checks ownership before reading this table.
CREATE TABLE IF NOT EXISTS public.chat_learning_context (
 session_id uuid PRIMARY KEY REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 board text NOT NULL CHECK (board IN ('tn','cbse')),
 grade_level integer NOT NULL CHECK (grade_level BETWEEN 6 AND 12),
 subject text NOT NULL,
 context jsonb NOT NULL DEFAULT '{}',
 updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.chat_learning_context ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.chat_learning_context FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chat_learning_context TO service_role;
NOTIFY pgrst,'reload schema';
COMMIT;
