-- =====================================================
-- Tutor Preethi — SECURITY FIX: Enable RLS on all tables
-- Run this in Supabase SQL Editor to resolve the
-- "Table publicly accessible" security vulnerability
-- Safe to re-run (idempotent)
-- =====================================================


-- ═══════════════════════════════════════════════════
-- TABLE: profiles
-- Each user can only read/update their own profile.
-- The backend (service role key) bypasses RLS for
-- admin-level writes like subscription updates.
-- ═══════════════════════════════════════════════════
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own profile"   ON profiles;
DROP POLICY IF EXISTS "Users update own profile" ON profiles;
DROP POLICY IF EXISTS "Users insert own profile" ON profiles;

-- Users can only read their own profile row
CREATE POLICY "Users read own profile"
    ON profiles FOR SELECT
    TO authenticated
    USING (auth.uid() = id);

-- Users can update their own profile (e.g. display name)
CREATE POLICY "Users update own profile"
    ON profiles FOR UPDATE
    TO authenticated
    USING (auth.uid() = id);

-- Allow new profile creation on sign-up (trigger or client)
CREATE POLICY "Users insert own profile"
    ON profiles FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = id);


-- ═══════════════════════════════════════════════════
-- TABLE: documents
-- Textbook content — readable by all authenticated
-- users (needed for chat/quiz context lookups).
-- Nobody should be able to write via the client.
-- All writes go through the backend service role key.
-- ═══════════════════════════════════════════════════
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Authenticated users read documents" ON documents;

-- All logged-in users can read textbook chunks (for RAG)
CREATE POLICY "Authenticated users read documents"
    ON documents FOR SELECT
    TO authenticated
    USING (true);

-- No INSERT / UPDATE / DELETE allowed from client side.
-- The backend uses the service-role key which bypasses RLS.


-- ═══════════════════════════════════════════════════
-- TABLE: quiz_sessions
-- ═══════════════════════════════════════════════════
ALTER TABLE quiz_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Read sessions"   ON quiz_sessions;
DROP POLICY IF EXISTS "Create sessions" ON quiz_sessions;
DROP POLICY IF EXISTS "Update sessions" ON quiz_sessions;

CREATE POLICY "Read sessions"
    ON quiz_sessions FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Create sessions"
    ON quiz_sessions FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = teacher_id);

CREATE POLICY "Update sessions"
    ON quiz_sessions FOR UPDATE
    TO authenticated
    USING (auth.uid() = teacher_id);


-- ═══════════════════════════════════════════════════
-- TABLE: quiz_questions
-- ═══════════════════════════════════════════════════
ALTER TABLE quiz_questions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Read questions" ON quiz_questions;

CREATE POLICY "Read questions"
    ON quiz_questions FOR SELECT
    TO authenticated
    USING (true);

-- INSERT is done via backend service role key (bypasses RLS).


-- ═══════════════════════════════════════════════════
-- TABLE: quiz_responses
-- ═══════════════════════════════════════════════════
ALTER TABLE quiz_responses ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Submit response" ON quiz_responses;
DROP POLICY IF EXISTS "Read responses"  ON quiz_responses;

CREATE POLICY "Submit response"
    ON quiz_responses FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = student_id);

CREATE POLICY "Read responses"
    ON quiz_responses FOR SELECT
    TO authenticated
    USING (true);


-- ═══════════════════════════════════════════════════
-- VERIFY — run this SELECT after applying the script
-- to confirm RLS is ON for all tables
-- ═══════════════════════════════════════════════════
SELECT
    schemaname,
    tablename,
    rowsecurity  AS rls_enabled
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
