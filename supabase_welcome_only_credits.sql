-- Apply to an existing learning-credit installation before releasing the UI.
-- No welcome balances, eligibility dates, paid plans or purchased grants change.
-- Positive legacy daily balances expire lazily at the next balance/admission.
-- An in-progress admitted answer retains its balance until settlement/timeout.
BEGIN;
ALTER TABLE public.learning_credit_wallets ALTER COLUMN daily_remaining SET DEFAULT 0;
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
    IF NOT (w.active_request IS NOT NULL AND coalesce(w.active_since > now()-interval '10 minutes',false)) THEN
        -- Daily grants are retired. Preserve negative completion debt and any
        -- already admitted answer; never refill or regrant the welcome wallet.
        UPDATE public.learning_credit_wallets SET credit_date=today,
            daily_remaining=least(daily_remaining,0) WHERE user_id=target_user_id;
    END IF;
    SELECT * INTO w FROM public.learning_credit_wallets WHERE user_id=target_user_id;
    RETURN jsonb_build_object('daily_remaining',greatest(w.daily_remaining,0),
        'welcome_remaining',w.welcome_remaining,'welcome_allowance',50000,'daily_allowance',0,
        'remaining',greatest(w.daily_remaining+w.welcome_remaining,0)+coalesce((SELECT sum(remaining) FROM public.learning_credit_topups WHERE user_id=target_user_id AND expires_at>now()),0),
        'topup_remaining',coalesce((SELECT sum(remaining) FROM public.learning_credit_topups WHERE user_id=target_user_id AND expires_at>now()),0),
        'completion_overrun',greatest(-w.daily_remaining,0),
        'resets_at',NULL,
        'active',w.active_request IS NOT NULL AND w.active_since > now()-interval '10 minutes');
END $$;
REVOKE ALL ON FUNCTION public.learning_credit_balance(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.learning_credit_balance(uuid) TO service_role;
COMMIT;
