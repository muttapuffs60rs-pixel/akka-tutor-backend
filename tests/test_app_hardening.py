"""Offline regressions: exercise real route bodies without model/service startup."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import List
import traceback
import unittest
from unittest.mock import Mock, patch

from fastapi import Depends, HTTPException
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field, ValidationError

from image_security import MAX_IMAGE_BYTES, download_chat_image, validate_image_url
from prompts import AKKA_QUIZ_PROMPT

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://example.supabase.co"
IMAGE = ORIGIN + "/storage/v1/object/public/chat-images/chat_uploads/test.jpg"


def load_routes():
    """Compile the actual definitions; skip OCR/model creation and live credentials."""
    names = {
        "QuizRequest", "QuizQuestion", "QuizResponse", "StudentAnswerRequest",
        "generate_quiz", "submit_answer", "get_daily_profile",
    }
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8-sig"))
    definitions = [node for node in tree.body if getattr(node, "name", None) in names]
    for node in definitions:
        node.decorator_list = []
    namespace = {
        "List": List, "BaseModel": BaseModel, "Field": Field,
        "asyncio": asyncio, "traceback": traceback, "HTTPException": HTTPException,
        "Depends": Depends, "get_current_user": lambda: None,
        "ChatPromptTemplate": ChatPromptTemplate, "AKKA_QUIZ_PROMPT": AKKA_QUIZ_PROMPT,
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(ROOT / "main.py"), "exec"), namespace)
    return namespace


class ImageSecurityTests(unittest.TestCase):
    def test_only_the_app_storage_path_is_allowed(self):
        self.assertEqual(validate_image_url(IMAGE, ORIGIN), IMAGE)
        for url in (
            "http://127.0.0.1/private", "http://169.254.169.254/latest/meta-data/",
            "https://example.supabase.co.evil.test/image.jpg",
            "https://example.supabase.co@evil.test/image.jpg",
            ORIGIN + ":444/storage/v1/object/public/chat-images/chat_uploads/test.jpg",
            ORIGIN + "/storage/v1/object/public/other-bucket/test.jpg",
            IMAGE + "?redirect=http://localhost", IMAGE + "#fragment",
            IMAGE.replace("test.jpg", "%2e%2e/secrets"),
            IMAGE.replace("test.jpg", "%252e%252e/secrets"),
            IMAGE.replace("test.jpg", "..\\secrets"),
        ):
            with self.subTest(url=url), self.assertRaises(HTTPException) as error:
                validate_image_url(url, ORIGIN)
            self.assertEqual(error.exception.status_code, 400)

    @patch("image_security.requests.get")
    def test_valid_image_is_streamed_without_redirects(self, request):
        response = Mock(status_code=200, headers={"Content-Type": "image/jpeg"})
        response.iter_content.return_value = [b"image", b"bytes"]
        request.return_value.__enter__.return_value = response
        self.assertEqual(download_chat_image(IMAGE, ORIGIN), (b"imagebytes", "image/jpeg"))
        self.assertFalse(request.call_args.kwargs["allow_redirects"])
        self.assertTrue(request.call_args.kwargs["stream"])

    @patch("image_security.requests.get")
    def test_redirects_non_images_and_oversized_uploads_are_rejected(self, request):
        for status, mime, chunks, expected in (
            (302, "image/jpeg", [], 400),
            (200, "text/html", [b"html"], 400),
            (200, "image/png", [], 400),
            (200, "image/png", [b"x" * MAX_IMAGE_BYTES, b"x"], 413),
        ):
            response = Mock(status_code=status, headers={"Content-Type": mime})
            response.iter_content.return_value = chunks
            request.return_value.__enter__.return_value = response
            with self.subTest(status=status, mime=mime, expected=expected), self.assertRaises(HTTPException) as error:
                download_chat_image(IMAGE, ORIGIN)
            self.assertEqual(error.exception.status_code, expected)


class QuizRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.routes = load_routes()
        self.database = Mock()
        self.routes["supabase"] = self.database
        self.database.rpc.return_value.execute.return_value.data = "2026-10-08"
        self.context = Mock(return_value="Textbook material")
        self.routes["get_context"] = self.context
        self.request = self.routes["QuizRequest"](
            subject="Science", grade_level=12, units=["Unit 1"],
            section="Section 1.2", num_questions=1,
        )
        self.question = dict(question="Which option?", options=["A", "B", "C", "D"],
                             correct_answer="B", explanation="B is correct")
        self.prompts = []
        self.model = Mock()
        self.routes["deepseek_llm"] = self.model
        self.set_model_output([self.question])

    def set_model_output(self, questions):
        def result(prompt):
            self.prompts.append(prompt.to_string())
            return self.routes["QuizResponse"](questions=questions)
        self.model.with_structured_output.return_value = RunnableLambda(result)

    async def test_quiz_prompt_and_response_match_the_client_contract(self):
        result = await self.routes["generate_quiz"](self.request, "student")
        self.assertEqual(result["questions"][0]["correct_answer"], "B")
        self.assertEqual(result["questions"][0]["option_b"], "B")
        self.assertIn("Class 12 Science", self.prompts[0])
        self.assertIn("exactly 1 MCQs", self.prompts[0])
        self.assertIn("Section 1.2", self.context.call_args.args[0])
        self.assertEqual([call.args[0] for call in self.database.rpc.call_args_list], ["reserve_daily_quiz"])

    async def test_limit_remains_403_without_using_the_model(self):
        self.database.rpc.return_value.execute.return_value.data = None
        with self.assertRaises(HTTPException) as error:
            await self.routes["generate_quiz"](self.request, "student")
        self.assertEqual(error.exception.status_code, 403)
        self.model.with_structured_output.assert_not_called()

    async def test_invalid_model_answers_release_the_daily_slot(self):
        self.set_model_output([{**self.question, "correct_answer": "Z"}])
        with self.assertRaises(HTTPException) as error:
            await self.routes["generate_quiz"](self.request, "student")
        self.assertEqual(error.exception.status_code, 502)
        self.database.rpc.assert_called_with("release_daily_quiz", {
            "target_user_id": "student", "usage_date": "2026-10-08",
        })

    async def test_empty_quiz_releases_the_daily_slot(self):
        self.set_model_output([])
        with self.assertRaises(HTTPException) as error:
            await self.routes["generate_quiz"](self.request, "student")
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(self.database.rpc.call_args.args[0], "release_daily_quiz")

    def test_question_counts_are_bounded(self):
        for count in (0, -1, 26, 100000):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                self.routes["QuizRequest"](subject="Science", grade_level=10, units=["Unit 1"], num_questions=count)

    async def test_question_from_another_session_cannot_be_scored(self):
        session_query = Mock()
        session_query.select.return_value = session_query
        session_query.eq.return_value = session_query
        session_query.execute.return_value.data = [{"id": "session-a", "status": "active", "current_question_index": 0}]
        question_query = Mock()
        question_query.select.return_value = question_query
        question_query.eq.return_value = question_query
        question_query.execute.return_value.data = []
        self.database.table.side_effect = lambda name: session_query if name == "quiz_sessions" else question_query
        data = self.routes["StudentAnswerRequest"](question_id="other-session-question", submitted_answer="B", student_name="Student")
        with self.assertRaises(HTTPException) as error:
            await self.routes["submit_answer"]("ABC123", data, "student")
        self.assertEqual(error.exception.status_code, 404)
        self.assertIn(unittest.mock.call("session_id", "session-a"), question_query.eq.call_args_list)
        question_query.insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
