-- Apply after the learning-credit and chat-reliability migrations.
-- Daily reply counts are reporting counters, not access entitlements.
BEGIN;
CREATE OR REPLACE FUNCTION public.reserve_chat_request(target_user_id uuid, target_session_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE p jsonb; used integer; request_id uuid;
BEGIN
    p := public.reset_daily_usage(target_user_id);
    IF p IS NULL THEN RETURN jsonb_build_object('error','profile'); END IF;
    IF NOT EXISTS (SELECT 1 FROM public.chat_sessions
        WHERE id=target_session_id AND user_id=target_user_id) THEN
        RETURN jsonb_build_object('error','session');
    END IF;
    SELECT count(*) INTO used FROM public.ai_chat_requests
        WHERE user_id=target_user_id AND session_id=target_session_id;
    IF used >= 10 THEN RETURN jsonb_build_object('error','conversation_limit'); END IF;
    -- Credit admission and subscription validity are checked separately by
    -- begin_learning_credit_request before any generation starts.
    INSERT INTO public.ai_chat_requests(user_id,session_id)
        VALUES(target_user_id,target_session_id) RETURNING id INTO request_id;
    UPDATE public.profiles SET chats_today=coalesce(chats_today,0)+1 WHERE id=target_user_id;
    RETURN jsonb_build_object('request_id',request_id,'turns_used',used+1);
END $$;
REVOKE ALL ON FUNCTION public.reserve_chat_request(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_chat_request(uuid,uuid) TO service_role;
COMMIT;
