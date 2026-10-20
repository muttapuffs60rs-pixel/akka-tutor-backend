-- Private owner report: run in Supabase SQL Editor. Counts begin at deployment.
-- Unique visitors are browser estimates. Private browsing, storage clearing,
-- disabled analytics and multiple devices affect accuracy. All dates use IST.
SELECT period,
 count(v.event_id) AS app_views,
 count(DISTINCT v.visitor_hash) AS estimated_unique_visitors
FROM (VALUES
 ('Today (IST)', date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata'),
 ('Last 7 days',now()-interval '7 days'),
 ('Last 30 days',now()-interval '30 days'),
 ('Last 90 days',now()-interval '90 days')
) AS windows(period,starts_at)
LEFT JOIN public.anonymous_app_visits v ON v.visited_at>=windows.starts_at
GROUP BY period,starts_at ORDER BY starts_at DESC;

