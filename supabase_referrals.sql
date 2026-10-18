BEGIN;
CREATE TABLE public.referral_codes(user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, code text UNIQUE NOT NULL);
CREATE TABLE public.referral_links(invitee_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, inviter_id uuid NOT NULL REFERENCES auth.users(id), created_at timestamptz NOT NULL DEFAULT now(), CHECK(invitee_id<>inviter_id));
CREATE TABLE public.referral_balances(user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, remaining bigint NOT NULL DEFAULT 0 CHECK(remaining>=0));
CREATE TABLE public.verified_subscription_payments(payment_id text PRIMARY KEY, order_id text UNIQUE NOT NULL, user_id uuid NOT NULL REFERENCES auth.users(id), tier_id text NOT NULL, mode text NOT NULL CHECK(mode IN ('test','live')), created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.referral_rewards(invitee_id uuid REFERENCES auth.users(id), inviter_id uuid NOT NULL REFERENCES auth.users(id), payment_id text UNIQUE NOT NULL REFERENCES public.verified_subscription_payments(payment_id), credits bigint NOT NULL, mode text NOT NULL CHECK(mode IN ('test','live')), created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(invitee_id,mode));
ALTER TABLE public.ai_chat_requests ADD COLUMN referral_credits_charged bigint NOT NULL DEFAULT 0;
ALTER TABLE public.referral_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referral_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referral_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.verified_subscription_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referral_rewards ENABLE ROW LEVEL SECURITY;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['referral_codes','referral_links','referral_balances','verified_subscription_payments','referral_rewards'] LOOP
 EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated',t);
 EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
END LOOP; END $$;
CREATE OR REPLACE FUNCTION public.referral_summary(uid uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE code_value text; active boolean; BEGIN
 INSERT INTO public.referral_codes(user_id,code) VALUES(uid,upper(substr(replace(gen_random_uuid()::text,'-',''),1,12))) ON CONFLICT(user_id) DO NOTHING;
 SELECT code INTO code_value FROM public.referral_codes WHERE user_id=uid;
 SELECT subscription_tier IN ('tier_199','tier_499','tier_999','tier_49_daily') AND subscription_expires_at>now() INTO active FROM public.profiles WHERE id=uid;
 RETURN jsonb_build_object('code',code_value,'active',coalesce(active,false),'remaining',coalesce((SELECT remaining FROM public.referral_balances WHERE user_id=uid),0),
 'invited', (SELECT count(*) FROM public.referral_links WHERE inviter_id=uid),
 'claimed',EXISTS(SELECT 1 FROM public.referral_links WHERE invitee_id=uid),
 'can_claim',NOT EXISTS(SELECT 1 FROM public.referral_links WHERE invitee_id=uid) AND NOT EXISTS(SELECT 1 FROM public.verified_subscription_payments WHERE user_id=uid) AND NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=uid AND subscription_start_date IS NOT NULL),
 'earned',coalesce((SELECT sum(credits) FROM public.referral_rewards WHERE inviter_id=uid AND mode='live'),0),
 'test_earned',coalesce((SELECT sum(credits) FROM public.referral_rewards WHERE inviter_id=uid AND mode='test'),0),
 'history',coalesce((SELECT jsonb_agg(jsonb_build_object('credits',credits,'mode',mode,'created_at',created_at)) FROM (SELECT * FROM public.referral_rewards WHERE inviter_id=uid ORDER BY created_at DESC LIMIT 100) r),'[]'::jsonb));
END $$;
CREATE OR REPLACE FUNCTION public.claim_referral(uid uuid,code_value text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE inviter uuid; BEGIN
 PERFORM 1 FROM public.profiles WHERE id=uid FOR UPDATE;
 IF EXISTS(SELECT 1 FROM public.referral_links WHERE invitee_id=uid) OR EXISTS(SELECT 1 FROM public.verified_subscription_payments WHERE user_id=uid) OR EXISTS(SELECT 1 FROM public.profiles WHERE id=uid AND subscription_start_date IS NOT NULL) THEN RETURN jsonb_build_object('error','A referral can only be added once, before your first payment.'); END IF;
 SELECT user_id INTO inviter FROM public.referral_codes WHERE code=upper(trim(code_value));
 IF inviter IS NULL OR inviter=uid THEN RETURN jsonb_build_object('error','Enter a valid friend referral code.'); END IF;
 INSERT INTO public.referral_links(invitee_id,inviter_id) VALUES(uid,inviter);
 RETURN jsonb_build_object('success',true);
END $$;
CREATE OR REPLACE FUNCTION public.apply_verified_subscription(uid uuid,payment_value text,order_value text,tier_value text,mode_value text,start_value timestamptz,expiry_value timestamptz) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE inviter uuid; reward bigint; old public.profiles%ROWTYPE; existing public.verified_subscription_payments%ROWTYPE; first_payment boolean; BEGIN
 SELECT * INTO old FROM public.profiles WHERE id=uid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Profile missing'; END IF;
 SELECT * INTO existing FROM public.verified_subscription_payments WHERE payment_id=payment_value OR order_id=order_value;
 IF FOUND THEN
  IF existing.user_id<>uid OR existing.payment_id<>payment_value OR existing.order_id<>order_value OR existing.tier_id<>tier_value OR existing.mode<>mode_value THEN RAISE EXCEPTION 'Payment identity conflict'; END IF;
  RETURN jsonb_build_object('success',true,'replayed',true);
 END IF;
 reward:=CASE tier_value WHEN 'tier_49_daily' THEN 10000 WHEN 'tier_199' THEN 20000 WHEN 'tier_499' THEN 30000 WHEN 'tier_999' THEN 50000 ELSE NULL END;
 IF reward IS NULL OR mode_value NOT IN ('test','live') THEN RAISE EXCEPTION 'Invalid verified plan'; END IF;
 first_payment:=NOT EXISTS(SELECT 1 FROM public.verified_subscription_payments WHERE user_id=uid AND mode=mode_value);
 INSERT INTO public.verified_subscription_payments VALUES(payment_value,order_value,uid,tier_value,mode_value,now());
 UPDATE public.profiles SET subscription_tier=tier_value,subscription_start_date=start_value,subscription_expires_at=expiry_value,
 previous_tier=CASE WHEN tier_value='tier_49_daily' AND old.subscription_tier NOT IN ('free','tier_49_daily') THEN old.subscription_tier ELSE NULL END WHERE id=uid;
 SELECT inviter_id INTO inviter FROM public.referral_links WHERE invitee_id=uid;
 IF first_payment AND inviter IS NOT NULL THEN
  INSERT INTO public.referral_rewards(invitee_id,inviter_id,payment_id,credits,mode) VALUES(uid,inviter,payment_value,reward,mode_value);
  IF mode_value='live' THEN INSERT INTO public.referral_balances(user_id,remaining) VALUES(inviter,reward) ON CONFLICT(user_id) DO UPDATE SET remaining=referral_balances.remaining+excluded.remaining; END IF;
 END IF;
 RETURN jsonb_build_object('success',true);
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
        -coalesce(topup_credits_charged,0)-coalesce(referral_credits_charged,0)),0)) INTO base_remaining
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
    needed bigint; pack_debit bigint := 0; take_amount bigint; pack record; referral_debit bigint:=0; earned bigint;
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
        IF w.active_paid AND EXISTS(SELECT 1 FROM public.profiles WHERE id=target_user_id AND subscription_tier IN ('tier_199','tier_499','tier_999','tier_49_daily') AND subscription_expires_at>now()) THEN
          SELECT remaining INTO earned FROM public.referral_balances WHERE user_id=target_user_id FOR UPDATE;
          referral_debit:=least(needed,coalesce(earned,0));
          UPDATE public.referral_balances SET remaining=remaining-referral_debit WHERE user_id=target_user_id;
          needed:=needed-referral_debit;
        END IF;
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
        learning_credits_charged=charge,referral_credits_charged=referral_debit,topup_credits_charged=pack_debit WHERE id=target_request_id;
    RETURN jsonb_build_object('charged',charge);
