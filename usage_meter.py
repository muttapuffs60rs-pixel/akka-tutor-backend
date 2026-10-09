"""Read-only usage reporting; this does not grant or enforce token entitlements."""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
# tier_199 is the legacy identifier for the Standard plan, now priced at ₹249.
MONTHLY_TARGETS = {'tier_199': 1_250_000, 'tier_499': 3_000_000, 'tier_999': 8_000_000}
DAILY_LIMITS = {'tier_199': 50, 'tier_499': 150, 'tier_999': 150}


def monthly_window(now):
    start = now.astimezone(IST).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end


def usage_summary(profile, rows, now):
    start, end = monthly_window(now)
    tier = profile.get('subscription_tier') or 'free'
    daily_limit = None if tier in ('admin', 'tier_49_daily') else DAILY_LIMITS.get(tier, 5)
    fields = ('input_tokens', 'output_tokens', 'vision_input_tokens', 'vision_output_tokens')
    used = sum(max(0, int(row.get(field) or 0)) for row in rows for field in fields)
    unknown = sum(row.get('status') not in ('cached',) and
                  (row.get('input_tokens') is None or row.get('output_tokens') is None)
                  for row in rows)
    return {
        'tier': tier, 'monthly_tokens_used': used,
        'monthly_credits_used': sum(
            max(0, int(row['learning_credits_charged']) - int(row.get('topup_credits_charged') or 0)) if row.get('learning_credits_charged') is not None
            else sum(max(0, int(row.get(field) or 0)) for field in fields) for row in rows),
        'token_period': 'lifetime' if tier == 'free' else 'monthly',
        'token_target': 50_000 if tier == 'free' else MONTHLY_TARGETS.get(tier),
        'monthly_token_target': MONTHLY_TARGETS.get(tier),
        'monthly_limit_enforced': False, 'unmetered_requests': unknown,
        'period_start': start.isoformat(), 'period_end': end.isoformat(),
        'daily_limit': daily_limit,
        'daily_remaining': None if daily_limit is None else max(0, daily_limit - int(profile.get('chats_today') or 0)),
    }


def fetch_usage(client, profile, user_id, now=None):
    now = now or datetime.now(timezone.utc)
    start, end = monthly_window(now)
    rows = []
    # PostgREST caps individual responses; paginate so heavy users aren't undercounted.
    for offset in range(0, 1_000_000, 1000):
        batch = (client.table('ai_chat_requests')
                 .select('status,input_tokens,output_tokens,vision_input_tokens,vision_output_tokens,learning_credits_charged,topup_credits_charged')
                 .eq('user_id', user_id).gte('created_at',
                     '1970-01-01T00:00:00+00:00' if (profile.get('subscription_tier') or 'free') == 'free' else start.isoformat())
                 .lt('created_at', end.isoformat()).order('id')
                 .range(offset, offset + 999).execute().data)
        rows.extend(batch)
        if len(batch) < 1000:
            return usage_summary(profile, rows, now)
    raise RuntimeError('Usage report exceeds supported range')
