"""学习过程的离线回归；全程使用合成配置与模型替身。"""

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from pydantic import ValidationError

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import graph_builder
import lesson_builder
import llm_client
import study_builder
from graph_builder import KnowledgeGraph, SourceNote, StudyTask
from lesson_builder import Lesson, LessonError
from model_settings import GenerationConfig
from study_builder import (Feedback, StudyError, build_learning_feedback, get_study_plan,
                           get_study_tasks, update_review_schedule)


CONFIG = GenerationConfig(provider="chatgpt", base_url="https://example.invalid/v1", model="offline-model",
                          api_format="responses", output_mode="json_schema", revision="synthetic-revision")


def small_graph():
    return KnowledgeGraph.model_validate({"target_id": "goal", "nodes": [
        {"id": "base", "label": "基础", "prerequisite_sets": []},
        {"id": "goal", "label": "目标", "prerequisite_sets": [["base"]]},
    ]})


def output_card(node_id="goal", context=""):
    return {"node_id": node_id, "title": "合成卡片", "definition": "定义说明", "intuition": "直观说明",
            "example": "例子说明", "proof_idea": "推理说明", "exercise": {
                "question": "合成选择题", "options": ["甲", "乙", "丙", "丁"], "correct_index": 1,
                "explanation": "选择乙的理由", "dimension": "definition"},
            "source": "generated", "math_context": context}


