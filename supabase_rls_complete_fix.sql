-- =====================================================
-- Tutor Preethi — CHAT TABLE RLS POLICIES
-- Run this in Supabase SQL Editor
-- Fixes all missing policies for chat_sessions,
-- chat_messages so the app continues to work.
-- =====================================================


-- ═══════════════════════════════════════════════════
-- TABLE: chat_sessions
-- Columns: id, user_id, title, created_at
-- Flutter inserts, selects, and updates these rows.
-- Each session belongs to one user (user_id column).
-- ═══════════════════════════════════════════════════
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own sessions"   ON chat_sessions;
DROP POLICY IF EXISTS "Users create own sessions" ON chat_sessions;
DROP POLICY IF EXISTS "Users update own sessions" ON chat_sessions;
DROP POLICY IF EXISTS "Users delete own sessions" ON chat_sessions;

-- User can only see their own chat sessions
CREATE POLICY "Users read own sessions"
    ON chat_sessions FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

-- User can create sessions for themselves
CREATE POLICY "Users create own sessions"
    ON chat_sessions FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

-- User can update their own sessions (e.g. rename title)
CREATE POLICY "Users update own sessions"
    ON chat_sessions FOR UPDATE TO authenticated
    USING (auth.uid() = user_id);

-- User can delete their own sessions
CREATE POLICY "Users delete own sessions"
    ON chat_sessions FOR DELETE TO authenticated
    USING (auth.uid() = user_id);


-- ═══════════════════════════════════════════════════
-- TABLE: chat_messages
-- Columns: id, user_id, session_id, message,
--          is_user, image_url, created_at
-- Flutter inserts and reads these rows.
-- ═══════════════════════════════════════════════════
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own messages"   ON chat_messages;
DROP POLICY IF EXISTS "Users create own messages" ON chat_messages;

-- User can only read messages from their own sessions
CREATE POLICY "Users read own messages"
    ON chat_messages FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

-- User can insert messages tagged with their own user_id
CREATE POLICY "Users create own messages"
    ON chat_messages FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);


-- ═══════════════════════════════════════════════════
-- Re-confirm all other table policies (idempotent)
-- ═══════════════════════════════════════════════════

-- profiles
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users read own profile"   ON profiles;
DROP POLICY IF EXISTS "Users update own profile" ON profiles;
DROP POLICY IF EXISTS "Users insert own profile" ON profiles;
CREATE POLICY "Users read own profile"   ON profiles FOR SELECT TO authenticated USING (auth.uid() = id);
CREATE POLICY "Users update own profile" ON profiles FOR UPDATE TO authenticated USING (auth.uid() = id);
CREATE POLICY "Users insert own profile" ON profiles FOR INSERT TO authenticated WITH CHECK (auth.uid() = id);

-- documents (read-only for all authenticated users)
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Authenticated users read documents" ON documents;
CREATE POLICY "Authenticated users read documents" ON documents FOR SELECT TO authenticated USING (true);

-- quiz_sessions
ALTER TABLE quiz_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Read sessions"   ON quiz_sessions;
DROP POLICY IF EXISTS "Create sessions" ON quiz_sessions;
DROP POLICY IF EXISTS "Update sessions" ON quiz_sessions;
CREATE POLICY "Read sessions"   ON quiz_sessions FOR SELECT TO authenticated USING (true);
CREATE POLICY "Create sessions" ON quiz_sessions FOR INSERT TO authenticated WITH CHECK (auth.uid() = teacher_id);
CREATE POLICY "Update sessions" ON quiz_sessions FOR UPDATE TO authenticated USING (auth.uid() = teacher_id);

-- quiz_questions
ALTER TABLE quiz_questions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Read questions" ON quiz_questions;
CREATE POLICY "Read questions" ON quiz_questions FOR SELECT TO authenticated USING (true);

-- quiz_responses
ALTER TABLE quiz_responses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Submit response" ON quiz_responses;
DROP POLICY IF EXISTS "Read responses"  ON quiz_responses;
CREATE POLICY "Submit response" ON quiz_responses FOR INSERT TO authenticated WITH CHECK (auth.uid() = student_id);
CREATE POLICY "Read responses"  ON quiz_responses FOR SELECT TO authenticated USING (true);

-- mock_questions
ALTER TABLE mock_questions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Authenticated users read mock_questions" ON mock_questions;
CREATE POLICY "Authenticated users read mock_questions" ON mock_questions FOR SELECT TO authenticated USING (true);


-- ═══════════════════════════════════════════════════
-- VERIFY: All tables should show rls_enabled = true
-- AND each should have at least one policy
-- ═══════════════════════════════════════════════════
SELECT
    t.tablename,
    t.rowsecurity AS rls_enabled,
    COUNT(p.policyname) AS policy_count
FROM pg_tables t
LEFT JOIN pg_policies p ON p.tablename = t.tablename AND p.schemaname = 'public'
WHERE t.schemaname = 'public'
GROUP BY t.tablename, t.rowsecurity
ORDER BY t.tablename;
