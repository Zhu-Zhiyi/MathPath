"""节点学习卡的离线回归检查；不读取授权记录，不调用真实模型。"""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from pydantic import ValidationError

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import lesson_builder
import llm_client
from graph_builder import KnowledgeGraph
from lesson_builder import Exercise, Lesson, LessonError, build_lesson
from model_settings import GenerationConfig


def example_graph():
    return KnowledgeGraph.model_validate_json(
        (PROJECT / "examples" / "homology_graph.json").read_text(encoding="utf-8"))


def small_graph():
    return KnowledgeGraph.model_validate({
        "target_id": "goal", "nodes": [
            {"id": "base", "label": "基础知识", "prerequisite_sets": []},
            {"id": "goal", "label": "理解目标", "prerequisite_sets": [["base"]]},
        ],
    })


def generated_card(node_id="goal"):
    return {
        "node_id": node_id, "title": "离线模拟学习卡",
        "definition": "这是离线格式验证内容，不代表真实模型生成。",
        "intuition": "一个简单的说明。", "example": "一个具体的例子。", "proof_idea": "一个推理要点。",
        "exercise": {"question": "离线测试题", "options": ["甲", "乙", "丙", "丁"],
                     "correct_index": 1, "explanation": "离线测试答案说明。", "dimension": "intuition"},
        "source": "generated",
    }


