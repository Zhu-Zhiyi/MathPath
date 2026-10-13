"""Library schemas reject coercion, extra account fields and mismatched graph state."""

import copy
from pathlib import Path
import sys
import unittest
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from pydantic import ValidationError
from library_models import HistoryCreate, HistoryUpdate, IdBatch, ProjectCreate, StudyAttempt, StudyState
from test_library_store import attempt, graph


class LibraryModelTests(unittest.TestCase):
    def test_mastery_accepts_only_actual_booleans(self):
        for value in ("true", 1, None):
            with self.assertRaises(ValidationError):
                StudyState.model_validate({"mastery": {"base": {"definition": value}}})

    def test_unknown_fields_are_rejected_at_every_nested_level(self):
        values = [{"api_key": "secret"}, {"mastery": {"base": {"definition": True, "api_key": "secret"}}},
                  {"attempts": [attempt(access_token="secret")]},
                  {"reviews": {"base": {"due_at": "2026-10-12T00:00:00.000Z", "api_key": "secret"}}}]
        for value in values:
            with self.assertRaises(ValidationError):
                StudyState.model_validate(value)

    def test_all_graph_state_references_are_checked(self):
        for state in ({"mastery": {"missing": {}}}, {"notes": {"missing": ""}},
                      {"attempts": [attempt(node_id="missing")]}, {"active_node_id": "missing"},
                      {"reviews": {"missing": {"due_at": "2026-10-12T00:00:00.000Z"}}}):
            with self.assertRaises(ValidationError):
                HistoryCreate(title="目标", goal="测试", graph=graph(), state=state)

    def test_attempt_ids_must_be_unique(self):
        value = attempt()
        with self.assertRaises(ValidationError):
            StudyState.model_validate({"attempts": [value, value]})

    def test_attempt_limit_is_500(self):
        values = [attempt() for _ in range(500)]
        self.assertEqual(len(StudyState.model_validate({"attempts": values}).attempts), 500)
        with self.assertRaises(ValidationError):
            StudyState.model_validate({"attempts": values + [attempt()]})

    def test_timestamp_must_be_real_date_and_include_timezone(self):
        for value in ("2026-10-12T00:00:00.000", "2026-99-99T00:00:00.000Z", "something malicious and long"):
            with self.assertRaises(ValidationError):
                StudyAttempt.model_validate(attempt(created_at=value))

    def test_feedback_matches_attempt_task(self):
        feedback = {"node_id": "other", "task_id": "task", "outcome": "needs_review", "summary": "待核查",
                    "steps": [], "next_hint": None, "next_action": "compare_reference", "source": "model_candidate",
                    "review_required": True, "reference_answer": "参考"}
        with self.assertRaises(ValidationError):
            StudyAttempt.model_validate(attempt(feedback=feedback))

    def test_generated_or_reference_feedback_cannot_claim_human_review_unneeded(self):
        for source in ("model_candidate", "local_reference"):
            feedback = {"node_id": "base", "task_id": "exercise:base:0", "outcome": "correct", "summary": "待核查",
                        "steps": [], "next_hint": None, "next_action": "continue", "source": source,
                        "review_required": False, "reference_answer": "参考"}
            with self.assertRaises(ValidationError):
                StudyAttempt.model_validate(attempt(feedback=feedback))

    def test_independent_evidence_cannot_also_use_hints(self):
        with self.assertRaises(ValidationError):
            StudyAttempt.model_validate(attempt(hint_level=1, outcome="independent"))
        self.assertEqual(StudyAttempt.model_validate(attempt(hint_level=0, outcome="independent", feedback=None)).outcome,
                         "independent")

    def test_uncertain_or_failed_feedback_cannot_be_independent_evidence(self):
        for outcome, review_required, source in (("correct", True, "model_candidate"), ("partial", False, "local_check"),
                                                 ("incorrect", False, "local_check"), ("needs_review", True, "local_reference")):
            feedback = {"node_id": "base", "task_id": "exercise:base:0", "outcome": outcome, "summary": "核对推理",
                        "steps": [], "next_hint": None, "next_action": "compare_reference", "source": source,
                        "review_required": review_required, "reference_answer": "参考答案"}
            with self.assertRaises(ValidationError):
                StudyAttempt.model_validate(attempt(outcome="independent", feedback=feedback))

    def test_patch_requires_revision_and_at_least_one_real_change(self):
        for value in ({"title": "目标"}, {"expected_revision": True, "title": "目标"}, {"expected_revision": 1},
                      {"expected_revision": 1, "state": None}, {"expected_revision": 1, "title": "  "}):
            with self.assertRaises(ValidationError):
                HistoryUpdate.model_validate(value)
        self.assertIn("project_id", HistoryUpdate(expected_revision=1, project_id=None).model_fields_set)

    def test_empty_control_or_oversize_titles_are_rejected(self):
        for value in ("  ", "a\nb", "x" * 121):
            with self.assertRaises(ValidationError):
                ProjectCreate(title=value)

    def test_uuid_batch_is_bounded_and_duplicate_free(self):
        for values in ([], [str(uuid4())] * 2, [str(uuid4()) for _ in range(201)], ["not-a-uuid"]):
            with self.assertRaises(ValidationError):
                IdBatch(ids=values)

    def test_lesson_keys_must_match_lesson_nodes(self):
        from lesson_builder import build_lesson, load_example_graph
        original = load_example_graph()
        lesson = build_lesson(original, original.nodes[0].id)
        with self.assertRaises(ValidationError):
            StudyState(lessons={"different": lesson})

    def test_saved_lesson_cannot_silently_change_shared_math_context(self):
        from graph_builder import StudyPlan
        from lesson_builder import build_lesson, load_example_graph
        original = load_example_graph()
        lesson = build_lesson(original, original.nodes[0].id)
        changed = original.model_copy(deep=True)
        changed.study_plan = StudyPlan(mode="intuition", objective="解释同调", criteria=["区分循环与边界"],
                                       math_context="本次采用与旧卡片不同的系数约定。")
        with self.assertRaises(ValidationError):
            HistoryCreate(title="学习", goal="同调", graph=changed, state={"lessons": {lesson.node_id: lesson}})


if __name__ == "__main__":
    unittest.main()
