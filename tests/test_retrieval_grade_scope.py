"""Identical passages in different grades must retain the requested metadata."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import time
from unittest.mock import Mock
from textbook_retrieval import TAMIL_SUBJECTS, named_work_query, clean_passage


class RetrievalGradeScopeTests(unittest.TestCase):
    def test_named_tamil_work_uses_scoped_text_without_unrelated_vectors(self):
        source = Path(__file__).resolve().parents[1] / 'main.py'
        function = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                        if getattr(n, 'name', None) == '_get_context_cached')
        function.decorator_list = []
        lexical, embedding, database = Mock(), Mock(), Mock()
        namespace = dict(supabase=database, embeddings=embedding, TAMIL_SUBJECTS=TAMIL_SUBJECTS,
                         tamil_keyword_passages=lexical, named_work_query=named_work_query,
                         clean_passage=clean_passage)
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        lexical.return_value = [{'section_name':'சித்தர் பாடல்','content':'Verified poem lines'}]
        result = namespace['_get_context_cached']('சித்தர் பாடல்', 'Advance Tamil', 11, .1, 5, 0)
        self.assertIn('Class 11 | Advance Tamil', result)
        self.assertIn('Verified poem lines', result)
        lexical.assert_called_with(database, 'சித்தர் பாடல்', 'Advance Tamil', 11)
        lexical.return_value = []
        with self.assertRaises(LookupError):
            namespace['_get_context_cached']('“Unknown poem” விளக்குக', 'Tamil', 6, .1, 5, 0)
        embedding.embed_query.assert_not_called()
        database.rpc.assert_not_called()

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
        namespace = {"supabase": database, "embeddings": Mock(),
                     "TAMIL_SUBJECTS": TAMIL_SUBJECTS}
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
