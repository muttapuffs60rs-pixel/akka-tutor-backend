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
COMMIT;
