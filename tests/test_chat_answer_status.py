"""Explicit uncertainty signals; all models and histories are synthetic."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from lesson_builder import load_example_graph
from pydantic import ValidationError
from study_builder import StudyError
from teaching_help import ChatInput, ChatResponse, ChatTurn, HelpResponse, build_learning_chat


class ChatAnswerStatusTests(unittest.TestCase):
    def test_model_facing_schema_requires_four_fields_and_no_storage_fields(self):
        schema = ChatResponse.model_json_schema()
        self.assertEqual(set(schema["required"]), {"response", "source", "review_required", "answer_status"})
        self.assertEqual(set(schema["properties"]), {"response", "source", "review_required", "answer_status"})
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("default", schema["properties"]["answer_status"])
        self.assertEqual(set(HelpResponse.model_json_schema()["properties"]), {"response", "source", "review_required"})

    def test_legacy_response_and_turn_default_answered_without_changing_review_status(self):
        result = ChatResponse(response="旧解释", source="model_candidate", review_required=True)
        self.assertEqual(result.answer_status, "answered")
        turn = ChatTurn(id=str(uuid4()), question="旧问题", response="旧解释", source="local_reference",
                        review_required=True, created_at="2026-10-12T01:00:00.000Z")
        self.assertEqual(turn.answer_status, "answered")
        self.assertTrue(turn.review_required)

    def test_chat_history_id_must_be_uuid_and_is_not_given_to_model(self):
        with self.assertRaises(ValidationError):
            ChatInput(question="数学问题", history_id="../../credentials")
        for status in ("answered", "uncertain", "unanswered"):
            output = json.dumps({"response": "针对性解释或具体未解决原因", "source": "local_reference",
                                 "review_required": False, "answer_status": status})
            with patch("teaching_help.generate_text", return_value=output) as model:
                result = build_learning_chat(ChatInput(question="数学问题", use_model=True, history_id=str(uuid4())))
            model.assert_called_once()
            prompt = json.loads(model.call_args.args[0])
            self.assertNotIn("history_id", prompt)
            self.assertEqual(result.answer_status, status)
            self.assertEqual(result.source, "model_candidate")
            self.assertTrue(result.review_required)
            self.assertIn("缺少条件", model.call_args.kwargs["instructions"])
            self.assertIn("answer_status", model.call_args.kwargs["json_schema"]["required"])

    def test_unknown_status_and_storage_fields_in_model_output_are_rejected_safely(self):
        for updates in ({"answer_status": "verified"}, {"answer_status": True}, {"answer_status": None},
                        {"problem_id": str(uuid4())}, {"api_key": "synthetic-secret-canary"}):
            output = json.dumps({"response": "一条解释", "source": "model_candidate", "review_required": True,
                                 "answer_status": "answered", **updates})
            with patch("teaching_help.generate_text", return_value=output) as model, self.assertRaises(StudyError) as caught:
                build_learning_chat(ChatInput(question="数学问题", use_model=True))
            self.assertNotIn("synthetic-secret-canary", str(caught.exception))
            model.assert_called_once()

    def test_provider_omitting_status_keeps_text_but_is_conservatively_uncertain(self):
        output = json.dumps({"response": "缺少条件，暂时无法回答", "source": "local_reference", "review_required": False})
        with patch("teaching_help.generate_text", return_value=output) as model:
            result = build_learning_chat(ChatInput(question="数学问题", use_model=True))
        model.assert_called_once()
        self.assertEqual(result.response, "缺少条件，暂时无法回答")
        self.assertEqual(result.answer_status, "uncertain")
        self.assertEqual(result.source, "model_candidate")
        self.assertTrue(result.review_required)

    def test_local_without_card_is_unanswered_and_existing_card_is_uncertain(self):
        with patch("teaching_help.generate_text", side_effect=AssertionError("不可调用模型")):
            missing = build_learning_chat(ChatInput(question="任意数学问题"))
            saved = build_learning_chat(ChatInput(graph=load_example_graph(), question="为什么取商？"))
        self.assertEqual(missing.answer_status, "unanswered")
        self.assertEqual(saved.answer_status, "uncertain")
        self.assertTrue(saved.review_required)

    def test_turn_rejects_unknown_answer_status_and_retains_explicit_unanswered(self):
        value = {"id": str(uuid4()), "node_id": None, "question": "问题", "response": "缺少假设，暂时不能回答",
                 "source": "model_candidate", "review_required": True, "created_at": "2026-10-12T01:00:00.000Z",
                 "answer_status": "unanswered"}
        self.assertEqual(ChatTurn.model_validate(value).model_dump(mode="json"), value)
        with self.assertRaises(ValidationError):
            ChatTurn.model_validate({**value, "answer_status": "verified"})


if __name__ == "__main__":
    unittest.main()
