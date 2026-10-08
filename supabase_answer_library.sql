-- Apply after supabase_chat_cost_controls.sql. No client may access these tables directly.
BEGIN;
CREATE TABLE IF NOT EXISTS public.answer_library (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cache_key text NOT NULL UNIQUE,
    question text NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
    answer text NOT NULL CHECK (length(answer) BETWEEN 1 AND 16000),
    subject text NOT NULL,
    grade_level integer NOT NULL CHECK (grade_level BETWEEN 6 AND 12),
    board text NOT NULL,
    language text NOT NULL,
    syllabus_version text NOT NULL,
    prompt_hash text NOT NULL,
    context_hash text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    chapter text NOT NULL DEFAULT '',
    source_reference text NOT NULL DEFAULT '',
    review_note text NOT NULL DEFAULT '',
    privacy_checked boolean NOT NULL DEFAULT false,
    accuracy_checked boolean NOT NULL DEFAULT false,
    reviewed_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    report_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'approved' OR (privacy_checked AND accuracy_checked
        AND length(trim(chapter)) > 0 AND length(trim(source_reference)) > 0))
);
CREATE INDEX IF NOT EXISTS answer_library_queue_idx ON public.answer_library(status, updated_at DESC);
CREATE TABLE IF NOT EXISTS public.answer_library_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    answer_id uuid NOT NULL REFERENCES public.answer_library(id),
    reviewer_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    previous_answer text NOT NULL,
    review jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.answer_library_reports (
    answer_id uuid NOT NULL REFERENCES public.answer_library(id),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (answer_id, user_id)
);
ALTER TABLE public.answer_library ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.answer_library_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.answer_library_reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.answer_library, public.answer_library_reviews, public.answer_library_reports FROM anon, authenticated;
GRANT ALL ON public.answer_library, public.answer_library_reviews, public.answer_library_reports TO service_role;

ALTER TABLE public.ai_chat_requests ADD COLUMN IF NOT EXISTS answer_cache_id uuid REFERENCES public.answer_library(id);
ALTER TABLE public.ai_chat_requests ADD COLUMN IF NOT EXISTS response_source text NOT NULL DEFAULT 'ai';
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS answer_cache_id uuid;
CREATE INDEX IF NOT EXISTS ai_chat_requests_cache_idx ON public.ai_chat_requests(user_id, answer_cache_id);

CREATE OR REPLACE FUNCTION public.review_library_answer(target_id uuid, reviewer_id uuid, review jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE current_answer public.answer_library%ROWTYPE;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.profiles WHERE id = reviewer_id AND subscription_tier = 'admin') THEN
        RAISE EXCEPTION 'Administrator access required' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO current_answer FROM public.answer_library WHERE id = target_id FOR UPDATE;
    IF NOT FOUND OR current_answer.updated_at IS DISTINCT FROM (review->>'expected_updated_at')::timestamptz THEN
        RETURN NULL;
    END IF;
    INSERT INTO public.answer_library_reviews(answer_id, reviewer_id, previous_answer, review)
        VALUES (target_id, reviewer_id, current_answer.answer, review);
    UPDATE public.answer_library SET
        status = review->>'status', answer = review->>'answer',
        chapter = review->>'chapter', source_reference = review->>'source_reference',
        review_note = review->>'review_note', privacy_checked = (review->>'privacy_checked')::boolean,
        accuracy_checked = (review->>'accuracy_checked')::boolean,
        reviewed_by = reviewer_id, updated_at = clock_timestamp()
    WHERE id = target_id RETURNING * INTO current_answer;
    RETURN to_jsonb(current_answer);
END $$;

CREATE OR REPLACE FUNCTION public.report_library_answer(target_id uuid, reporter_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.ai_chat_requests WHERE user_id = reporter_id
        AND answer_cache_id = target_id AND response_source = 'cache' AND status = 'cached') THEN
        RETURN false;
    END IF;
    -- Lock the same row as review updates. An accepted report requires a fresh review.
    PERFORM 1 FROM public.answer_library WHERE id = target_id FOR UPDATE;
    INSERT INTO public.answer_library_reports(answer_id, user_id) VALUES(target_id, reporter_id)
        ON CONFLICT DO NOTHING;
    IF FOUND THEN
        UPDATE public.answer_library SET status = 'pending', privacy_checked = false,
            accuracy_checked = false, report_count = report_count + 1,
            review_note = 'Student reported this saved answer. Review before publishing again.',
            updated_at = clock_timestamp() WHERE id = target_id;
    END IF;
    RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.review_library_answer(uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.report_library_answer(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.review_library_answer(uuid, uuid, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.report_library_answer(uuid, uuid) TO service_role;
COMMIT;
