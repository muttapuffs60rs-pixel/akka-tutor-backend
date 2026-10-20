BEGIN;
CREATE TABLE IF NOT EXISTS public.anonymous_app_visits (
 event_id uuid PRIMARY KEY,
 visitor_hash text NOT NULL CHECK (visitor_hash ~ '^[a-f0-9]{64}$'),
 source text NOT NULL CHECK (source IN ('direct','google','bing','facebook','instagram','whatsapp','other')),
 visited_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS anonymous_app_visits_time ON public.anonymous_app_visits(visited_at);
ALTER TABLE public.anonymous_app_visits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.anonymous_app_visits FROM PUBLIC,anon,authenticated;
GRANT ALL ON public.anonymous_app_visits TO service_role;
CREATE OR REPLACE FUNCTION public.record_anonymous_visit(event uuid,visitor text,referrer_source text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 INSERT INTO public.anonymous_app_visits(event_id,visitor_hash,source)
 VALUES(event,visitor,referrer_source) ON CONFLICT(event_id) DO NOTHING;
 DELETE FROM public.anonymous_app_visits WHERE visited_at < now()-interval '90 days';
END $$;
REVOKE ALL ON FUNCTION public.record_anonymous_visit(uuid,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_anonymous_visit(uuid,text,text) TO service_role;
COMMIT;
