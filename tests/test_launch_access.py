import unittest
from unittest.mock import Mock
from fastapi import HTTPException
from launch_access import require_launch_access

class LaunchAccessTests(unittest.TestCase):
    def test_approved_account_passes(self):
        db=Mock(); db.rpc.return_value.execute.return_value.data=True
        require_launch_access(db,'tester')
        db.rpc.assert_called_once_with('app_launch_access_for_user',{'target_user_id':'tester'})

    def test_all_other_values_fail_closed(self):
        for value in (False,None,'true',{},[]):
            db=Mock(); db.rpc.return_value.execute.return_value.data=value
            with self.assertRaises(HTTPException) as e: require_launch_access(db,'student')
            self.assertEqual(e.exception.status_code,403)

    def test_database_failure_never_allows_access(self):
        db=Mock(); db.rpc.side_effect=RuntimeError('unavailable')
        with self.assertRaises(HTTPException) as e: require_launch_access(db,'student')
        self.assertEqual(e.exception.status_code,503)
