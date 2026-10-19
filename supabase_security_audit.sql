-- Apply LAST, after existing application migrations. Deploy with quiz_security.py
-- and the private-image Flutter client. Existing chat images become private.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

CREATE TABLE IF NOT EXISTS public.quiz_participants (
    session_id uuid NOT NULL REFERENCES public.quiz_sessions(id) ON DELETE CASCADE,
    student_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    admitted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, student_id)
);
CREATE INDEX IF NOT EXISTS quiz_participants_quota ON public.quiz_participants(student_id, admitted_at);
INSERT INTO public.quiz_participants(session_id,student_id,admitted_at)
SELECT session_id,student_id,min(created_at) FROM public.quiz_responses
WHERE session_id IS NOT NULL AND student_id IS NOT NULL GROUP BY session_id,student_id
ON CONFLICT DO NOTHING;
ALTER TABLE public.quiz_participants ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.quiz_participants FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.quiz_participants TO authenticated;
GRANT ALL ON public.quiz_participants TO service_role;
DROP POLICY IF EXISTS "Own quiz admission" ON public.quiz_participants;
CREATE POLICY "Own quiz admission" ON public.quiz_participants FOR SELECT TO authenticated USING(student_id=auth.uid());

-- Replace permissive policies while preserving existing restrictive launch gates.
DO $$ DECLARE p record; BEGIN
 FOR p IN SELECT policyname FROM pg_policies WHERE schemaname='public' AND tablename='quiz_sessions' AND permissive='PERMISSIVE' LOOP
  EXECUTE format('DROP POLICY %I ON public.quiz_sessions',p.policyname);
 END LOOP;
END $$;
ALTER TABLE public.quiz_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.quiz_sessions FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.quiz_sessions TO authenticated;
GRANT ALL ON public.quiz_sessions TO service_role;
CREATE POLICY "Authorized quiz sessions" ON public.quiz_sessions FOR SELECT TO authenticated
 USING(teacher_id=auth.uid() OR EXISTS(SELECT 1 FROM public.quiz_participants p WHERE p.session_id=quiz_sessions.id AND p.student_id=auth.uid()));

-- New participant rows must observe the same pre-launch restriction as existing tables.
DO $$ BEGIN
 IF to_regprocedure('public.app_launch_allowed()') IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='quiz_participants' AND policyname='arivora_prelaunch_gate') THEN
  CREATE POLICY arivora_prelaunch_gate ON public.quiz_participants AS RESTRICTIVE FOR ALL TO anon,authenticated
   USING((SELECT public.app_launch_allowed())) WITH CHECK((SELECT public.app_launch_allowed()));
 END IF;
END $$;

ALTER TABLE public.quiz_questions ADD COLUMN IF NOT EXISTS timer_seconds integer NOT NULL DEFAULT 60;
ALTER TABLE public.quiz_questions ADD COLUMN IF NOT EXISTS timer_mode text NOT NULL DEFAULT 'manual';

