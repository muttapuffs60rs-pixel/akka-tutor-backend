-- Subscriber-only top-ups. Apply before enabling top-up order creation.
BEGIN;
ALTER TABLE public.learning_credit_topups DROP CONSTRAINT IF EXISTS learning_credit_topups_remaining_check;
ALTER TABLE public.learning_credit_topups ADD CONSTRAINT learning_credit_topups_remaining_check CHECK (remaining BETWEEN 0 AND 300000);
ALTER TABLE public.learning_credit_topups ALTER COLUMN remaining SET DEFAULT 300000;
CREATE OR REPLACE FUNCTION public.learning_topup_eligibility(target_user_id uuid)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
 SELECT jsonb_build_object('eligible', coalesce((SELECT
   subscription_tier IN ('tier_199','tier_499','tier_999') AND subscription_expires_at > now()
   FROM public.profiles WHERE id=target_user_id), false));
$$;
REVOKE ALL ON FUNCTION public.learning_topup_eligibility(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.learning_topup_eligibility(uuid) TO service_role;

CREATE OR REPLACE FUNCTION public.grant_learning_credit_topup(target_user_id uuid,payment_id_value text,order_id_value text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE pack public.learning_credit_topups%ROWTYPE; subscriber public.profiles%ROWTYPE;
BEGIN
 IF length(coalesce(payment_id_value,'')) < 3 OR length(coalesce(order_id_value,'')) < 3 THEN
   RAISE EXCEPTION 'Invalid verified payment identity';
 END IF;
 -- Serialize subscription changes and grants for this account.
 SELECT * INTO subscriber FROM public.profiles WHERE id=target_user_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Subscriber not found'; END IF;
 -- Replays remain idempotent even after subscription expiry.
 SELECT * INTO pack FROM public.learning_credit_topups
   WHERE payment_id=payment_id_value OR order_id=order_id_value;
 IF FOUND THEN
   IF pack.user_id<>target_user_id OR pack.order_id<>order_id_value OR pack.payment_id<>payment_id_value THEN
     RAISE EXCEPTION 'Payment grant conflict';
   END IF;
 ELSE
   IF subscriber.subscription_tier NOT IN ('tier_199','tier_499','tier_999')
      OR subscriber.subscription_tier IS NULL
      OR subscriber.subscription_expires_at IS NULL OR subscriber.subscription_expires_at<=now() THEN
     RAISE EXCEPTION 'An active paid subscription is required for top-ups';
   END IF;
   INSERT INTO public.learning_credit_topups(payment_id,order_id,user_id,remaining,expires_at)
     VALUES(payment_id_value,order_id_value,target_user_id,300000,subscriber.subscription_expires_at)
     RETURNING * INTO pack;
 END IF;
 RETURN jsonb_build_object('credits',300000,'remaining',pack.remaining,'expires_at',pack.expires_at);
END $$;
REVOKE ALL ON FUNCTION public.grant_learning_credit_topup(uuid,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.grant_learning_credit_topup(uuid,text,text) TO service_role;
COMMIT;
