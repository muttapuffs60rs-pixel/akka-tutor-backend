"""Identical passages in different grades must retain the requested metadata."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import time
from unittest.mock import Mock


class RetrievalGradeScopeTests(unittest.TestCase):
    def test_metadata_lookup_is_scoped_to_grade_and_subject(self):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(n for n in tree.body if getattr(n, "name", None) == "_get_context_cached")
        function.decorator_list = []
        database = Mock()
        database.rpc.return_value.execute.return_value = SimpleNamespace(data=[{"content": "Shared passage"}])
        query = Mock()
        query.select.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{
            "content": "Shared passage", "unit_name": "Class seven unit", "section_name": "Plants",
        }])
        database.table.return_value = query
        namespace = {"supabase": database, "embeddings": Mock()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        result = namespace["_get_context_cached"]("Explain plants", "Science", 7, 0.1, 5, 0)
        self.assertIn("Class seven unit", result)
        self.assertEqual(query.eq.call_args_list[0].args, ("grade_level", 7))
        self.assertEqual(query.eq.call_args_list[1].args, ("subject", "Science"))

        query.execute.side_effect = TimeoutError("metadata temporarily unavailable")
        result = namespace["_get_context_cached"]("Explain plants", "Science", 7, 0.1, 5, 0)
        self.assertEqual(result, "Shared passage")

    def test_transient_failure_retries_and_does_not_poison_future_lookups(self):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(n for n in tree.body if getattr(n, "name", None) == "get_context")
        lookup = Mock(side_effect=[TimeoutError(), "Recovered textbook text"])
        namespace = {"_get_context_cached": lookup, "time": time}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        self.assertEqual(namespace["get_context"]("Plants", "Science", 7), "Recovered textbook text")
        self.assertEqual(lookup.call_count, 2)
        lookup.side_effect = [TimeoutError(), TimeoutError(), "New textbook text"]
        self.assertEqual(namespace["get_context"]("Plants", "Science", 7), "No specific textbook context found.")
        self.assertEqual(namespace["get_context"]("Plants", "Science", 7), "New textbook text")


if __name__ == "__main__":
    unittest.main()
