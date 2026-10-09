-- Apply after supabase_app_hardening.sql, before deploying the new /ask client/server.
BEGIN;
CREATE TABLE IF NOT EXISTS public.ai_chat_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Deliberately not cascaded when a conversation is deleted: retain its cost ledger.
    session_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'reserved',
    input_tokens bigint,
    output_tokens bigint,
    vision_input_tokens bigint,
    vision_output_tokens bigint
);
CREATE INDEX IF NOT EXISTS ai_chat_requests_session_idx
    ON public.ai_chat_requests(user_id, session_id);
ALTER TABLE public.ai_chat_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ai_chat_requests FROM anon, authenticated;
GRANT ALL ON public.ai_chat_requests TO service_role;

-- Seed existing conversation lengths once. These are not measured token usage.
INSERT INTO public.ai_chat_requests(user_id, session_id, status)
SELECT s.user_id, s.id, 'legacy_unmetered'
FROM public.chat_sessions s
CROSS JOIN LATERAL (
    SELECT LEAST(count(*), 10)::integer AS turns FROM public.chat_messages m
    WHERE m.session_id = s.id AND m.user_id = s.user_id AND m.is_user = true
) history
CROSS JOIN LATERAL generate_series(1, history.turns) AS turn_number
WHERE NOT EXISTS (SELECT 1 FROM public.ai_chat_requests r WHERE r.session_id = s.id AND r.user_id = s.user_id);

CREATE OR REPLACE FUNCTION public.reserve_chat_request(target_user_id uuid, target_session_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE p jsonb; used integer; daily_limit integer; request_id uuid;
BEGIN
    -- reset_daily_usage takes the profile lock; hold it until this transaction ends.
    p := public.reset_daily_usage(target_user_id);
    IF p IS NULL THEN RETURN jsonb_build_object('error', 'profile'); END IF;
    IF NOT EXISTS (SELECT 1 FROM public.chat_sessions
        WHERE id = target_session_id AND user_id = target_user_id) THEN
        RETURN jsonb_build_object('error', 'session');
    END IF;
    SELECT count(*) INTO used FROM public.ai_chat_requests
        WHERE user_id = target_user_id AND session_id = target_session_id;
    IF used >= 10 THEN RETURN jsonb_build_object('error', 'conversation_limit'); END IF;
    daily_limit := CASE p->>'subscription_tier'
        WHEN 'tier_199' THEN 50 WHEN 'tier_499' THEN 150 WHEN 'tier_999' THEN 150
        WHEN 'tier_49_daily' THEN 999999 WHEN 'admin' THEN 999999 ELSE 5 END;
    IF COALESCE((p->>'chats_today')::integer, 0) >= daily_limit THEN
        RETURN jsonb_build_object('error', 'daily_limit');
    END IF;
    INSERT INTO public.ai_chat_requests(user_id, session_id)
        VALUES(target_user_id, target_session_id) RETURNING id INTO request_id;
    UPDATE public.profiles SET chats_today = COALESCE(chats_today, 0) + 1
        WHERE id = target_user_id;
    RETURN jsonb_build_object('request_id', request_id, 'turns_used', used + 1);
END $$;
REVOKE ALL ON FUNCTION public.reserve_chat_request(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_chat_request(uuid, uuid) TO service_role;
COMMIT;
