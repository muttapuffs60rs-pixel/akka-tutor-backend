-- Apply this isolated migration before the pre-launch frontend/backend release.
-- Starts inactive; activate only after both deployments have been verified.
BEGIN;
CREATE SCHEMA IF NOT EXISTS app_private;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS app_private.launch_config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    enabled boolean NOT NULL DEFAULT false,
    launch_date date NOT NULL DEFAULT '2026-10-20',
    launch_at timestamptz,
    timezone text NOT NULL DEFAULT 'Asia/Kolkata'
);
INSERT INTO app_private.launch_config(singleton) VALUES(true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS app_private.launch_testers (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE
);
ALTER TABLE app_private.launch_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_private.launch_testers ENABLE ROW LEVEL SECURITY;
INSERT INTO app_private.launch_testers(user_id)
SELECT id FROM auth.users WHERE lower(email)='tester005@test.com'
ON CONFLICT DO NOTHING;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_private.launch_testers) THEN
        RAISE EXCEPTION 'Approved tester account is missing';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.app_launch_access_for_user(target_user_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
    SELECT EXISTS(SELECT 1 FROM app_private.launch_config WHERE NOT enabled)
      OR EXISTS(SELECT 1 FROM app_private.launch_testers WHERE user_id=target_user_id);
$$;
REVOKE ALL ON FUNCTION public.app_launch_access_for_user(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.app_launch_access_for_user(uuid) TO service_role;

CREATE OR REPLACE FUNCTION public.app_launch_allowed()
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
    SELECT public.app_launch_access_for_user(auth.uid());
$$;
REVOKE ALL ON FUNCTION public.app_launch_allowed() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.app_launch_allowed() TO anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION public.app_launch_status()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
    SELECT jsonb_build_object('prelaunch',enabled,'launch_date',launch_date,
        'launch_at',launch_at,'timezone',timezone,'server_now',now(),
        'allowed',public.app_launch_allowed()) FROM app_private.launch_config WHERE singleton;
$$;
REVOKE ALL ON FUNCTION public.app_launch_status() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.app_launch_status() TO anon,authenticated,service_role;

-- Applies to REST table access AND existing SECURITY DEFINER RPCs.
CREATE OR REPLACE FUNCTION public.app_prelaunch_request()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
    IF current_setting('request.jwt.claims',true)::jsonb->>'role' = 'service_role' THEN RETURN; END IF;
    IF current_setting('request.path',true) IN ('/rpc/app_launch_status','/rpc/app_launch_allowed') THEN RETURN; END IF;
    IF NOT public.app_launch_allowed() THEN
        RAISE SQLSTATE 'PT403' USING MESSAGE='Arivora is in pre-launch. Private testing access only.';
    END IF;
END $$;
REVOKE ALL ON FUNCTION public.app_prelaunch_request() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.app_prelaunch_request() TO anon,authenticated,service_role;

-- Refuse to overwrite an unrelated pre-request hook.
DO $$ DECLARE settings text; BEGIN
    SELECT array_to_string(rolconfig,',') INTO settings FROM pg_roles WHERE rolname='authenticator';
    IF settings LIKE '%pgrst.db_pre_request=%' AND settings NOT LIKE '%pgrst.db_pre_request=public.app_prelaunch_request%' THEN
        RAISE EXCEPTION 'Existing pre-request hook must be composed before installing pre-launch';
    END IF;
END $$;
ALTER ROLE authenticator SET pgrst.db_pre_request='public.app_prelaunch_request';

-- REST hooks do not govern Realtime/Storage. Preserve existing RLS policies and
-- add a restrictive AND gate for ordinary clients on existing application tables.
DO $$ DECLARE t record; BEGIN
    FOR t IN SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind IN ('r','p') AND (n.nspname='public' OR (n.nspname='storage' AND c.relname='objects'))
    LOOP
        IF t.nspname='public' THEN
            EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',t.nspname,t.relname);
        END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_policies WHERE schemaname=t.nspname AND tablename=t.relname AND policyname='arivora_prelaunch_gate') THEN
            EXECUTE format('CREATE POLICY arivora_prelaunch_gate ON %I.%I AS RESTRICTIVE FOR ALL TO anon,authenticated USING ((SELECT public.app_launch_allowed())) WITH CHECK ((SELECT public.app_launch_allowed()))',t.nspname,t.relname);
        END IF;
    END LOOP;
END $$;
NOTIFY pgrst,'reload config';
NOTIFY pgrst,'reload schema';
COMMIT;

-- Activation (run separately after deployment):
-- UPDATE app_private.launch_config SET enabled=true WHERE singleton;
-- Launch-day release (manual, never triggered by the countdown):
-- UPDATE app_private.launch_config SET enabled=false WHERE singleton;
-- Exact ceremony time, once confirmed: set launch_at to an ISO timestamp with +05:30.
