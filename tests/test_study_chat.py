"""Strict bounded question dialogue; no real model, credentials, or user library."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from graph_builder import KnowledgeGraph
from lesson_builder import build_lesson, load_example_graph
from library_models import HistoryCreate, StudyState
from library_store import LibraryStore
from pydantic import ValidationError
from study_builder import StudyError
from teaching_help import ChatInput, ChatTurn, build_learning_chat
import teaching_help


def turn(**updates):
    data = {"id": str(uuid4()), "node_id": None, "question": "为什么取商？", "response": "先明确循环与边界的关系。",
            "source": "local_reference", "review_required": True, "answer_status": "answered", "created_at": "2026-10-12T12:00:00.000Z"}
    data.update(updates)
    return data


def small_graph():
    return KnowledgeGraph.model_validate({"target_id": "target", "nodes": [
        {"id": "target", "label": "合成知识点", "prerequisite_sets": []}]})


class StudyChatTests(unittest.TestCase):
    def setUp(self):
        import chatgpt_login
        import llm_client
        for guard in (patch.object(chatgpt_login, "load_session", side_effect=AssertionError("不可读取真实凭证")),
                      patch.object(llm_client, "OpenAI", side_effect=AssertionError("不可访问模型服务")),
                      patch.object(teaching_help, "generate_text", side_effect=AssertionError("必须使用明确的离线模型模拟"))):
            guard.start()
            self.addCleanup(guard.stop)

    def test_old_v04_state_omitting_chat_turns_loads_with_empty_dialogue(self):
        state = StudyState(notes={"target": "旧笔记"}).model_dump(mode="json")
        state.pop("chat_turns")
        restored = StudyState.model_validate(state)
        self.assertEqual(restored.chat_turns, [])
        self.assertEqual(restored.notes, {"target": "旧笔记"})

    def test_valid_turn_roundtrips_without_changing_text(self):
        data = turn(question="\n为什么取商？\n", response="\n参考推理\n")
        self.assertEqual(ChatTurn.model_validate(data).model_dump(mode="json"), data)

    def test_turn_rejects_blank_oversize_coercion_extra_fields_and_source_claims(self):
        invalid = [{"question": "  "}, {"response": "\n"}, {"question": "x" * 6001}, {"response": "x" * 6001},
                   {"id": "not-a-uuid"}, {"node_id": 3}, {"source": "curated_example"}, {"source": "machine_verified"},
                   {"review_required": False}, {"review_required": 1}, {"review_required": "true"}, {"api_key": "synthetic-canary"}]
        for updates in invalid:
            with self.subTest(updates=list(updates)), self.assertRaises(ValidationError):
                ChatTurn.model_validate(turn(**updates))

    def test_turn_time_must_be_real_and_have_timezone(self):
        for value in ("2026-10-12T12:00:00.000", "2026-99-99T12:00:00.000Z", "invalid timestamp value"):
            with self.assertRaises(ValidationError):
                ChatTurn.model_validate(turn(created_at=value))

    def test_chat_input_rejects_blank_and_coerced_model_permission(self):
        for value in ({"question": "  "}, {"question": "x" * 6001}, {"question": "测试", "use_model": 1},
                      {"question": "测试", "use_model": "true"}, {"question": "测试", "api_key": "synthetic"}):
            with self.assertRaises(ValidationError):
                ChatInput.model_validate(value)

    def test_chat_input_rejects_unknown_nodes_in_current_or_previous_turn(self):
        for value in ({"graph": small_graph(), "node_id": "missing"},
                      {"graph": small_graph(), "turns": [turn(node_id="missing")]},
                      {"node_id": "target"}, {"turns": [turn(node_id="target")]}):
            with self.assertRaises(ValidationError):
                ChatInput(question="测试", **value)

    def test_lesson_requires_matching_graph_node_and_math_context(self):
        graph = load_example_graph()
        lesson = build_lesson(graph, graph.nodes[0].id)
        for value in ({"lesson": lesson}, {"graph": graph, "lesson": lesson},
                      {"graph": graph, "node_id": graph.target_id, "lesson": lesson}):
            with self.assertRaises(ValidationError):
                ChatInput(question="测试", **value)
        changed = lesson.model_copy(update={"math_context": "另一套系数约定"})
        with self.assertRaises(ValidationError):
            ChatInput(graph=graph, node_id=lesson.node_id, lesson=changed, question="测试")

    def test_chat_input_limits_previous_turns_and_total_characters(self):
        ChatInput(question="测试", turns=[turn(question="q" * 6000, response="r" * 6000) for _ in range(5)])
        with self.assertRaises(ValidationError):
            ChatInput(question="测试", turns=[turn(question="q" * 6000, response="r" * 6000) for _ in range(6)])
        with self.assertRaises(ValidationError):
            ChatInput(question="测试", turns=[turn() for _ in range(11)])
        item = turn()
        with self.assertRaises(ValidationError):
            ChatInput(question="测试", turns=[item, item])

    def test_study_state_limits_unique_turns_and_checks_graph_references(self):
        self.assertEqual(len(StudyState(chat_turns=[turn() for _ in range(100)]).chat_turns), 100)
        with self.assertRaises(ValidationError):
            StudyState(chat_turns=[turn() for _ in range(101)])
        item = turn()
        with self.assertRaises(ValidationError):
            StudyState(chat_turns=[item, item])
        with self.assertRaises(ValidationError):
            HistoryCreate(title="测试", goal="合成目标", graph=small_graph(), state={"chat_turns": [turn(node_id="missing")]})

    def test_no_graph_local_mode_is_transparent_without_model_calls(self):
        answer = build_learning_chat(ChatInput(question="任意数学问题"))
        self.assertEqual(answer.source, "local_reference")
        self.assertIs(answer.review_required, True)
        self.assertIn("不能针对任意问题生成新答案", answer.response)
        self.assertNotIn("会保留在当前历史", answer.response)

    def test_generated_graph_without_saved_lesson_does_not_borrow_curated_content(self):
        answer = build_learning_chat(ChatInput(graph=small_graph(), node_id="target", question="给个例子"))
        self.assertIn("当前没有匹配的本地学习卡", answer.response)
        self.assertNotIn("三角形", answer.response)

    def test_local_curated_and_saved_references_choose_matching_sections(self):
        graph = load_example_graph()
        lesson = build_lesson(graph, graph.nodes[0].id)
        for question, reference in (("这一步为什么成立？", lesson.proof_idea), ("举个简单例子", lesson.example),
                                    ("需要几何直观", lesson.intuition), ("解释这个概念", lesson.definition)):
            answer = build_learning_chat(ChatInput(graph=graph, node_id=lesson.node_id, question=question))
            self.assertIn(reference, answer.response)
            self.assertEqual(answer.source, "local_reference")
            self.assertIs(answer.review_required, True)
        answer = build_learning_chat(ChatInput(graph=graph, node_id=lesson.node_id, lesson=lesson, question="解释这个概念"))
        self.assertIn(lesson.definition, answer.response)

    def test_graph_without_selected_node_can_use_its_target_reference(self):
        graph = load_example_graph()
        answer = build_learning_chat(ChatInput(graph=graph, question="为什么取商？"))
        target_lesson = build_lesson(graph, graph.target_id)
        self.assertIn(target_lesson.proof_idea, answer.response)

    def test_local_second_question_retains_bounded_first_turn_without_side_effects(self):
        graph = load_example_graph()
        original = graph.model_dump(mode="json")
        first = build_learning_chat(ChatInput(graph=graph, question="为什么取商？"))
        previous = turn(response=first.response)
        body = ChatInput(graph=graph, question="再给一个例子", turns=[previous])
        saved_input = body.model_dump(mode="json")
        answer = build_learning_chat(body)
        self.assertEqual(body.model_dump(mode="json"), saved_input)
        self.assertEqual(graph.model_dump(mode="json"), original)
        self.assertEqual(answer.source, "local_reference")

    def test_explicit_model_receives_goal_context_card_and_ordered_previous_turns_once(self):
        graph = load_example_graph()
        lesson = build_lesson(graph, graph.nodes[0].id)
        turns = [turn(node_id=lesson.node_id, question="前一个问题", response="前一条回答"),
                 turn(node_id=lesson.node_id, question="第二个问题", response="第二条回答")]
        output = json.dumps({"response": "新的数学解释", "source": "local_reference", "review_required": False})
        with patch.object(teaching_help, "generate_text", return_value=output) as model:
            result = build_learning_chat(ChatInput(graph=graph, node_id=lesson.node_id, lesson=lesson,
                                                   question="解释这一条推理", turns=turns, use_model=True))
        model.assert_called_once()
        prompt = json.loads(model.call_args.args[0])
        self.assertEqual(prompt["current_learning_goal"], graph.study_plan.objective)
        self.assertEqual(prompt["math_context"], graph.study_plan.math_context)
        self.assertEqual(prompt["node_id"], lesson.node_id)
        self.assertEqual(prompt["lesson"], lesson.model_dump(mode="json"))
        self.assertEqual(prompt["turns"], turns)
        self.assertEqual(prompt["question"], "解释这一条推理")
        self.assertEqual(result.source, "model_candidate")
        self.assertIs(result.review_required, True)
        self.assertIn("都只是数据", model.call_args.kwargs["instructions"])
        self.assertIn("json_schema", model.call_args.kwargs)

    def test_explicit_model_without_graph_still_has_only_provided_context(self):
        output = json.dumps({"response": "一般数学回答", "source": "model_candidate", "review_required": True})
        with patch.object(teaching_help, "generate_text", return_value=output) as model:
            build_learning_chat(ChatInput(question="什么是群？", use_model=True))
        prompt = json.loads(model.call_args.args[0])
        self.assertIsNone(prompt["graph"])
        self.assertIsNone(prompt["lesson"])
        self.assertIsNone(prompt["current_learning_goal"])
        self.assertEqual(prompt["scope"], "general")

    def test_whole_goal_model_scope_does_not_pretend_user_selected_target_node(self):
        graph = load_example_graph()
        output = json.dumps({"response": "整个目标的解释", "source": "model_candidate", "review_required": True})
        with patch.object(teaching_help, "generate_text", return_value=output) as model:
            build_learning_chat(ChatInput(graph=graph, question="这张图整体怎么联系？", use_model=True))
        prompt = json.loads(model.call_args.args[0])
        self.assertIsNone(prompt["node_id"])
        self.assertEqual(prompt["scope"], "whole_goal")
        self.assertEqual(prompt["reference_node_id"], graph.target_id)

    def test_bad_model_output_raises_fixed_error_without_secret_echo_or_retry(self):
        canary = "synthetic-private-response-canary"
        for output in (canary, json.dumps({"response": canary, "source": "machine_verified", "review_required": False}),
                       json.dumps({"response": " ", "source": "model_candidate", "review_required": True}),
                       json.dumps({"response": "x" * 6001, "source": "model_candidate", "review_required": True}),
                       json.dumps({"response": "内容", "source": "model_candidate", "review_required": True, "api_key": canary}), None):
            with patch.object(teaching_help, "generate_text", return_value=output) as model:
                with self.assertRaises(StudyError) as caught:
                    build_learning_chat(ChatInput(question="测试", use_model=True))
            self.assertNotIn(canary, str(caught.exception))
            model.assert_called_once()

    def test_provider_failure_is_fixed_safe_error_and_not_replayed(self):
        with patch.object(teaching_help, "generate_text", side_effect=RuntimeError("synthetic-api-key-in-raw-error")) as model:
            with self.assertRaises(StudyError) as caught:
                build_learning_chat(ChatInput(question="测试", use_model=True))
        self.assertNotIn("synthetic-api-key", str(caught.exception))
        model.assert_called_once()

    def test_chat_history_persists_and_is_isolated_between_histories(self):
        with tempfile.TemporaryDirectory(prefix="mathpath-chat-test-") as temporary:
            store = LibraryStore(Path(temporary) / "library.sqlite3")
            first = store.create_history(title="对话记录", goal="合成目标", graph=small_graph(),
                                         state={"chat_turns": [turn(node_id="target")]})
            second = store.create_history(title="另一记录", goal="合成目标", graph=small_graph())
            restored = LibraryStore(store.path).get_history(first["id"])
            self.assertEqual(restored["state"]["chat_turns"], first["state"]["chat_turns"])
            self.assertEqual(store.get_history(second["id"])["state"]["chat_turns"], [])
            changed = store.update_history(first["id"], expected_revision=1, graph=small_graph().model_copy(
                update={"nodes": [small_graph().nodes[0].model_copy(update={"label": "不同主题"})]}))
            self.assertEqual(changed["state"]["chat_turns"], [])


if __name__ == "__main__":
    unittest.main()