class LessonTests(unittest.TestCase):
    def setUp(self):
        lesson_builder.clear_lesson_cache()
        self.addCleanup(lesson_builder.clear_lesson_cache)
        configuration = patch.object(lesson_builder, "resolve_generation_config", side_effect=lambda *, default_model:
            GenerationConfig(provider="api", base_url="https://offline.example.test/v1", model=default_model,
                             api_format="chat_completions", output_mode="json_object", revision="offline-lesson-fixture",
                             api_key="synthetic-offline-key"))
        configuration.start()
        self.addCleanup(configuration.stop)
        for name in ("get_usable_session", "OpenAI"):
            guard = patch.object(llm_client, name, side_effect=AssertionError("学习卡测试必须离线"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_all_eight_curated_cards_are_valid_without_model_call(self):
        graph = example_graph()
        self.assertEqual(len(graph.nodes), 8)
        with patch.object(lesson_builder, "generate_text", side_effect=AssertionError("样例不应访问模型")):
            for node in graph.nodes:
                with self.subTest(node_id=node.id):
                    lesson = build_lesson(graph, node.id)
                    self.assertEqual(lesson.node_id, node.id)
                    self.assertEqual(lesson.source, "curated_example")
                    self.assertEqual(len(lesson.exercise.options), 4)
                    self.assertIn(lesson.exercise.correct_index, range(4))
                    self.assertIsInstance(Lesson.model_validate_json(lesson.model_dump_json()), Lesson)

    def test_canonical_match_allows_only_order_changes(self):
        data = example_graph().model_dump()
        data["nodes"].reverse()
        for node in data["nodes"]:
            for group in node["prerequisite_sets"]:
                group.reverse()
        graph = KnowledgeGraph.model_validate(data)
        with patch.object(lesson_builder, "generate_text", side_effect=AssertionError("顺序不改变图的含义")):
            lesson = build_lesson(graph, graph.target_id)
        self.assertEqual(lesson.source, "curated_example")

    def test_same_node_id_in_changed_label_graph_cannot_receive_curated_card(self):
        data = example_graph().model_dump()
        data["nodes"][0]["label"] = "另一个数学内容"
        graph = KnowledgeGraph.model_validate(data)
        card = generated_card(graph.target_id)
        with patch.object(lesson_builder, "generate_text", return_value=json.dumps(card, ensure_ascii=False)) as model:
            lesson = build_lesson(graph, graph.target_id)
        self.assertEqual(lesson.source, "generated")
        model.assert_called_once()

    def test_same_node_id_in_changed_dependencies_cannot_receive_curated_card(self):
        data = example_graph().model_dump()
        # Remove a redundant direct prerequisite; all nodes still serve the target.
        data["nodes"][-1]["prerequisite_sets"] = [["cycles_mod_boundaries"]]
        graph = KnowledgeGraph.model_validate(data)
        with patch.object(lesson_builder, "generate_text", return_value=json.dumps(generated_card(graph.target_id))) as model:
            lesson = build_lesson(graph, graph.target_id)
        self.assertEqual(lesson.source, "generated")
        model.assert_called_once()

    def test_generated_card_receives_entire_graph_and_strict_schema(self):
        graph = small_graph()
        with patch.object(lesson_builder, "generate_text", return_value=json.dumps(generated_card())) as model:
            lesson = build_lesson(graph, "goal")
        self.assertEqual(lesson.exercise.correct_index, 1)
        payload = json.loads(model.call_args.args[0])
        self.assertEqual(payload["graph"], graph.model_dump())
        self.assertEqual(payload["selected_node_id"], "goal")
        self.assertEqual(model.call_args.kwargs["json_schema"], Lesson.model_json_schema())
        self.assertIn("source 必须为 generated", model.call_args.kwargs["instructions"])

    def test_unknown_node_is_rejected_before_model_or_fixture(self):
        with patch.object(lesson_builder, "generate_text", side_effect=AssertionError("非法节点不应调用模型")):
            with self.assertRaisesRegex(LessonError, "不在当前学习图"):
                build_lesson(small_graph(), "missing")

    def test_generated_card_must_match_requested_node_and_source(self):
        for change in ({"node_id": "base"}, {"source": "curated_example"}):
            with self.subTest(change=change):
                card = generated_card()
                card.update(change)
                with patch.object(lesson_builder, "generate_text", return_value=json.dumps(card)):
                    with self.assertRaisesRegex(LessonError, "与所选知识点不一致"):
                        build_lesson(small_graph(), "goal")

    def test_parser_errors_do_not_echo_model_content(self):
        sensitive_marker = "synthetic-private-content-should-not-appear"
        invalid = [sensitive_marker, json.dumps({"node_id": sensitive_marker}),
                   json.dumps({**generated_card(), "definition": " "}), "x" * 80_001]
        for output in invalid:
            with self.subTest(output_length=len(output)):
                with patch.object(lesson_builder, "generate_text", return_value=output):
                    with self.assertRaises(LessonError) as error:
                        build_lesson(small_graph(), "goal")
                self.assertNotIn(sensitive_marker, str(error.exception))

    def test_model_failure_propagates_without_curated_fallback(self):
        graph = example_graph()
        data = graph.model_dump()
        data["nodes"][0]["label"] = "新的知识点名称"
        graph = KnowledgeGraph.model_validate(data)
        failure = RuntimeError("离线模拟模型失败")
        with patch.object(lesson_builder, "generate_text", side_effect=failure):
            with self.assertRaises(RuntimeError) as error:
                build_lesson(graph, graph.target_id)
        self.assertIs(error.exception, failure)

    def test_exercise_rejects_ambiguous_or_invalid_options_and_answers(self):
        valid = generated_card()["exercise"]
        cases = [
            {"options": ["甲", "乙", "丙"]},
            {"options": ["甲", "乙", "丙", " "]},
            {"options": ["甲", "乙", "丙", " 甲 "]},
            {"options": ["a", "A", "b", "c"]},
            {"options": ["甲", "乙", "丙", "丁" * 351]},
            {"correct_index": -1}, {"correct_index": 4}, {"correct_index": True},
            {"correct_index": "1"}, {"dimension": "mastery"},
            {"question": "\t"}, {"explanation": " "}, {"extra": "禁止额外字段"},
        ]
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(ValidationError):
                    Exercise.model_validate({**copy.deepcopy(valid), **change})

    def test_card_fields_have_required_content_and_bounds(self):
        for field in ("title", "definition", "intuition", "example", "proof_idea"):
            for value in (" ", "x" * 1201):
                with self.subTest(field=field, length=len(value)):
                    with self.assertRaises(ValidationError):
                        Lesson.model_validate({**generated_card(), field: value})
        with self.assertRaises(ValidationError):
            Lesson.model_validate({**generated_card(), "extra": "禁止额外字段"})

    def test_schema_exposes_exact_options_and_answer_bounds(self):
        schema = Lesson.model_json_schema()
        exercise = schema["$defs"]["Exercise"]
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(exercise["additionalProperties"])
        self.assertEqual(exercise["properties"]["options"]["minItems"], 4)
        self.assertEqual(exercise["properties"]["options"]["maxItems"], 4)
        self.assertEqual(exercise["properties"]["options"]["items"]["maxLength"], 350)
        self.assertEqual(exercise["properties"]["correct_index"]["minimum"], 0)
        self.assertEqual(exercise["properties"]["correct_index"]["maximum"], 3)


if __name__ == "__main__":
    unittest.main()