CREATE OR REPLACE FUNCTION public.secure_create_live_quiz(uid uuid,title_value text,questions_value jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE tier text; amount integer; allowed integer; since_value timestamptz;
 sid uuid; code text; q jsonb; idx integer:=0;
BEGIN
 IF title_value IS NULL OR length(trim(title_value)) NOT BETWEEN 1 AND 255
 OR jsonb_typeof(questions_value) IS DISTINCT FROM 'array' THEN RETURN jsonb_build_object('error','invalid'); END IF;
 IF jsonb_array_length(questions_value) NOT BETWEEN 1 AND 50 THEN RETURN jsonb_build_object('error','invalid'); END IF;
 -- Same per-account lock serializes all hosting/admission reservations.
 SELECT CASE WHEN subscription_tier='admin' THEN 'admin'
     WHEN subscription_tier IN ('tier_199','tier_499','tier_999') AND subscription_expires_at>now() THEN subscription_tier
     ELSE 'free' END INTO tier FROM public.profiles WHERE id=uid FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 since_value := date_trunc(CASE WHEN tier='free' THEN 'month' ELSE 'day' END,now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata';
 allowed := CASE tier WHEN 'admin' THEN 2147483647 WHEN 'free' THEN 1 WHEN 'tier_199' THEN 3 ELSE 5 END;
 SELECT count(*) INTO amount FROM public.quiz_sessions WHERE teacher_id=uid AND created_at>=since_value;
 IF amount>=allowed THEN RETURN jsonb_build_object('error','quota'); END IF;
 -- UUID entropy, unique constraint, and bounded collision retry.
 FOR attempt IN 1..10 LOOP
  code := '';
  FOR position IN 0..5 LOOP
   code := code || substr('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',1+(get_byte(uuid_send(gen_random_uuid()),0)%36),1);
  END LOOP;
  BEGIN
   INSERT INTO public.quiz_sessions(session_code,teacher_id,title,status,current_question_index)
   VALUES(code,uid,title_value,'waiting',-1) RETURNING id INTO sid;
   EXIT;
  EXCEPTION WHEN unique_violation THEN
   IF attempt=10 THEN RAISE; END IF;
  END;
 END LOOP;
 FOR q IN SELECT value FROM jsonb_array_elements(questions_value) LOOP
  -- A raised error rolls back the session as well as every question.
  IF length(trim(coalesce(q->>'question_text',''))) NOT BETWEEN 1 AND 2000
    OR length(trim(coalesce(q->>'correct_answer',''))) NOT BETWEEN 1 AND 500
    OR coalesce(q->>'question_type','') NOT IN ('mcq','fill_blank')
    OR coalesce((q->>'points')::integer,1) NOT BETWEEN 1 AND 100
    OR coalesce((q->>'timer_seconds')::integer,60) NOT BETWEEN 5 AND 600
    OR coalesce(q->>'timer_mode','manual') NOT IN ('auto','manual') THEN
   RAISE EXCEPTION 'Invalid quiz question';
  END IF;
  IF q->>'question_type'='mcq' THEN
   IF jsonb_typeof(q->'options') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'Invalid quiz options'; END IF;
   IF jsonb_array_length(q->'options') NOT BETWEEN 2 AND 4
      OR NOT (q->'options' @> jsonb_build_array(q->>'correct_answer'))
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(q->'options') o WHERE jsonb_typeof(o)<>'string' OR length(trim(o#>>'{}')) NOT BETWEEN 1 AND 500) THEN
    RAISE EXCEPTION 'Invalid quiz options';
   END IF;
  END IF;
  INSERT INTO public.quiz_questions(session_id,question_text,question_type,options,correct_answer,points,sort_order,timer_seconds,timer_mode)
  VALUES(sid,q->>'question_text',q->>'question_type',q->'options',q->>'correct_answer',coalesce((q->>'points')::integer,1),idx,coalesce((q->>'timer_seconds')::integer,60),coalesce(q->>'timer_mode','manual'));
  idx:=idx+1;
 END LOOP;
 RETURN jsonb_build_object('session_id',sid,'session_code',code,'title',title_value,'question_count',idx);
END $$;

CREATE OR REPLACE FUNCTION public.secure_join_live_quiz(uid uuid,code_value text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.quiz_sessions%ROWTYPE; tier text; allowed integer; amount integer;
 since_value timestamptz; questions jsonb;
BEGIN
 -- An admitted GET is idempotent. New admissions consume quota before answers.
 SELECT CASE WHEN subscription_tier='admin' THEN 'admin'
     WHEN subscription_tier IN ('tier_199','tier_499','tier_999') AND subscription_expires_at>now() THEN subscription_tier
     ELSE 'free' END INTO tier FROM public.profiles WHERE id=uid FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 SELECT * INTO s FROM public.quiz_sessions WHERE session_code=upper(code_value) FOR SHARE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF s.teacher_id IS DISTINCT FROM uid AND NOT EXISTS(SELECT 1 FROM public.quiz_participants WHERE session_id=s.id AND student_id=uid) THEN
  IF s.status='completed' THEN RETURN jsonb_build_object('error','forbidden'); END IF;
  since_value:=date_trunc(CASE WHEN tier='free' THEN 'month' ELSE 'day' END,now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata';
  allowed:=CASE tier WHEN 'admin' THEN 2147483647 WHEN 'free' THEN 3 WHEN 'tier_199' THEN 10 ELSE 15 END;
  SELECT count(*) INTO amount FROM public.quiz_participants WHERE student_id=uid AND admitted_at>=since_value;
  IF amount>=allowed THEN RETURN jsonb_build_object('error','quota'); END IF;
  INSERT INTO public.quiz_participants(session_id,student_id) VALUES(s.id,uid);
 END IF;
 SELECT coalesce(jsonb_agg(CASE WHEN s.teacher_id=uid THEN to_jsonb(q) ELSE to_jsonb(q)-'correct_answer' END ORDER BY q.sort_order),'[]'::jsonb)
 INTO questions FROM public.quiz_questions q WHERE q.session_id=s.id;
 RETURN to_jsonb(s)||jsonb_build_object('questions',questions,'is_teacher',s.teacher_id=uid);
END $$;

CREATE OR REPLACE FUNCTION public.secure_answer_live_quiz(uid uuid,code_value text,question_value uuid,answer_value text,name_value text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.quiz_sessions%ROWTYPE; q public.quiz_questions%ROWTYPE; correct boolean;
BEGIN
 IF length(trim(coalesce(answer_value,''))) NOT BETWEEN 1 AND 500 OR length(trim(coalesce(name_value,''))) NOT BETWEEN 1 AND 100 THEN RETURN jsonb_build_object('error','invalid'); END IF;
 -- Hold the session through scoring, preventing teacher transitions during a write.
 SELECT * INTO s FROM public.quiz_sessions WHERE session_code=upper(code_value) FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF NOT EXISTS(SELECT 1 FROM public.quiz_participants WHERE session_id=s.id AND student_id=uid) THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 SELECT * INTO q FROM public.quiz_questions WHERE id=question_value AND session_id=s.id;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF s.status<>'active' OR q.sort_order<>s.current_question_index THEN RETURN jsonb_build_object('error','inactive'); END IF;
 correct:=CASE WHEN q.question_type='fill_blank' THEN lower(trim(answer_value))=lower(trim(q.correct_answer)) ELSE trim(answer_value)=trim(q.correct_answer) END;
 BEGIN
  INSERT INTO public.quiz_responses(session_id,student_id,student_name,question_id,submitted_answer,is_correct)
  VALUES(s.id,uid,trim(name_value),q.id,trim(answer_value),correct);
 EXCEPTION WHEN unique_violation THEN RETURN jsonb_build_object('error','duplicate'); END;
 -- Do not reveal the answer while other students can still submit.
 RETURN jsonb_build_object('is_correct',correct);
END $$;

CREATE OR REPLACE FUNCTION public.secure_live_leaderboard(uid uuid,code_value text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.quiz_sessions%ROWTYPE; result jsonb;
BEGIN
 SELECT * INTO s FROM public.quiz_sessions WHERE session_code=upper(code_value);
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF s.teacher_id IS DISTINCT FROM uid AND NOT EXISTS(SELECT 1 FROM public.quiz_participants WHERE session_id=s.id AND student_id=uid) THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) INTO result FROM public.get_session_leaderboard(s.id) r;
 RETURN jsonb_build_object('leaderboard',result);
END $$;

DO $$ DECLARE fn record; BEGIN
 FOR fn IN SELECT p.oid::regprocedure signature FROM pg_proc p JOIN pg_namespace n ON p.pronamespace=n.oid
 WHERE n.nspname='public' AND p.proname IN ('secure_create_live_quiz','secure_join_live_quiz','secure_answer_live_quiz','secure_live_leaderboard','get_session_leaderboard') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated',fn.signature);
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role',fn.signature);
 END LOOP;
END $$;

-- Private images: callers can only access their UUID-scoped upload directory.
-- Legacy flat objects remain private; ownership cannot safely be inferred.
UPDATE storage.buckets SET public=false, file_size_limit=5242880,
 allowed_mime_types=ARRAY['image/jpeg','image/png','image/webp'] WHERE id='chat-images';
-- Restrictive policies guard against pre-existing permissive policies on storage.
DROP POLICY IF EXISTS "Chat image owner guard" ON storage.objects;
CREATE POLICY "Chat image owner guard" ON storage.objects AS RESTRICTIVE FOR ALL TO anon,authenticated
 USING(bucket_id<>'chat-images' OR (auth.uid() IS NOT NULL AND (storage.foldername(name))[1]='chat_uploads' AND (storage.foldername(name))[2]=auth.uid()::text))
 WITH CHECK(bucket_id<>'chat-images' OR (auth.uid() IS NOT NULL AND (storage.foldername(name))[1]='chat_uploads' AND (storage.foldername(name))[2]=auth.uid()::text));
DROP POLICY IF EXISTS "Own private chat images" ON storage.objects;
CREATE POLICY "Own private chat images" ON storage.objects FOR ALL TO authenticated
 USING(bucket_id='chat-images' AND (storage.foldername(name))[1]='chat_uploads' AND (storage.foldername(name))[2]=auth.uid()::text)
 WITH CHECK(bucket_id='chat-images' AND (storage.foldername(name))[1]='chat_uploads' AND (storage.foldername(name))[2]=auth.uid()::text);
NOTIFY pgrst,'reload schema';
COMMIT;
