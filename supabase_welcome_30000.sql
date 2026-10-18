-- New accounts receive 30,000 welcome credits after this migration.
-- Existing grants and the separate daily allowance retain their current rules.
BEGIN;
ALTER TABLE public.learning_credit_policy
    ADD COLUMN IF NOT EXISTS welcome_amount integer NOT NULL DEFAULT 30000
        CHECK(welcome_amount BETWEEN 0 AND 50000),
    ADD COLUMN IF NOT EXISTS welcome_amount_from timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS launch_bonus_amount integer NOT NULL DEFAULT 20000
        CHECK(launch_bonus_amount BETWEEN 0 AND 20000),
    ADD COLUMN IF NOT EXISTS launch_bonus_from timestamptz NOT NULL DEFAULT '2026-10-20T00:00:00+05:30',
    ADD COLUMN IF NOT EXISTS launch_bonus_until timestamptz NOT NULL DEFAULT '2026-10-21T00:00:00+05:30';
ALTER TABLE public.learning_credit_wallets
    ADD COLUMN IF NOT EXISTS welcome_allowance bigint NOT NULL DEFAULT 50000
        CHECK(welcome_allowance BETWEEN 0 AND 50000);

CREATE OR REPLACE FUNCTION public.learning_credit_balance(target_user_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE w public.learning_credit_wallets%ROWTYPE;
    today date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
BEGIN
    WITH entitlement AS (
    SELECT u.id,
        CASE WHEN u.created_at < p.welcome_from THEN 0
             WHEN u.created_at < p.welcome_amount_from THEN 50000 ELSE p.welcome_amount END
        + CASE WHEN u.created_at >= p.welcome_from
                    AND u.created_at >= p.launch_bonus_from AND u.created_at < p.launch_bonus_until
               THEN p.launch_bonus_amount ELSE 0 END AS welcome_grant
    FROM auth.users u CROSS JOIN public.learning_credit_policy p WHERE u.id=target_user_id
    )
    INSERT INTO public.learning_credit_wallets(user_id,credit_date,welcome_remaining,welcome_allowance)
    SELECT id,today,welcome_grant,welcome_grant FROM entitlement
    ON CONFLICT DO NOTHING;
    SELECT * INTO w FROM public.learning_credit_wallets WHERE user_id=target_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'User not found'; END IF;
    IF w.credit_date < today AND NOT (w.active_request IS NOT NULL AND w.active_since > now()-interval '10 minutes') THEN
        UPDATE public.learning_credit_wallets SET credit_date=today,
            daily_remaining=15000 + least(daily_remaining,0) WHERE user_id=target_user_id;
    END IF;
    SELECT * INTO w FROM public.learning_credit_wallets WHERE user_id=target_user_id;
    RETURN jsonb_build_object('daily_remaining',greatest(w.daily_remaining,0),
        'welcome_remaining',w.welcome_remaining,'welcome_allowance',w.welcome_allowance,
        'daily_allowance',15000,
        'remaining',greatest(w.daily_remaining+w.welcome_remaining,0)+coalesce((SELECT sum(remaining) FROM public.learning_credit_topups WHERE user_id=target_user_id AND expires_at>now()),0),
        'topup_remaining',coalesce((SELECT sum(remaining) FROM public.learning_credit_topups WHERE user_id=target_user_id AND expires_at>now()),0),
        'completion_overrun',greatest(-w.daily_remaining,0),
        'resets_at',((today+1)::timestamp AT TIME ZONE 'Asia/Kolkata'),
        'active',w.active_request IS NOT NULL AND w.active_since > now()-interval '10 minutes');
END $$;
REVOKE ALL ON FUNCTION public.learning_credit_balance(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.learning_credit_balance(uuid) TO service_role;
COMMIT;
