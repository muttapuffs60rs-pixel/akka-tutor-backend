-- Synthetic records only. All test writes are rolled back.
BEGIN;
DO $$
DECLARE
    fresh uuid := gen_random_uuid(); legacy uuid := gen_random_uuid();
    ineligible uuid := gen_random_uuid(); existing uuid := gen_random_uuid();
    opening uuid := gen_random_uuid(); closing uuid := gen_random_uuid();
    just_before uuid := gen_random_uuid();
    policy public.learning_credit_policy%ROWTYPE; balance jsonb;
BEGIN
    SELECT * INTO policy FROM public.learning_credit_policy WHERE singleton;
    INSERT INTO auth.users(id,aud,role,email,raw_user_meta_data,created_at,updated_at)
    VALUES
      (fresh,'authenticated','authenticated',fresh::text||'@example.invalid','{}',policy.welcome_amount_from+interval '1 second',now()),
      (legacy,'authenticated','authenticated',legacy::text||'@example.invalid','{}',policy.welcome_from+(policy.welcome_amount_from-policy.welcome_from)/2,now()),
      (ineligible,'authenticated','authenticated',ineligible::text||'@example.invalid','{}',policy.welcome_from-interval '1 day',now()),
      (existing,'authenticated','authenticated',existing::text||'@example.invalid','{}',policy.welcome_from,now()),
      (opening,'authenticated','authenticated',opening::text||'@example.invalid','{}',policy.launch_bonus_from,now()),
      (closing,'authenticated','authenticated',closing::text||'@example.invalid','{}',policy.launch_bonus_until,now()),
      (just_before,'authenticated','authenticated',just_before::text||'@example.invalid','{}',policy.launch_bonus_from-interval '1 microsecond',now());
    balance := public.learning_credit_balance(fresh);
    IF (balance->>'welcome_remaining')::bigint<>30000 OR (balance->>'welcome_allowance')::bigint<>30000 THEN
      RAISE EXCEPTION 'New grant is not 30000'; END IF;
    IF (balance->>'daily_allowance')::bigint<>15000 THEN RAISE EXCEPTION 'Daily allowance changed'; END IF;
    UPDATE public.learning_credit_wallets SET welcome_remaining=29000,credit_date=current_date-1,daily_remaining=0 WHERE user_id=fresh;
    balance := public.learning_credit_balance(fresh);
    IF (balance->>'welcome_remaining')::bigint<>29000 THEN RAISE EXCEPTION 'Welcome grant repeated'; END IF;
    balance := public.learning_credit_balance(legacy);
    IF (balance->>'welcome_remaining')::bigint<>50000 THEN RAISE EXCEPTION 'Legacy eligibility changed'; END IF;
    balance := public.learning_credit_balance(ineligible);
    IF (balance->>'welcome_remaining')::bigint<>0 THEN RAISE EXCEPTION 'Ineligible account granted credits'; END IF;
    INSERT INTO public.learning_credit_wallets(user_id,credit_date,welcome_remaining,welcome_allowance)
      VALUES(existing,current_date,37000,50000);
    balance := public.learning_credit_balance(existing);
    IF (balance->>'welcome_remaining')::bigint<>37000 OR (balance->>'welcome_allowance')::bigint<>50000 THEN
      RAISE EXCEPTION 'Existing grant changed'; END IF;
    balance := public.learning_credit_balance(opening);
    IF (balance->>'welcome_remaining')::bigint<>50000 OR (balance->>'welcome_allowance')::bigint<>50000 THEN
      RAISE EXCEPTION 'Opening-day bonus missing'; END IF;
    UPDATE public.learning_credit_wallets SET welcome_remaining=41000 WHERE user_id=opening;
    balance := public.learning_credit_balance(opening);
    IF (balance->>'welcome_remaining')::bigint<>41000 THEN RAISE EXCEPTION 'Opening bonus repeated'; END IF;
    balance := public.learning_credit_balance(closing);
    IF (balance->>'welcome_remaining')::bigint<>30000 THEN RAISE EXCEPTION 'Bonus extended past deadline'; END IF;
    balance := public.learning_credit_balance(just_before);
    IF (balance->>'welcome_remaining')::bigint<>30000 THEN RAISE EXCEPTION 'Bonus started early'; END IF;
    IF has_function_privilege('anon','public.learning_credit_balance(uuid)','EXECUTE')
      OR has_function_privilege('authenticated','public.learning_credit_balance(uuid)','EXECUTE') THEN
      RAISE EXCEPTION 'Privileged balance function exposed'; END IF;
END $$;
ROLLBACK;
SELECT 'PASS: 30000 standard, 50000 opening-day grant, IST boundaries, no repeated grants, legacy balances and permissions. Synthetic records rolled back.' AS result;
