-- =====================================================
-- Tutor Preethi — Live Quiz Feature Setup
-- Run this entire script in Supabase SQL Editor
-- =====================================================

-- 1. QUIZ SESSIONS
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_code VARCHAR(6) UNIQUE NOT NULL,
    teacher_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'waiting'
        CHECK (status IN ('waiting', 'active', 'completed')),
    current_question_index INT DEFAULT -1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. QUIZ QUESTIONS
CREATE TABLE IF NOT EXISTS quiz_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    question_type VARCHAR(20) NOT NULL
        CHECK (question_type IN ('mcq', 'fill_blank')),
    options JSONB,
    correct_answer TEXT NOT NULL,
    points INT DEFAULT 1,
    sort_order INT NOT NULL
);

-- 3. STUDENT RESPONSES (students must be logged in)
CREATE TABLE IF NOT EXISTS quiz_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    student_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    student_name TEXT NOT NULL,
    question_id UUID REFERENCES quiz_questions(id) ON DELETE CASCADE,
    submitted_answer TEXT NOT NULL,
    is_correct BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, student_id, question_id)
);

-- 4. LEADERBOARD RPC
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
$$ LANGUAGE plpgsql;

-- 5. ENABLE REALTIME
ALTER PUBLICATION supabase_realtime ADD TABLE quiz_sessions;
ALTER PUBLICATION supabase_realtime ADD TABLE quiz_responses;

-- 6. RLS POLICIES
ALTER TABLE quiz_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz_responses ENABLE ROW LEVEL SECURITY;

-- Sessions: anyone authenticated can read; only teacher can write
CREATE POLICY "Read sessions" ON quiz_sessions FOR SELECT TO authenticated USING (true);
CREATE POLICY "Create sessions" ON quiz_sessions FOR INSERT TO authenticated WITH CHECK (auth.uid() = teacher_id);
CREATE POLICY "Update sessions" ON quiz_sessions FOR UPDATE TO authenticated USING (auth.uid() = teacher_id);

-- Questions: authenticated users can read; only teacher can write (via backend)
CREATE POLICY "Read questions" ON quiz_questions FOR SELECT TO authenticated USING (true);

-- Responses: students submit their own; all can read (leaderboard)
CREATE POLICY "Submit response" ON quiz_responses FOR INSERT TO authenticated WITH CHECK (auth.uid() = student_id);
CREATE POLICY "Read responses" ON quiz_responses FOR SELECT TO authenticated USING (true);
