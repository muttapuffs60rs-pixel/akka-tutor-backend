import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from usage_meter import usage_summary, monthly_window, fetch_usage


class UsageMeterTests(unittest.TestCase):
    def test_paid_saved_answer_deducts_credits_without_inventing_api_tokens(self):
        rows = [{'status': 'cached', 'input_tokens': 0, 'output_tokens': 0,
                 'learning_credits_charged': 3000},
                {'status': 'complete', 'input_tokens': 100, 'output_tokens': 20,
                 'learning_credits_charged': 120}]
        for tier in ('tier_199', 'tier_499', 'tier_999'):
            result = usage_summary({'subscription_tier': tier}, rows, datetime.now(timezone.utc))
            self.assertEqual(result['monthly_tokens_used'], 120)
            self.assertEqual(result['monthly_credits_used'], 3120)

    def test_topup_spend_is_not_also_deducted_from_monthly_allowance(self):
        result = usage_summary({'subscription_tier': 'tier_199'}, [
            {'status': 'cached', 'input_tokens': 0, 'output_tokens': 0,
             'learning_credits_charged': 3000, 'topup_credits_charged': 3000}], datetime.now(timezone.utc))
        self.assertEqual(result['monthly_credits_used'], 0)
        self.assertEqual(result['monthly_tokens_used'], 0)

    def test_ist_month_boundary(self):
        start, end = monthly_window(datetime(2026, 12, 31, 19, tzinfo=timezone.utc))
        self.assertEqual((start.year, start.month, start.day), (2027, 1, 1))
        self.assertEqual((end.year, end.month), (2027, 2))

    def test_counts_cost_even_on_failed_or_truncated_requests(self):
        rows = [{'status': 'truncated', 'input_tokens': 100, 'output_tokens': 900},
                {'status': 'failed', 'input_tokens': 20, 'output_tokens': 10,
                 'vision_input_tokens': 30, 'vision_output_tokens': 40},
                {'status': 'cached', 'input_tokens': 0, 'output_tokens': 0},
                {'status': 'legacy_unmetered'}]
        result = usage_summary({'subscription_tier': 'tier_499', 'chats_today': 4}, rows,
                               datetime.now(timezone.utc))
        self.assertEqual(result['monthly_tokens_used'], 1100)
        self.assertEqual(result['unmetered_requests'], 1)
        self.assertEqual(result['monthly_token_target'], 3000000)
        self.assertFalse(result['monthly_limit_enforced'])
        self.assertEqual(result['daily_remaining'], 146)

    def test_free_and_unlimited(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(usage_summary({'chats_today': 8}, [], now)['daily_remaining'], 0)
        self.assertIsNone(usage_summary({'subscription_tier': 'admin'}, [], now)['daily_limit'])
        self.assertEqual(usage_summary({'subscription_tier': 'tier_199'}, [], now)['monthly_token_target'], 1250000)
        self.assertEqual(usage_summary({'subscription_tier': 'tier_999'}, [], now)['token_target'], 8000000)
        self.assertEqual(usage_summary({}, [], now)['token_target'], 50000)
        self.assertEqual(usage_summary({}, [], now)['token_period'], 'lifetime')

    def test_scopes_and_paginates(self):
        client = MagicMock()
        query = client.table.return_value
        for name in ('select', 'eq', 'gte', 'lt', 'order', 'range'):
            getattr(query, name).return_value = query
        row = {'status': 'complete', 'input_tokens': 1, 'output_tokens': 2}
        query.execute.side_effect = [MagicMock(data=[row] * 1000), MagicMock(data=[row])]
        result = fetch_usage(client, {}, 'student-id')
        self.assertEqual(result['monthly_tokens_used'], 3003)
        query.eq.assert_called_with('user_id', 'student-id')
        query.gte.assert_called_with('created_at', '1970-01-01T00:00:00+00:00')
        self.assertEqual(query.range.call_args_list[-1].args, (1000, 1999))


if __name__ == '__main__':
    unittest.main()
