-- Additive migration. Existing clients/RPC remain valid during deployment.
BEGIN;
ALTER TABLE public.ai_chat_requests
    ADD COLUMN IF NOT EXISTS client_request_id uuid,
    ADD COLUMN IF NOT EXISTS payload_hash text,
    ADD COLUMN IF NOT EXISTS execution_id uuid,
    ADD COLUMN IF NOT EXISTS turns_used integer,
    ADD COLUMN IF NOT EXISTS response_text text,
    ADD COLUMN IF NOT EXISTS response_expires_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS ai_chat_requests_client_id_idx
    ON public.ai_chat_requests(user_id, client_request_id)
    WHERE client_request_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.reserve_chat_request_v2(
    target_user_id uuid, target_session_id uuid, target_client_request_id uuid,
    target_payload_hash text, target_execution_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE existing public.ai_chat_requests%ROWTYPE; reservation jsonb;
BEGIN
    IF target_client_request_id IS NULL OR target_execution_id IS NULL
       OR target_payload_hash IS NULL OR length(target_payload_hash) <> 64 THEN
        RETURN jsonb_build_object('error','invalid_request');
    END IF;
    -- Serializes this user/key across processes and uncertain-commit retries.
    PERFORM pg_advisory_xact_lock(hashtextextended(target_user_id::text || target_client_request_id::text, 0));
    SELECT * INTO existing FROM public.ai_chat_requests
        WHERE user_id=target_user_id AND client_request_id=target_client_request_id;
    IF FOUND THEN
        IF existing.session_id <> target_session_id OR existing.payload_hash <> target_payload_hash THEN
            RETURN jsonb_build_object('error','request_conflict');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.chat_sessions WHERE id=target_session_id AND user_id=target_user_id) THEN
            RETURN jsonb_build_object('error','session');
        END IF;
        RETURN jsonb_build_object('request_id',existing.id,'turns_used',existing.turns_used,
            'status',existing.status,'same_execution',existing.execution_id=target_execution_id,
            'response_text',CASE WHEN existing.response_expires_at > now() THEN existing.response_text ELSE NULL END,
            'response_source',existing.response_source,'answer_cache_id',existing.answer_cache_id,
            'stale',existing.created_at < now()-interval '10 minutes');
    END IF;
    reservation := public.reserve_chat_request(target_user_id,target_session_id);
    IF reservation ? 'error' THEN RETURN reservation; END IF;
    UPDATE public.ai_chat_requests SET client_request_id=target_client_request_id,
        payload_hash=target_payload_hash, execution_id=target_execution_id,
        turns_used=(reservation->>'turns_used')::integer
        WHERE id=(reservation->>'request_id')::uuid;
    RETURN reservation || jsonb_build_object('same_execution',true,'status','reserved');
END $$;
REVOKE ALL ON FUNCTION public.reserve_chat_request_v2(uuid,uuid,uuid,text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_chat_request_v2(uuid,uuid,uuid,text,uuid) TO service_role;

-- Reservation and generation are separate: a retry may recover a reservation
-- whose response was lost, but never start a second running generation.
CREATE OR REPLACE FUNCTION public.claim_chat_generation(
    target_user_id uuid, target_request_id uuid, target_execution_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE existing public.ai_chat_requests%ROWTYPE;
BEGIN
    SELECT * INTO existing FROM public.ai_chat_requests
        WHERE id=target_request_id AND user_id=target_user_id FOR UPDATE;
    IF NOT FOUND OR target_execution_id IS NULL THEN
        RETURN jsonb_build_object('claimed',false);
    END IF;
    IF existing.status='reserved' THEN
        UPDATE public.ai_chat_requests SET status='processing',execution_id=target_execution_id
            WHERE id=target_request_id;
        RETURN jsonb_build_object('claimed',true);
    END IF;
    RETURN jsonb_build_object('claimed',existing.status='processing' AND existing.execution_id=target_execution_id);
END $$;
REVOKE ALL ON FUNCTION public.claim_chat_generation(uuid,uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_chat_generation(uuid,uuid,uuid) TO service_role;

-- Replay text has a short lifetime; the token/accounting ledger remains unchanged.
SELECT cron.schedule('expire-chat-replays','17 * * * *',
    $job$UPDATE public.ai_chat_requests SET response_text=NULL,response_expires_at=NULL
          WHERE response_expires_at < now();$job$);
COMMIT;