END $$;
CREATE OR REPLACE FUNCTION public.capture_credit_balance_after()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE tier text; plan_limit bigint; pending bigint; packs bigint; w public.learning_credit_wallets%ROWTYPE;
BEGIN
  SELECT * INTO w FROM public.learning_credit_wallets WHERE user_id=NEW.user_id FOR UPDATE;
  IF NOT FOUND THEN RETURN NEW; END IF;
  SELECT subscription_tier INTO tier FROM public.profiles WHERE id=NEW.user_id;
  SELECT coalesce(sum(remaining),0) INTO packs FROM public.learning_credit_topups
    WHERE user_id=NEW.user_id AND expires_at>now();
  IF coalesce(tier,'free')='free' THEN
    pending:=greatest(w.daily_remaining+w.welcome_remaining,0)+packs;
  ELSE
    plan_limit:=CASE tier WHEN 'tier_199' THEN 1250000 WHEN 'tier_499' THEN 3000000 WHEN 'tier_999' THEN 8000000 ELSE NULL END;
    IF plan_limit IS NULL THEN RETURN NEW; END IF;
    SELECT greatest(0,plan_limit-coalesce(sum(coalesce(learning_credits_charged,
      coalesce(input_tokens,0)+coalesce(output_tokens,0)+coalesce(vision_input_tokens,0)+coalesce(vision_output_tokens,0))
      -coalesce(topup_credits_charged,0)-coalesce(referral_credits_charged,0)),0))+packs+CASE WHEN EXISTS(SELECT 1 FROM public.profiles WHERE id=NEW.user_id AND subscription_expires_at>now()) THEN coalesce((SELECT remaining FROM public.referral_balances WHERE user_id=NEW.user_id),0) ELSE 0 END INTO pending
      FROM public.ai_chat_requests WHERE user_id=NEW.user_id
      AND created_at >= (date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata');
  END IF;
  UPDATE public.ai_chat_requests SET credit_balance_after=pending WHERE id=NEW.id;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.referral_summary(uuid),public.claim_referral(uuid,text),public.apply_verified_subscription(uuid,text,text,text,text,timestamptz,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.referral_summary(uuid),public.claim_referral(uuid,text),public.apply_verified_subscription(uuid,text,text,text,text,timestamptz,timestamptz) TO service_role;
COMMIT;