class StudyEngineTests(unittest.TestCase):
    def setUp(self):
        lesson_builder.clear_lesson_cache()
        self.addCleanup(lesson_builder.clear_lesson_cache)
        for module, name in ((llm_client, "get_usable_session"), (llm_client, "OpenAI"),
                             (graph_builder, "generate_text"), (lesson_builder, "generate_text"),
                             (study_builder, "generate_text")):
            mock = patch.object(module, name, side_effect=AssertionError("学习测试不得访问真实模型或凭证"))
            mock.start()
            self.addCleanup(mock.stop)
        for module in (lesson_builder, study_builder):
            mock = patch.object(module, "resolve_generation_config", return_value=CONFIG)
            mock.start()
            self.addCleanup(mock.stop)
        self.graph = lesson_builder.load_example_graph()

    def test_curated_plan_and_all_cards_retain_old_content_and_add_staged_tasks(self):
        self.assertEqual(len(self.graph.study_plan.diagnostics), 2)
        self.assertEqual(len(self.graph.study_plan.final_tasks), 2)
        self.assertEqual(len(self.graph.study_plan.criteria), 3)
        ids = set()
        for node in self.graph.nodes:
            lesson = lesson_builder.build_lesson(self.graph, node.id)
            self.assertEqual(lesson.math_context, self.graph.study_plan.math_context)
            self.assertEqual(len(lesson.followup_exercises), 2)
            self.assertIsNotNone(lesson.illustration)
            self.assertEqual([task.kind for task in lesson.learning_tasks], ["guided", "independent"])
            tasks = get_study_tasks(self.graph, node.id, "lesson", lesson)
            self.assertEqual(len(tasks), 6)
            for task in tasks:
                self.assertNotIn(task.id, ids)
                ids.add(task.id)
                self.assertEqual(len(task.hints), 3)
                StudyTask.model_validate_json(task.model_dump_json())
        global_tasks = get_study_tasks(self.graph)
        self.assertEqual({task.kind for task in global_tasks}, {"diagnostic", "final", "mixed"})
        self.assertEqual(len(ids | {task.id for task in global_tasks}), 53)

    def test_legacy_graph_and_cards_stay_valid_and_use_local_example(self):
        payload = self.graph.model_dump()
        payload.pop("study_plan")
        for node in payload["nodes"]:
            for field in ("rationale", "required_abilities", "branch_outcomes", "required_dimensions"):
                node.pop(field)
        legacy = KnowledgeGraph.model_validate(payload)
        self.assertEqual(lesson_builder.build_lesson(legacy, legacy.target_id).source, "curated_example")
        self.assertEqual(len(get_study_tasks(legacy, kind="diagnostic")), 2)
        old_card = output_card()
        old_card.pop("math_context")
        card = Lesson.model_validate(old_card)
        self.assertEqual(card.learning_tasks, [])
        self.assertEqual(card.math_context, "")

    def test_legacy_nonexample_has_honest_generic_diagnostic_and_final(self):
        graph = small_graph()
        plan = get_study_plan(graph)
        self.assertIn("未保存统一", plan.math_context)
        tasks = get_study_tasks(graph)
        self.assertEqual({task.kind for task in tasks}, {"diagnostic", "final"})
        feedback = build_learning_feedback(graph, "goal", plan.final_tasks[0].id, "这是我的尝试")
        self.assertEqual(feedback.outcome, "needs_review")
        self.assertTrue(feedback.review_required)

    def test_task_aliases_return_independent_copies_without_mutation(self):
        before = self.graph.model_dump()
        node = self.graph.nodes[0].id
        tasks = get_study_tasks(self.graph, node, "review")
        self.assertEqual([task.kind for task in tasks], ["retrieval"])
        tasks[0].question = "调用者修改"
        self.assertNotEqual(get_study_tasks(self.graph, node, "retrieval")[0].question, "调用者修改")
        self.assertEqual(self.graph.model_dump(), before)
        with self.assertRaises(StudyError):
            get_study_tasks(self.graph, "unknown")
        with self.assertRaises(StudyError):
            get_study_tasks(self.graph, kind="invalid")

    def test_choice_check_is_local_and_does_not_mark_node_mastery(self):
        node = self.graph.nodes[0].id
        task = get_study_tasks(self.graph, node, "exercise")[0]
        before = self.graph.model_dump()
        feedback = build_learning_feedback(self.graph, node, task.id, str(task.correct_index), use_model=True)
        self.assertEqual(feedback.outcome, "correct")
        self.assertEqual(feedback.source, "local_check")
        self.assertFalse(feedback.review_required)
        self.assertIn("不能代表", feedback.summary)
        self.assertEqual(self.graph.model_dump(), before)
        wrong = (task.correct_index + 1) % len(task.options)
        feedback = build_learning_feedback(self.graph, node, task.id, str(wrong))
        self.assertEqual(feedback.outcome, "incorrect")
        self.assertEqual(feedback.next_hint, task.hints[0])

    def test_choice_rejects_nonindexes_including_huge_integer_without_overflow(self):
        node = self.graph.nodes[0].id
        task = get_study_tasks(self.graph, node, "exercise")[0]
        for answer in ("４", "-1", "4", "1.0", "01", "1 " , "x", "9" * 5000):
            with self.subTest(answer=answer[:20]), self.assertRaises(StudyError):
                build_learning_feedback(self.graph, node, task.id, answer)

    def test_generated_choice_is_compared_but_answer_is_not_certified(self):
        graph = small_graph()
        lesson = Lesson.model_validate(output_card())
        task = get_study_tasks(graph, "goal", "exercise", lesson)[0]
        feedback = build_learning_feedback(graph, "goal", task.id, "1", lesson=lesson)
        self.assertEqual(feedback.outcome, "correct")
        self.assertTrue(feedback.review_required)
        self.assertIn("仍需核对", feedback.summary)

    def test_imported_curated_label_cannot_replace_the_local_answer_key(self):
        node = self.graph.nodes[0].id
        lesson = lesson_builder.build_lesson(self.graph, node)
        original = lesson.exercise.correct_index
        lesson.exercise.correct_index = (original + 1) % 4
        forged = get_study_tasks(self.graph, node, "exercise", lesson)[0]
        self.assertEqual(forged.correct_index, original)
        feedback = build_learning_feedback(self.graph, node, forged.id,
                                            str(lesson.exercise.correct_index), lesson=lesson)
        self.assertEqual(feedback.outcome, "incorrect")

    def test_open_local_feedback_never_uses_string_match_to_claim_correctness(self):
        node = self.graph.nodes[0].id
        task = get_study_tasks(self.graph, node, "guided")[0]
        for answer in (task.reference_answer, "明显错误的任意答案", "我用了另一个正确解法"):
            feedback = build_learning_feedback(self.graph, node, task.id, answer)
            self.assertEqual(feedback.outcome, "needs_review")
            self.assertEqual(feedback.source, "local_reference")
            self.assertTrue(feedback.review_required)
            self.assertTrue(all(step.status == "uncertain" for step in feedback.steps))
            self.assertEqual(feedback.reference_answer, task.reference_answer)

    def test_hint_progression_stops_at_three_and_handles_unknown_tasks(self):
        node = self.graph.nodes[0].id
        task = get_study_tasks(self.graph, node, "guided")[0]
        for level in range(4):
            feedback = build_learning_feedback(self.graph, node, task.id, "尝试", level)
            self.assertEqual(feedback.next_hint, task.hints[level] if level < 3 else None)
        for answer, level in (("", 0), (" ", 0), ("x" * 6001, 0), ("a", True), ("a", -1), ("a", 4)):
            with self.assertRaises(StudyError):
                build_learning_feedback(self.graph, node, task.id, answer, level)
        with self.assertRaises(StudyError):
            build_learning_feedback(self.graph, node, "unknown", "答案")

    def candidate(self, task):
        return {"node_id": task.node_id, "task_id": task.id, "outcome": "correct",
                "summary": "该不同解法的关键推理成立，仍请核对条件。",
                "steps": [{"criterion_id": item.id, "status": "satisfied", "comment": "依据用户说明核对这个要点。"} for item in task.rubric],
                "next_hint": None, "next_action": "independent_check", "source": "model_candidate",
                "review_required": True, "reference_answer": task.reference_answer}

    def test_explicit_model_feedback_uses_snapshot_full_context_and_rubric(self):
        node = self.graph.nodes[0].id
        task = get_study_tasks(self.graph, node, "independent")[0]
        alternative = "先用坐标对作减法，再改变基方向；这个写法与参考公式等价。"
        with patch.object(study_builder, "generate_text", return_value=json.dumps(self.candidate(task), ensure_ascii=False)) as model:
            feedback = build_learning_feedback(self.graph, node, task.id, alternative, use_model=True)
        model.assert_called_once()
        self.assertIs(model.call_args.kwargs["configuration"], CONFIG)
        self.assertEqual(model.call_args.kwargs["model"], CONFIG.model)
        payload = json.loads(model.call_args.args[0])
        self.assertEqual(payload["answer"], alternative)
        self.assertEqual(payload["graph"]["study_plan"]["math_context"], self.graph.study_plan.math_context)
        self.assertEqual(payload["task"]["rubric"], [item.model_dump() for item in task.rubric])
        self.assertTrue(feedback.review_required)
        self.assertEqual(feedback.source, "model_candidate")
        self.assertTrue(feedback.summary.startswith("AI 候选反馈"))

    def test_invalid_model_feedback_is_safe_and_not_replaced_by_local_success(self):
        node = self.graph.nodes[0].id
        task = get_study_tasks(self.graph, node, "independent")[0]
        marker = "synthetic-secret-must-never-be-in-error"
        for change in ({"source": "local_check"}, {"review_required": False}, {"task_id": "wrong"},
                       {"reference_answer": marker}, {"steps": []}, {"summary": " "}):
            output = {**self.candidate(task), **change}
            with patch.object(study_builder, "generate_text", return_value=json.dumps(output)), self.assertRaises(StudyError) as caught:
                build_learning_feedback(self.graph, node, task.id, "答案", use_model=True)
            self.assertNotIn(marker, str(caught.exception))
        for output in (marker, "x" * 30001, None):
            with patch.object(study_builder, "generate_text", return_value=output), self.assertRaises(StudyError) as caught:
                build_learning_feedback(self.graph, node, task.id, "答案", use_model=True)
            self.assertNotIn(marker, str(caught.exception))

    def test_graph_mode_and_model_sources_are_not_self_certified(self):
        output = self.graph.model_dump()
        with patch.object(graph_builder, "generate_text", return_value=json.dumps(output, ensure_ascii=False)) as model:
            graph = graph_builder.build_graph("目标文本", mode="proof")
        self.assertEqual(graph.study_plan.mode, "proof")
        self.assertTrue(all(note.review_status == "unverified" for note in graph.study_plan.source_notes))
        self.assertTrue(all(task.source == "generated" for task in graph.study_plan.diagnostics + graph.study_plan.final_tasks))
        self.assertEqual(json.loads(model.call_args.args[0])["study_mode"], "proof")

    def test_annotation_and_task_validation_catches_invalid_routes_and_references(self):
        payload = self.graph.model_dump()
        for change in (lambda x: x["nodes"][1].update(branch_outcomes=["甲", "乙"]),
                       lambda x: x["nodes"][1].update(required_dimensions=["definition", "definition"]),
                       lambda x: x["study_plan"]["diagnostics"][0].update(node_id="missing"),
                       lambda x: x["study_plan"]["diagnostics"][0].update(kind="final"),
                       lambda x: x["study_plan"]["final_tasks"][0].update(options=["额外选项"]),
                       lambda x: x["study_plan"]["final_tasks"][0].update(rubric=[{"id":"same","description":"甲"},{"id":"same","description":"乙"}])):
            changed = copy.deepcopy(payload)
            change(changed)
            with self.assertRaises(ValidationError):
                KnowledgeGraph.model_validate(changed)

    def test_source_notes_only_accept_https_and_have_verified_primary_locator(self):
        source = self.graph.study_plan.source_notes[0]
        self.assertIn("hatcher/AT/ATch2.pdf", source.url)
        self.assertIn("105", source.locator)
        for url in ("javascript:alert(1)", "http://example.org", "https://user:password@example.org", "https://example.org/\nunsafe"):
            with self.assertRaises(ValidationError):
                SourceNote.model_validate({**source.model_dump(), "url": url})

    def test_strict_generated_schema_requires_metadata_and_all_task_properties(self):
        for schema in (KnowledgeGraph.model_json_schema(), Lesson.model_json_schema(), Feedback.model_json_schema()):
            def walk(value):
                if isinstance(value, dict):
                    self.assertNotIn("default", value)
                    if value.get("type") == "object" and "properties" in value:
                        self.assertEqual(set(value["required"]), set(value["properties"]))
                        self.assertFalse(value["additionalProperties"])
                    for child in value.values():
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)
            walk(schema)

    def test_changed_math_context_cannot_silently_receive_curated_card(self):
        graph = self.graph.model_copy(deep=True)
        graph.study_plan.math_context = "合成测试采用其他系数；不是本地整数同调样例。"
        with patch.object(lesson_builder, "generate_text", return_value=json.dumps(output_card(graph.target_id, graph.study_plan.math_context))) as model:
            lesson = lesson_builder.build_lesson(graph, graph.target_id)
        model.assert_called_once()
        self.assertEqual(lesson.source, "generated")

    def test_context_and_goal_mode_are_part_of_generated_card_cache_identity(self):
        graph = small_graph()
        graph.study_plan = get_study_plan(graph)
        first = graph.model_copy(deep=True)
        second = graph.model_copy(deep=True)
        second.study_plan.math_context = "合成测试的另一套符号约定"
        third = graph.model_copy(deep=True)
        third.study_plan.mode = "proof"
        def output(prompt, **kwargs):
            item = json.loads(prompt)
            return json.dumps(output_card("goal", item["graph"]["study_plan"]["math_context"]))
        with patch.object(lesson_builder, "generate_text", side_effect=output) as model:
            lesson_builder.build_lesson(first, "goal")
            lesson_builder.build_lesson(first, "goal")
            lesson_builder.build_lesson(second, "goal")
            lesson_builder.build_lesson(third, "goal")
        self.assertEqual(model.call_count, 3)

    def test_generated_card_must_preserve_shared_math_context(self):
        graph = small_graph()
        graph.study_plan = get_study_plan(graph)
        with patch.object(lesson_builder, "generate_text", return_value=json.dumps(output_card("goal", "冲突的约定"))):
            with self.assertRaisesRegex(LessonError, "数学约定不一致"):
                lesson_builder.build_lesson(graph, "goal")
        with patch.object(lesson_builder, "generate_text", return_value=json.dumps(output_card("goal"))):
            lesson = lesson_builder.build_lesson(graph, "goal")
        self.assertEqual(lesson.math_context, graph.study_plan.math_context)

    def test_shared_direction_formula_produces_exact_cycle_condition(self):
        # This checks the displayed interaction's mathematics independently of UI.
        for a in range(-3, 4):
            for b in range(-3, 4):
                for c in range(-3, 4):
                    boundary = (-a-c, a-b, b+c)
                    self.assertEqual(boundary == (0, 0, 0), a == b == -c)
        self.assertIn("e₁₂−e₀₂+e₀₁", self.graph.study_plan.math_context)
        self.assertIn("没有2单形", self.graph.study_plan.math_context)


class ReviewScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)

    def test_confirmed_independent_evidence_grows_adjustable_intervals(self):
        previous = None
        for days in (1, 3, 7, 14, 30, 60, 60):
            previous = update_review_schedule(previous, "independent", attempted_at=self.now)
            self.assertEqual(previous["interval_days"], days)
            self.assertEqual(datetime.fromisoformat(previous["due_at"]), self.now + timedelta(days=days))

    def test_model_candidates_and_hints_never_count_as_independent_success(self):
        before = {"streak": 5, "interval_days": 30}
        for outcome, hint, review in (("correct", 0, True), ("independent", 1, False), ("viewed", 0, False),
                                      ("needs_review", 0, True), ("partial", 0, False), ("ungraded", 0, False)):
            result = update_review_schedule(before, outcome, hint, attempted_at=self.now, review_required=review)
            self.assertEqual(result["interval_days"], 1)
            self.assertEqual(result["streak"], 0)
        self.assertEqual(before, {"streak": 5, "interval_days": 30})

    def test_wrong_answer_returns_to_short_practice(self):
        result = update_review_schedule({"streak": 4}, "incorrect", attempted_at=self.now)
        self.assertEqual(result["interval_days"], 0)
        self.assertEqual(datetime.fromisoformat(result["due_at"]), self.now + timedelta(minutes=10))

    def test_iso_times_normalize_timezone_and_invalid_records_are_rejected(self):
        result = update_review_schedule(attempted_at="2026-10-12T12:00:00+08:00")
        self.assertEqual(result["last_attempt_at"], "2026-10-12T04:00:00+00:00")
        for args in ({"attempted_at": "invalid"}, {"attempted_at": "2026-10-12T12:00:00"},
                     {"attempted_at": datetime(2026, 10, 12)}, {"hint_level": True},
                     {"previous": {"streak": True}}, {"outcome": "automatic_mastery"},
                     {"attempted_at": datetime.max.replace(tzinfo=timezone.utc)}):
            with self.assertRaises(StudyError):
                update_review_schedule(**args)


if __name__ == "__main__":
    unittest.main()
