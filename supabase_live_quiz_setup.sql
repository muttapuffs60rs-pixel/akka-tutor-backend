-- =====================================================
-- Tutor Preethi — Live Quiz Feature Setup
-- Run this entire script in Supabase SQL Editor
-- Safe to re-run (uses IF NOT EXISTS / OR REPLACE)
-- =====================================================


-- ─── 1. QUIZ SESSIONS ────────────────────────────────
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_code            VARCHAR(6) UNIQUE NOT NULL,
    teacher_id              UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    title                   VARCHAR(255) NOT NULL,
    status                  VARCHAR(20) DEFAULT 'waiting'
                                CHECK (status IN ('waiting', 'active', 'completed')),
    current_question_index  INT DEFAULT -1,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast session_code lookups (used on every API call)
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_code
    ON quiz_sessions (session_code);


-- ─── 2. QUIZ QUESTIONS ───────────────────────────────
CREATE TABLE IF NOT EXISTS quiz_questions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_text   TEXT NOT NULL,
    question_type   VARCHAR(20) NOT NULL
                        CHECK (question_type IN ('mcq', 'fill_blank')),
    options         JSONB,           -- array of choices for MCQ, null for fill_blank
    correct_answer  TEXT NOT NULL,
    points          INT DEFAULT 1,
    sort_order      INT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quiz_questions_session
    ON quiz_questions (session_id, sort_order);


-- ─── 3. STUDENT RESPONSES ────────────────────────────
-- Unique constraint prevents double-answering the same question
CREATE TABLE IF NOT EXISTS quiz_responses (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    student_id        UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    student_name      TEXT NOT NULL,
    question_id       UUID REFERENCES quiz_questions(id) ON DELETE CASCADE,
    submitted_answer  TEXT NOT NULL,
    is_correct        BOOLEAN NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, student_id, question_id)   -- one answer per student per question
);

CREATE INDEX IF NOT EXISTS idx_quiz_responses_session
    ON quiz_responses (session_id);


-- ─── 4. LEADERBOARD RPC ──────────────────────────────
-- Called by GET /live-quiz/{code}/leaderboard
-- Returns students ranked by correct answers for a given session
DROP FUNCTION IF EXISTS get_session_leaderboard(UUID);

CREATE OR REPLACE FUNCTION get_session_leaderboard(target_session_id UUID)
RETURNS TABLE(student_name TEXT, total_score NUMERIC) AS $$
BEGIN
    RETURN QUERY
    SELECT
        qr.student_name::TEXT,
        SUM(CASE WHEN qr.is_correct THEN 1 ELSE -0.5 END)::NUMERIC AS total_score
    FROM quiz_responses qr
    WHERE qr.session_id = target_session_id
    GROUP BY qr.student_id, qr.student_name
    ORDER BY total_score DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- ─── 5. REALTIME ─────────────────────────────────────
-- Allows Flutter to subscribe to live changes (answer counting)
DO $$
BEGIN
    -- quiz_sessions
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'quiz_sessions'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE quiz_sessions;
    END IF;

    -- quiz_responses
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'quiz_responses'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE quiz_responses;
    END IF;
END $$;


-- ─── 6. PROFILE UPDATES ──────────────────────────────
CREATE OR REPLACE FUNCTION increment_profile_field(target_user_id UUID, field_name TEXT)
RETURNS void AS $$
BEGIN
    IF field_name = 'chats_today' THEN
        UPDATE profiles SET chats_today = COALESCE(chats_today, 0) + 1 WHERE id = target_user_id;
    ELSIF field_name = 'quizzes_today' THEN
        UPDATE profiles SET quizzes_today = COALESCE(quizzes_today, 0) + 1 WHERE id = target_user_id;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- ─── 6. ROW LEVEL SECURITY ───────────────────────────
ALTER TABLE quiz_sessions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz_responses ENABLE ROW LEVEL SECURITY;

-- Drop existing policies first so this script is re-runnable
DROP POLICY IF EXISTS "Read sessions"    ON quiz_sessions;
DROP POLICY IF EXISTS "Create sessions"  ON quiz_sessions;
DROP POLICY IF EXISTS "Update sessions"  ON quiz_sessions;

DROP POLICY IF EXISTS "Read questions"   ON quiz_questions;
DROP POLICY IF EXISTS "Write questions"  ON quiz_questions;

DROP POLICY IF EXISTS "Submit response"  ON quiz_responses;
DROP POLICY IF EXISTS "Read responses"   ON quiz_responses;

-- quiz_sessions
CREATE POLICY "Read sessions"   ON quiz_sessions FOR SELECT TO authenticated USING (true);
CREATE POLICY "Create sessions" ON quiz_sessions FOR INSERT TO authenticated WITH CHECK (auth.uid() = teacher_id);
CREATE POLICY "Update sessions" ON quiz_sessions FOR UPDATE TO authenticated USING (auth.uid() = teacher_id);

-- quiz_questions (backend service writes via service-role key; students/teachers read)
CREATE POLICY "Read questions"  ON quiz_questions FOR SELECT TO authenticated USING (true);
-- INSERT is done from the backend with the service role key (bypasses RLS), so no insert policy needed here.
-- If you're inserting via anon/user key instead, uncomment the line below:
-- CREATE POLICY "Write questions" ON quiz_questions FOR INSERT TO authenticated WITH CHECK (true);

-- quiz_responses
CREATE POLICY "Submit response" ON quiz_responses FOR INSERT TO authenticated WITH CHECK (auth.uid() = student_id);
CREATE POLICY "Read responses"  ON quiz_responses FOR SELECT TO authenticated USING (true);


-- ─── DONE ────────────────────────────────────────────
-- Tables:   quiz_sessions, quiz_questions, quiz_responses
-- Function: get_session_leaderboard(target_session_id)
-- Realtime: quiz_sessions, quiz_responses
-- RLS:      All tables protected, authenticated users only
