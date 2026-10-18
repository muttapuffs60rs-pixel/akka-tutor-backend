BEGIN;
DO $$
DECLARE uid uuid:=gen_random_uuid(); sid uuid;
    receipt jsonb; replay jsonb; client_key uuid:=gen_random_uuid();
    tier text; n integer; before_count integer;
BEGIN
    INSERT INTO auth.users(id,aud,role,email,raw_user_meta_data,created_at,updated_at)
      VALUES(uid,'authenticated','authenticated',uid::text||'@example.invalid','{}',now(),now());
    INSERT INTO public.profiles(id,subscription_tier) VALUES(uid,'free') ON CONFLICT(id) DO NOTHING;
    FOREACH tier IN ARRAY ARRAY['free','tier_199','tier_499','tier_999'] LOOP
      UPDATE public.profiles SET subscription_tier=tier,chats_today=1000000,
        last_active_date=(now() AT TIME ZONE 'Asia/Kolkata')::date WHERE id=uid;
      INSERT INTO public.chat_sessions(user_id,title,board,grade_level,subject)
        VALUES(uid,'Synthetic credit access check','tn',10,'Maths') RETURNING id INTO sid;
      receipt:=public.reserve_chat_request_v2(uid,sid,client_key,repeat('a',64),gen_random_uuid());
      IF receipt ? 'error' THEN RAISE EXCEPTION 'Daily count still blocks tier %: %',tier,receipt; END IF;
      SELECT chats_today INTO before_count FROM public.profiles WHERE id=uid;
      replay:=public.reserve_chat_request_v2(uid,sid,client_key,repeat('a',64),gen_random_uuid());
      IF replay->>'request_id'<>receipt->>'request_id' OR
        (SELECT chats_today FROM public.profiles WHERE id=uid)<>before_count THEN
        RAISE EXCEPTION 'Replay is no longer idempotent'; END IF;
      FOR n IN 2..10 LOOP
        receipt:=public.reserve_chat_request(uid,sid);
        IF receipt ? 'error' THEN RAISE EXCEPTION 'Reservation failed: %',receipt; END IF;
      END LOOP;
      receipt:=public.reserve_chat_request(uid,sid);
      IF receipt->>'error' IS DISTINCT FROM 'conversation_limit' THEN
        RAISE EXCEPTION 'Conversation boundary lost'; END IF;
      receipt:=public.reserve_chat_request(uid,gen_random_uuid());
      IF receipt->>'error' IS DISTINCT FROM 'session' THEN RAISE EXCEPTION 'Session validation lost'; END IF;
      client_key:=gen_random_uuid();
    END LOOP;
    IF has_function_privilege('authenticated','public.reserve_chat_request(uuid,uuid)','EXECUTE')
      OR has_function_privilege('anon','public.reserve_chat_request(uuid,uuid)','EXECUTE') THEN
      RAISE EXCEPTION 'Client permissions expanded'; END IF;
END $$;
ROLLBACK;
SELECT 'PASS: all tiers admit requests past former daily caps; replay, session ownership, conversation boundary and permissions preserved. Synthetic records rolled back.' AS result;
