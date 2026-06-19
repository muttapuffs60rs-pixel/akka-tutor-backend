-- =====================================================
-- Tutor Preethi — Complete Database Setup + Security
-- Run this ONCE in Supabase SQL Editor
-- Creates all tables, RLS, indexes, and RPC functions
-- Safe to re-run (idempotent)
-- =====================================================


-- ═══════════════════════════════════════════════════
-- STEP 1: CREATE TABLES
-- ═══════════════════════════════════════════════════

-- ── quiz_sessions ────────────────────────────────────
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

CREATE INDEX IF NOT EXISTS idx_quiz_sessions_code
    ON quiz_sessions (session_code);

-- ── quiz_questions ────────────────────────────────────
CREATE TABLE IF NOT EXISTS quiz_questions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_text   TEXT NOT NULL,
    question_type   VARCHAR(20) NOT NULL
                        CHECK (question_type IN ('mcq', 'fill_blank')),
    options         JSONB,
    correct_answer  TEXT NOT NULL,
    points          INT DEFAULT 1,
    sort_order      INT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quiz_questions_session
    ON quiz_questions (session_id, sort_order);

-- ── quiz_responses ────────────────────────────────────
CREATE TABLE IF NOT EXISTS quiz_responses (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    student_id        UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    student_name      TEXT NOT NULL,
    question_id       UUID REFERENCES quiz_questions(id) ON DELETE CASCADE,
    submitted_answer  TEXT NOT NULL,
    is_correct        BOOLEAN NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, student_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_quiz_responses_session
    ON quiz_responses (session_id);


-- ═══════════════════════════════════════════════════
-- STEP 2: LEADERBOARD RPC FUNCTION
-- ═══════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION get_session_leaderboard(target_session_id UUID)
RETURNS TABLE(student_name TEXT, total_score BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT
        qr.student_name::TEXT,
        COUNT(*) FILTER (WHERE qr.is_correct = true) AS total_score
    FROM quiz_responses qr
    WHERE qr.session_id = target_session_id
    GROUP BY qr.student_id, qr.student_name
    ORDER BY total_score DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- ═══════════════════════════════════════════════════
-- STEP 3: ENABLE REALTIME
-- ═══════════════════════════════════════════════════
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'quiz_sessions'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE quiz_sessions;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'quiz_responses'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE quiz_responses;
    END IF;
END $$;


-- ═══════════════════════════════════════════════════
-- STEP 4: ROW LEVEL SECURITY — Enable on ALL tables
-- ═══════════════════════════════════════════════════

-- ── profiles ─────────────────────────────────────────
-- (table already exists from your Supabase auth setup)
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own profile"   ON profiles;
DROP POLICY IF EXISTS "Users update own profile" ON profiles;
DROP POLICY IF EXISTS "Users insert own profile" ON profiles;

CREATE POLICY "Users read own profile"
    ON profiles FOR SELECT TO authenticated
    USING (auth.uid() = id);

CREATE POLICY "Users update own profile"
    ON profiles FOR UPDATE TO authenticated
    USING (auth.uid() = id);

CREATE POLICY "Users insert own profile"
    ON profiles FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = id);

-- ── documents ─────────────────────────────────────────
-- (textbook chunks — read-only for students/teachers)
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Authenticated users read documents" ON documents;

CREATE POLICY "Authenticated users read documents"
    ON documents FOR SELECT TO authenticated
    USING (true);

-- ── quiz_sessions ─────────────────────────────────────
ALTER TABLE quiz_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Read sessions"   ON quiz_sessions;
DROP POLICY IF EXISTS "Create sessions" ON quiz_sessions;
DROP POLICY IF EXISTS "Update sessions" ON quiz_sessions;

CREATE POLICY "Read sessions"
    ON quiz_sessions FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "Create sessions"
    ON quiz_sessions FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = teacher_id);

CREATE POLICY "Update sessions"
    ON quiz_sessions FOR UPDATE TO authenticated
    USING (auth.uid() = teacher_id);

-- ── quiz_questions ────────────────────────────────────
ALTER TABLE quiz_questions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Read questions" ON quiz_questions;

CREATE POLICY "Read questions"
    ON quiz_questions FOR SELECT TO authenticated
    USING (true);

-- ── quiz_responses ────────────────────────────────────
ALTER TABLE quiz_responses ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Submit response" ON quiz_responses;
DROP POLICY IF EXISTS "Read responses"  ON quiz_responses;

CREATE POLICY "Submit response"
    ON quiz_responses FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = student_id);

CREATE POLICY "Read responses"
    ON quiz_responses FOR SELECT TO authenticated
    USING (true);


-- ═══════════════════════════════════════════════════
-- VERIFY — confirm rls_enabled = true for all tables
-- ═══════════════════════════════════════════════════
SELECT
    tablename,
    rowsecurity AS rls_enabled
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
