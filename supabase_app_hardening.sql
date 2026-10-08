-- Apply AFTER the existing setup scripts, BEFORE deploying the updated API.
-- Uses the API service-role key for privileged writes. No payment behavior changes.
BEGIN;

ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS chats_today INTEGER DEFAULT 0;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS quizzes_today INTEGER DEFAULT 0;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS last_active_date DATE;

-- RLS controls rows; column grants control which fields a client can change.
-- Remove any old table and column grants before granting the safe fields.
REVOKE INSERT, UPDATE, DELETE ON public.profiles FROM PUBLIC, anon, authenticated;
DO $$
DECLARE col RECORD;
BEGIN
    FOR col IN SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'profiles'
    LOOP
        EXECUTE format('REVOKE INSERT (%I), UPDATE (%I) ON public.profiles FROM PUBLIC, anon, authenticated', col.column_name, col.column_name);
        IF col.column_name IN ('full_name', 'grade_level', 'avatar_url', 'preferred_language', 'updated_at') THEN
            EXECUTE format('GRANT INSERT (%I), UPDATE (%I) ON public.profiles TO authenticated', col.column_name, col.column_name);
        END IF;
    END LOOP;
END $$;
GRANT INSERT (id), SELECT ON public.profiles TO authenticated;
GRANT ALL ON public.profiles TO service_role;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

-- Remove legacy policies, including any under unexpected names.
DO $$
DECLARE pol RECORD;
BEGIN
    FOR pol IN SELECT tablename, policyname FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename IN ('profiles', 'quiz_questions', 'quiz_responses')
    LOOP
        EXECUTE format('DROP POLICY %I ON public.%I', pol.policyname, pol.tablename);
    END LOOP;
END $$;
CREATE POLICY "Users read own profile" ON public.profiles FOR SELECT
    TO authenticated USING (auth.uid() = id);
CREATE POLICY "Users update own profile" ON public.profiles FOR UPDATE
    TO authenticated USING (auth.uid() = id) WITH CHECK (auth.uid() = id);
CREATE POLICY "Users insert own profile" ON public.profiles FOR INSERT
    TO authenticated WITH CHECK (auth.uid() = id);

-- Students obtain sanitized question data from the authenticated API.
-- Revoke all client writes: only the API may create sessions, questions or scores.
REVOKE ALL ON public.quiz_questions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.quiz_responses FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.quiz_questions, public.quiz_responses TO authenticated;
GRANT ALL ON public.quiz_questions, public.quiz_responses TO service_role;
ALTER TABLE public.quiz_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_responses ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Read questions" ON public.quiz_questions FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.quiz_sessions s
        WHERE s.id = quiz_questions.session_id AND s.teacher_id = auth.uid()));
CREATE POLICY "Read responses" ON public.quiz_responses FOR SELECT TO authenticated
    USING (student_id = auth.uid() OR EXISTS (SELECT 1 FROM public.quiz_sessions s
        WHERE s.id = quiz_responses.session_id AND s.teacher_id = auth.uid()));

-- Database clients cannot bypass API limits by creating quiz sessions directly.
REVOKE INSERT, UPDATE, DELETE ON public.quiz_sessions FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.quiz_sessions TO service_role;

-- Independent foreign keys do not enforce that a question belongs to a session.
CREATE OR REPLACE FUNCTION public.check_quiz_response_session()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.quiz_questions q
        WHERE q.id = NEW.question_id AND q.session_id = NEW.session_id) THEN
        RAISE EXCEPTION 'Question does not belong to session' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS quiz_response_session_check ON public.quiz_responses;
CREATE TRIGGER quiz_response_session_check BEFORE INSERT OR UPDATE
    ON public.quiz_responses FOR EACH ROW EXECUTE FUNCTION public.check_quiz_response_session();

-- Shared IST rollover holds a row lock until the surrounding transaction ends.
-- Both counters reset together, whether the first request is chat or a quiz.
CREATE OR REPLACE FUNCTION public.reset_daily_usage(target_user_id UUID)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    profile public.profiles%ROWTYPE;
    today DATE := (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::DATE;
BEGIN
    SELECT * INTO profile FROM public.profiles p WHERE p.id = target_user_id FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF profile.last_active_date::TEXT IS DISTINCT FROM today::TEXT THEN
        UPDATE public.profiles p SET
            chats_today = 0,
            quizzes_today = 0,
            subscription_tier = CASE WHEN p.subscription_tier = 'tier_49_daily'
                THEN COALESCE(p.previous_tier, 'free') ELSE p.subscription_tier END,
            previous_tier = CASE WHEN p.subscription_tier = 'tier_49_daily'
                THEN NULL ELSE p.previous_tier END,
            last_active_date = today
        WHERE p.id = target_user_id RETURNING p.* INTO profile;
    END IF;
    RETURN to_jsonb(profile);
END $$;

CREATE OR REPLACE FUNCTION public.reserve_daily_quiz(target_user_id UUID)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE profile JSONB;
BEGIN
    profile := public.reset_daily_usage(target_user_id);
    IF profile IS NULL THEN RAISE EXCEPTION 'User profile not found'; END IF;
    UPDATE public.profiles p SET quizzes_today = COALESCE(p.quizzes_today, 0) + 1
        WHERE p.id = target_user_id AND COALESCE(p.quizzes_today, 0) < 5;
    IF NOT FOUND THEN RETURN NULL; END IF;
    RETURN profile->>'last_active_date';
END $$;

CREATE OR REPLACE FUNCTION public.release_daily_quiz(target_user_id UUID, usage_date TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE public.profiles p SET quizzes_today = GREATEST(COALESCE(p.quizzes_today, 0) - 1, 0)
        WHERE p.id = target_user_id AND p.last_active_date::TEXT = usage_date;
END $$;

-- SECURITY DEFINER functions otherwise receive PUBLIC execute permission by default.
-- Include legacy counter, leaderboard and cleanup functions if present.
DO $$
DECLARE fn RECORD;
BEGIN
    FOR fn IN SELECT p.oid::regprocedure AS signature FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname IN (
            'reset_daily_usage', 'reserve_daily_quiz', 'release_daily_quiz',
            'increment_profile_field', 'get_session_leaderboard', 'delete_old_chat_sessions')
    LOOP
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, anon, authenticated', fn.signature);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn.signature);
    END LOOP;
END $$;

COMMIT;
