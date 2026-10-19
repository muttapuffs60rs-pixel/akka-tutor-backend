BEGIN;
DO $$
DECLARE uid uuid:=gen_random_uuid(); tier text; result jsonb; n integer:=0;
 expiry timestamptz:=now()+interval '3 days'; rejected boolean;
BEGIN
 INSERT INTO auth.users(id,aud,role,email,raw_user_meta_data,created_at,updated_at)
 VALUES(uid,'authenticated','authenticated',uid::text||'@example.invalid','{}',now(),now());
 INSERT INTO public.profiles(id,subscription_tier) VALUES(uid,'free') ON CONFLICT(id) DO NOTHING;
 FOREACH tier IN ARRAY ARRAY['free','tier_49_daily','admin','tier_199','tier_499','tier_999'] LOOP
  UPDATE public.profiles SET subscription_tier=tier, subscription_expires_at=expiry WHERE id=uid;
  IF tier IN ('tier_199','tier_499','tier_999') THEN
   IF (public.learning_topup_eligibility(uid)->>'eligible')::boolean IS NOT TRUE THEN RAISE EXCEPTION 'Eligible subscriber rejected'; END IF;
   n:=n+1;
   result:=public.grant_learning_credit_topup(uid,'pay_check_'||uid::text||n,'order_check_'||uid::text||n);
   IF (result->>'credits')::bigint<>300000 OR (result->>'expires_at')::timestamptz<>expiry THEN RAISE EXCEPTION 'Wrong credits or expiry'; END IF;
   PERFORM public.grant_learning_credit_topup(uid,'pay_check_'||uid::text||n,'order_check_'||uid::text||n);
   IF (SELECT count(*) FROM public.learning_credit_topups WHERE user_id=uid)<>n THEN RAISE EXCEPTION 'Duplicate grant'; END IF;
   IF (SELECT subscription_tier<>tier OR subscription_expires_at<>expiry FROM public.profiles WHERE id=uid) THEN RAISE EXCEPTION 'Subscription changed'; END IF;
  ELSE
   IF (public.learning_topup_eligibility(uid)->>'eligible')::boolean THEN RAISE EXCEPTION 'Ineligible allowed'; END IF;
   rejected:=false;
   BEGIN PERFORM public.grant_learning_credit_topup(uid,'pay_denied'||uid::text,'order_denied'||uid::text); EXCEPTION WHEN OTHERS THEN rejected:=true; END;
   IF NOT rejected THEN RAISE EXCEPTION 'Ineligible grant accepted'; END IF;
  END IF;
 END LOOP;
 FOREACH tier IN ARRAY ARRAY['tier_199','tier_499','tier_999'] LOOP
  UPDATE public.profiles SET subscription_tier=tier, subscription_expires_at=now()-interval '1 second' WHERE id=uid;
  IF (public.learning_topup_eligibility(uid)->>'eligible')::boolean THEN RAISE EXCEPTION 'Expired subscriber eligible'; END IF;
  rejected:=false;
  BEGIN PERFORM public.grant_learning_credit_topup(uid,'pay_expired'||uid::text,'order_expired'||uid::text); EXCEPTION WHEN OTHERS THEN rejected:=true; END;
  IF NOT rejected THEN RAISE EXCEPTION 'Expired grant accepted'; END IF;
 END LOOP;
 UPDATE public.profiles SET subscription_expires_at=NULL WHERE id=uid;
 IF (public.learning_topup_eligibility(uid)->>'eligible')::boolean THEN RAISE EXCEPTION 'Null expiry eligible'; END IF;
 PERFORM public.grant_learning_credit_topup(uid,'pay_check_'||uid::text||1,'order_check_'||uid::text||1);
 rejected:=false;
 BEGIN PERFORM public.grant_learning_credit_topup(uid,'pay_conflict'||uid::text,'order_check_'||uid::text||1); EXCEPTION WHEN OTHERS THEN rejected:=true; END;
 IF NOT rejected THEN RAISE EXCEPTION 'Conflicting identity accepted'; END IF;
 IF has_function_privilege('authenticated','public.grant_learning_credit_topup(uuid,text,text)','EXECUTE') THEN RAISE EXCEPTION 'Grant exposed to users'; END IF;
END $$;
ROLLBACK;
SELECT 'Subscriber eligibility, expiry, replay and conflict checks passed; synthetic rows rolled back' AS result;
