-- Validate new/changed contact numbers without modifying existing accounts.
BEGIN;
CREATE OR REPLACE FUNCTION public.validate_profile_mobile()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.phone_number IS NOT DISTINCT FROM OLD.phone_number THEN RETURN NEW; END IF;
  END IF;
  IF NEW.phone_number IS NOT NULL AND NEW.phone_number !~ '^[0-9]{10}$' THEN
    RAISE EXCEPTION 'Mobile number must contain exactly 10 digits' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.validate_profile_mobile() FROM PUBLIC;
DROP TRIGGER IF EXISTS validate_profile_mobile ON public.profiles;
CREATE TRIGGER validate_profile_mobile BEFORE INSERT OR UPDATE OF phone_number
ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.validate_profile_mobile();
CREATE TEMP TABLE mobile_probe(phone_number text);
CREATE TRIGGER mobile_probe BEFORE INSERT OR UPDATE OF phone_number ON mobile_probe FOR EACH ROW EXECUTE FUNCTION public.validate_profile_mobile();
DO $$ BEGIN
  INSERT INTO mobile_probe VALUES ('9000000000'), (NULL);
  BEGIN INSERT INTO mobile_probe VALUES ('abcdefghij'); RAISE EXCEPTION 'Invalid number accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN INSERT INTO mobile_probe VALUES ('123'); RAISE EXCEPTION 'Short number accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN UPDATE mobile_probe SET phone_number='12345678901' WHERE phone_number IS NOT NULL; RAISE EXCEPTION 'Long number accepted'; EXCEPTION WHEN check_violation THEN NULL; END;
END $$;
SELECT 'Mobile validation checks passed; changes rolled back' AS result;
ROLLBACK;
