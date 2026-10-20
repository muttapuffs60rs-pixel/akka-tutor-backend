BEGIN;
DO $$
DECLARE e uuid:=gen_random_uuid();
BEGIN
 PERFORM public.record_anonymous_visit(e,repeat('a',64),'direct');
 PERFORM public.record_anonymous_visit(e,repeat('a',64),'direct');
 IF (SELECT count(*) FROM public.anonymous_app_visits WHERE event_id=e)<>1 THEN RAISE EXCEPTION 'Duplicate counted'; END IF;
 IF has_table_privilege('anon','public.anonymous_app_visits','SELECT') OR has_table_privilege('authenticated','public.anonymous_app_visits','SELECT') THEN RAISE EXCEPTION 'Records publicly readable'; END IF;
 IF has_function_privilege('anon','public.record_anonymous_visit(uuid,text,text)','EXECUTE') OR has_function_privilege('authenticated','public.record_anonymous_visit(uuid,text,text)','EXECUTE') THEN RAISE EXCEPTION 'Direct public writes allowed'; END IF;
 IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid='public.anonymous_app_visits'::regclass) THEN RAISE EXCEPTION 'RLS missing'; END IF;
END $$;
ROLLBACK;
SELECT 'PASS: deduplication and private analytics permissions; test data rolled back' AS result;
