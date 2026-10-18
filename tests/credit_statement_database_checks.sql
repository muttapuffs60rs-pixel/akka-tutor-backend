BEGIN;
DO $$
DECLARE uid uuid:=gen_random_uuid(); sid uuid; rid uuid; eid uuid; receipt jsonb; tier text; expected bigint; saved bigint;
BEGIN
 INSERT INTO auth.users(id,aud,role,email,raw_user_meta_data,created_at,updated_at)
 VALUES(uid,'authenticated','authenticated',uid::text||'@example.invalid','{}',now(),now());
 INSERT INTO public.profiles(id,subscription_tier) VALUES(uid,'free') ON CONFLICT(id) DO NOTHING;
 PERFORM public.learning_credit_balance(uid);
 INSERT INTO public.chat_sessions(user_id,title,board,grade_level,subject) VALUES(uid,'Synthetic statement check','tn',10,'Maths') RETURNING id INTO sid;
 FOREACH tier IN ARRAY ARRAY['free','tier_199'] LOOP
  UPDATE public.profiles SET subscription_tier=tier WHERE id=uid;
  eid:=gen_random_uuid();
  receipt:=public.reserve_chat_request_v2(uid,sid,gen_random_uuid(),repeat('a',64),eid);
  rid:=(receipt->>'request_id')::uuid;
  PERFORM public.claim_chat_generation(uid,rid,eid);
  PERFORM public.begin_learning_credit_request(uid,rid);
  PERFORM public.finish_learning_credit_request(uid,rid,eid,'{"status":"complete","input_tokens":100,"output_tokens":200,"response_source":"model"}'::jsonb);
  SELECT credit_balance_after INTO saved FROM public.ai_chat_requests WHERE id=rid;
  IF tier='free' THEN expected:=((public.learning_credit_balance(uid))->>'remaining')::bigint;
  ELSE expected:=1250000-600; END IF;
  IF saved IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Snapshot mismatch %: % expected %',tier,saved,expected; END IF;
  PERFORM public.finish_learning_credit_request(uid,rid,eid,'{"status":"complete","input_tokens":999,"output_tokens":999}'::jsonb);
  IF (SELECT credit_balance_after FROM public.ai_chat_requests WHERE id=rid) IS DISTINCT FROM saved THEN RAISE EXCEPTION 'Replay changed snapshot'; END IF;
 END LOOP;
 IF has_function_privilege('authenticated','public.capture_credit_balance_after()','EXECUTE') THEN RAISE EXCEPTION 'Client access expanded'; END IF;
END $$;
ROLLBACK;
SELECT 'PASS: free and paid settled snapshots, replay stability and restricted access; synthetic records rolled back.' AS result;
