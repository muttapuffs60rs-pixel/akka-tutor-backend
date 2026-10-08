"""Identical passages in different grades must retain the requested metadata."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class RetrievalGradeScopeTests(unittest.TestCase):
    def test_metadata_lookup_is_scoped_to_grade_and_subject(self):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(n for n in tree.body if getattr(n, "name", None) == "get_context")
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
        result = namespace["get_context"]("Explain plants", "Science", 7)
        self.assertIn("Class seven unit", result)
        self.assertEqual(query.eq.call_args_list[0].args, ("grade_level", 7))
        self.assertEqual(query.eq.call_args_list[1].args, ("subject", "Science"))


if __name__ == "__main__":
    unittest.main()
