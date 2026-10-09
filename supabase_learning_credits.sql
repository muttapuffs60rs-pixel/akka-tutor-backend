-- Apply AFTER supabase_chat_reliability.sql, BEFORE deploying learning_credits.py.
BEGIN;
CREATE TABLE IF NOT EXISTS public.learning_credit_policy (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    welcome_from timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.learning_credit_policy(singleton) VALUES(true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.learning_credit_wallets (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    credit_date date NOT NULL,
    daily_remaining bigint NOT NULL DEFAULT 15000,
    welcome_remaining bigint NOT NULL DEFAULT 0 CHECK(welcome_remaining BETWEEN 0 AND 50000),
    active_request uuid,
    active_since timestamptz
);
ALTER TABLE public.ai_chat_requests ADD COLUMN IF NOT EXISTS learning_credits_charged bigint;
ALTER TABLE public.ai_chat_requests ADD COLUMN IF NOT EXISTS topup_credits_charged bigint DEFAULT 0;
ALTER TABLE public.learning_credit_wallets ADD COLUMN IF NOT EXISTS active_paid boolean DEFAULT false;
ALTER TABLE public.learning_credit_wallets ADD COLUMN IF NOT EXISTS active_base_remaining bigint DEFAULT 0;
CREATE TABLE IF NOT EXISTS public.learning_credit_topups (
    payment_id text PRIMARY KEY, order_id text UNIQUE NOT NULL,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    remaining bigint NOT NULL DEFAULT 200000 CHECK(remaining BETWEEN 0 AND 200000),
    granted_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT (now()+interval '30 days')
);
ALTER TABLE public.learning_credit_topups ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.learning_credit_topups FROM PUBLIC,anon,authenticated;
GRANT ALL ON public.learning_credit_topups TO service_role;
CREATE INDEX IF NOT EXISTS learning_credit_topups_user_expiry ON public.learning_credit_topups(user_id,expires_at);
CREATE OR REPLACE FUNCTION public.grant_learning_credit_topup(target_user_id uuid,payment_id_value text,order_id_value text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE pack public.learning_credit_topups%ROWTYPE;
BEGIN
    IF length(coalesce(payment_id_value,'')) < 3 OR length(coalesce(order_id_value,'')) < 3 THEN
        RAISE EXCEPTION 'Invalid verified payment identity';
    END IF;
    INSERT INTO public.learning_credit_topups(payment_id,order_id,user_id)
        VALUES(payment_id_value,order_id_value,target_user_id) ON CONFLICT DO NOTHING;
    SELECT * INTO pack FROM public.learning_credit_topups WHERE payment_id=payment_id_value;
    IF NOT FOUND OR pack.user_id<>target_user_id OR pack.order_id<>order_id_value THEN
        RAISE EXCEPTION 'Payment grant conflict';
    END IF;
    RETURN jsonb_build_object('credits',200000,'remaining',pack.remaining,'expires_at',pack.expires_at);
END $$;
REVOKE ALL ON FUNCTION public.grant_learning_credit_topup(uuid,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.grant_learning_credit_topup(uuid,text,text) TO service_role;

ALTER TABLE public.learning_credit_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.learning_credit_wallets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.learning_credit_policy, public.learning_credit_wallets FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.learning_credit_policy, public.learning_credit_wallets TO service_role;

CREATE OR REPLACE FUNCTION public.learning_credit_balance(target_user_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE w public.learning_credit_wallets%ROWTYPE;
    today date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
BEGIN
    INSERT INTO public.learning_credit_wallets(user_id,credit_date,welcome_remaining)
    SELECT u.id,today,CASE WHEN u.created_at >= p.welcome_from THEN 50000 ELSE 0 END
    FROM auth.users u CROSS JOIN public.learning_credit_policy p WHERE u.id=target_user_id
    ON CONFLICT DO NOTHING;
    SELECT * INTO w FROM public.learning_credit_wallets WHERE user_id=target_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'User not found'; END IF;
    IF w.credit_date < today AND NOT (w.active_request IS NOT NULL AND w.active_since > now()-interval '10 minutes') THEN
        -- Daily credits never accumulate. Carry an in-progress answer's overrun.
        UPDATE public.learning_credit_wallets SET credit_date=today,
            daily_remaining=15000 + least(daily_remaining,0) WHERE user_id=target_user_id;
    END IF;
    SELECT * INTO w FROM public.learning_credit_wallets WHERE user_id=target_user_id;
    RETURN jsonb_build_object('daily_remaining',greatest(w.daily_remaining,0),
        'welcome_remaining',w.welcome_remaining,'daily_allowance',15000,
        'remaining',greatest(w.daily_remaining+w.welcome_remaining,0)+coalesce((SELECT sum(remaining) FROM public.learning_credit_topups WHERE user_id=target_user_id AND expires_at>now()),0),
        'topup_remaining',coalesce((SELECT sum(remaining) FROM public.learning_credit_topups WHERE user_id=target_user_id AND expires_at>now()),0),
        'completion_overrun',greatest(-w.daily_remaining,0),
        'resets_at',((today+1)::timestamp AT TIME ZONE 'Asia/Kolkata'),
        'active',w.active_request IS NOT NULL AND w.active_since > now()-interval '10 minutes');
END $$;

CREATE OR REPLACE FUNCTION public.begin_learning_credit_request(target_user_id uuid,target_request_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE balance jsonb; w public.learning_credit_wallets%ROWTYPE; tier text; base_remaining bigint; plan_limit bigint;
BEGIN
    SELECT subscription_tier INTO tier FROM public.profiles WHERE id=target_user_id;
    IF NOT FOUND THEN RETURN jsonb_build_object('error','profile'); END IF;
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
    plan_limit := CASE tier WHEN 'tier_199' THEN 1250000 WHEN 'tier_499' THEN 3000000
        WHEN 'tier_999' THEN 8000000 ELSE 9223372036854775807 END;
    SELECT greatest(0,plan_limit-coalesce(sum(coalesce(learning_credits_charged,
        coalesce(input_tokens,0)+coalesce(output_tokens,0)+coalesce(vision_input_tokens,0)+coalesce(vision_output_tokens,0))
        -coalesce(topup_credits_charged,0)),0)) INTO base_remaining
        FROM public.ai_chat_requests WHERE user_id=target_user_id
        AND created_at >= (date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata');
    UPDATE public.learning_credit_wallets SET active_request=target_request_id,active_since=now(),
        active_paid=coalesce(tier,'free')<>'free',active_base_remaining=base_remaining
        WHERE user_id=target_user_id;
    RETURN balance || jsonb_build_object('enabled',coalesce(tier,'free')='free');
END $$;

CREATE OR REPLACE FUNCTION public.finish_learning_credit_request(
    target_user_id uuid,target_request_id uuid,target_execution_id uuid,record jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r public.ai_chat_requests%ROWTYPE; w public.learning_credit_wallets%ROWTYPE;
    charge bigint := 0; daily_debit bigint; welcome_debit bigint; metered boolean;
    needed bigint; pack_debit bigint := 0; take_amount bigint; pack record;
BEGIN
    -- Lock wallet before request, consistent with begin and balance.
    SELECT * INTO w FROM public.learning_credit_wallets WHERE user_id=target_user_id FOR UPDATE;
    metered := FOUND AND w.active_request=target_request_id;
    SELECT * INTO r FROM public.ai_chat_requests WHERE id=target_request_id AND user_id=target_user_id FOR UPDATE;
    IF NOT FOUND OR r.execution_id IS DISTINCT FROM target_execution_id THEN RAISE EXCEPTION 'Request mismatch'; END IF;
    IF r.learning_credits_charged IS NOT NULL THEN
        RETURN jsonb_build_object('charged',r.learning_credits_charged,'replayed',true);
    END IF;
    -- Record customer credits for every tier, separately from provider tokens.
    IF record->>'status'='cached' THEN
            charge := 3000;
        ELSIF record->>'status' IN ('complete','truncated') THEN
            IF record->>'input_tokens' IS NULL OR record->>'output_tokens' IS NULL THEN
                RAISE EXCEPTION 'Token usage missing';
            END IF;
            charge := greatest(coalesce((record->>'input_tokens')::bigint,0),0)
                    + greatest(coalesce((record->>'output_tokens')::bigint,0),0)
                    + greatest(coalesce((record->>'vision_input_tokens')::bigint,0),0)
                    + greatest(coalesce((record->>'vision_output_tokens')::bigint,0),0);
        END IF;
    IF metered THEN
        -- Settlement is assigned to the balance at admission, even across midnight.
        daily_debit := CASE WHEN w.active_paid THEN least(w.active_base_remaining,charge)
            ELSE least(greatest(w.daily_remaining,0),charge) END;
        welcome_debit := CASE WHEN w.active_paid THEN 0 ELSE least(w.welcome_remaining,charge-daily_debit) END;
        needed := charge-daily_debit-welcome_debit;
        FOR pack IN SELECT * FROM public.learning_credit_topups WHERE user_id=target_user_id
            AND expires_at>w.active_since AND remaining>0 ORDER BY expires_at,payment_id FOR UPDATE LOOP
            EXIT WHEN needed<=0;
            take_amount := least(needed,pack.remaining);
            UPDATE public.learning_credit_topups SET remaining=remaining-take_amount WHERE payment_id=pack.payment_id;
            pack_debit := pack_debit+take_amount;
            needed := needed-take_amount;
        END LOOP;
        UPDATE public.learning_credit_wallets SET
            daily_remaining=CASE WHEN w.active_paid THEN daily_remaining ELSE daily_remaining-daily_debit-needed END,
            welcome_remaining=welcome_remaining-welcome_debit,active_request=NULL,active_since=NULL
            WHERE user_id=target_user_id;
    ELSIF record->>'status' IN ('complete','cached','truncated') AND
        EXISTS(SELECT 1 FROM public.learning_credit_wallets WHERE user_id=target_user_id) AND
        coalesce((SELECT subscription_tier FROM public.profiles WHERE id=target_user_id),'free')='free' THEN
        RAISE EXCEPTION 'Credit admission expired; reconciliation required';
    END IF;
    UPDATE public.ai_chat_requests SET status=record->>'status',
        input_tokens=(record->>'input_tokens')::bigint,output_tokens=(record->>'output_tokens')::bigint,
        vision_input_tokens=(record->>'vision_input_tokens')::bigint,
        vision_output_tokens=(record->>'vision_output_tokens')::bigint,
        response_source=record->>'response_source',answer_cache_id=(record->>'answer_cache_id')::uuid,
        response_text=record->>'response_text',response_expires_at=(record->>'response_expires_at')::timestamptz,
        learning_credits_charged=charge,topup_credits_charged=pack_debit WHERE id=target_request_id;
    RETURN jsonb_build_object('charged',charge);
END $$;
REVOKE ALL ON FUNCTION public.learning_credit_balance(uuid), public.begin_learning_credit_request(uuid,uuid),
    public.finish_learning_credit_request(uuid,uuid,uuid,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.learning_credit_balance(uuid), public.begin_learning_credit_request(uuid,uuid),
    public.finish_learning_credit_request(uuid,uuid,uuid,jsonb) TO service_role;

-- Credits replace the free daily five-question limit; paid guardrails remain.
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
        WHEN 'tier_49_daily' THEN 999999 WHEN 'admin' THEN 999999 ELSE 999999 END;
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
