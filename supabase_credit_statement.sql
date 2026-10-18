-- Capture settled balances atomically. Existing transactions remain NULL.
BEGIN;
ALTER TABLE public.ai_chat_requests ADD COLUMN IF NOT EXISTS credit_balance_after bigint;
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
      -coalesce(topup_credits_charged,0)),0))+packs INTO pending
      FROM public.ai_chat_requests WHERE user_id=NEW.user_id
      AND created_at >= (date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata');
  END IF;
  UPDATE public.ai_chat_requests SET credit_balance_after=pending WHERE id=NEW.id;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.capture_credit_balance_after() FROM PUBLIC,anon,authenticated;
DROP TRIGGER IF EXISTS capture_credit_balance_after ON public.ai_chat_requests;
CREATE TRIGGER capture_credit_balance_after AFTER UPDATE OF learning_credits_charged ON public.ai_chat_requests
  FOR EACH ROW WHEN (OLD.learning_credits_charged IS NULL AND NEW.learning_credits_charged IS NOT NULL)
  EXECUTE FUNCTION public.capture_credit_balance_after();
COMMIT;
