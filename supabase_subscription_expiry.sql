-- Apply after supabase_learning_credits.sql. No balances or payment records are changed.
BEGIN;
CREATE OR REPLACE FUNCTION public.begin_learning_credit_request(target_user_id uuid,target_request_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE balance jsonb; w public.learning_credit_wallets%ROWTYPE; tier text; base_remaining bigint; plan_limit bigint;
BEGIN
    SELECT subscription_tier INTO tier FROM public.profiles WHERE id=target_user_id;
    IF NOT FOUND THEN RETURN jsonb_build_object('error','profile'); END IF;
    -- A stale paid tier must never authorize answers after its expiry.
    IF coalesce(tier,'free') <> 'free' AND EXISTS (
        SELECT 1 FROM public.profiles WHERE id=target_user_id
        AND subscription_expires_at <= now()
    ) THEN
        IF NOT EXISTS (SELECT 1 FROM public.learning_credit_topups
            WHERE user_id=target_user_id AND expires_at>now() AND remaining>0) THEN
            RETURN jsonb_build_object('error','subscription_expired');
        END IF;
        tier := 'free';
    END IF;
    balance := public.learning_credit_balance(target_user_id);
    SELECT * INTO w FROM public.learning_credit_wallets WHERE user_id=target_user_id FOR UPDATE;
    IF NOT EXISTS (SELECT 1 FROM public.ai_chat_requests WHERE id=target_request_id AND user_id=target_user_id
        AND status='processing' AND learning_credits_charged IS NULL) THEN
        RETURN jsonb_build_object('error','request_ended');
    END IF;
    IF w.active_request IS NOT NULL AND w.active_request<>target_request_id
        AND w.active_since > now()-interval '10 minutes' THEN
        RETURN jsonb_build_object('error','credit_busy');
    END IF;
    IF coalesce(tier,'free')='free' AND (balance->>'remaining')::bigint <= 0 THEN RETURN jsonb_build_object('error','credit_limit'); END IF;
    plan_limit := CASE tier WHEN 'tier_199' THEN 3000000 WHEN 'tier_499' THEN 5000000
        WHEN 'tier_999' THEN 8000000 ELSE 9223372036854775807 END;
    SELECT greatest(0,plan_limit-coalesce(sum(coalesce(learning_credits_charged,
        coalesce(input_tokens,0)+coalesce(output_tokens,0)+coalesce(vision_input_tokens,0)+coalesce(vision_output_tokens,0))
        -coalesce(topup_credits_charged,0)),0)) INTO base_remaining
        FROM public.ai_chat_requests WHERE user_id=target_user_id
        AND created_at >= coalesce((SELECT subscription_start_date FROM public.profiles WHERE id=target_user_id),
            (date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata'));
    UPDATE public.learning_credit_wallets SET active_request=target_request_id,active_since=now(),
        active_paid=coalesce(tier,'free')<>'free',active_base_remaining=base_remaining
        WHERE user_id=target_user_id;
    RETURN balance || jsonb_build_object('enabled',coalesce(tier,'free')='free');
END $$;
REVOKE ALL ON FUNCTION public.begin_learning_credit_request(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.begin_learning_credit_request(uuid,uuid) TO service_role;
COMMIT;
