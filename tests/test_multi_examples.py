"""Reviewed offline examples: scope, provenance, answer-key ownership and calculations."""

import copy
from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_builder import KnowledgeGraph
import lesson_builder
from lesson_builder import Lesson, LessonError, build_lesson, curated_example_id, list_examples, load_example_graph
from study_builder import build_learning_feedback, get_study_plan, get_study_tasks


def exact_rank(matrix):
    """Independent rational row reduction for checking authored finite examples."""
    rows = [[Fraction(value) for value in row] for row in matrix]
    pivot_row = 0
    for col in range(len(rows[0])):
        candidate = next((i for i in range(pivot_row, len(rows)) if rows[i][col]), None)
        if candidate is None:
            continue
        rows[pivot_row], rows[candidate] = rows[candidate], rows[pivot_row]
        pivot = rows[pivot_row][col]
        rows[pivot_row] = [value / pivot for value in rows[pivot_row]]
        for i in range(len(rows)):
            if i != pivot_row:
                factor = rows[i][col]
                rows[i] = [a - factor * b for a, b in zip(rows[i], rows[pivot_row])]
        pivot_row += 1
        if pivot_row == len(rows):
            break
    return pivot_row


def product(matrix, vector):
    return tuple(sum(a * b for a, b in zip(row, vector)) for row in matrix)


class MultiExampleTests(unittest.TestCase):
    def setUp(self):
        self.model_guard = patch.object(lesson_builder, "generate_text", side_effect=AssertionError("offline content must not call models"))
        self.model_guard.start()
        self.addCleanup(self.model_guard.stop)
        self.config_guard = patch.object(lesson_builder, "resolve_generation_config", side_effect=AssertionError("offline content must not read credentials"))
        self.config_guard.start()
        self.addCleanup(self.config_guard.stop)

    def all_tasks(self, graph):
        tasks = get_study_tasks(graph)
        for node in graph.nodes:
            tasks.extend(get_study_tasks(graph, node.id, "lesson", build_lesson(graph, node.id)))
        return tasks

    def test_catalog_default_and_allowlist(self):
        catalog = list_examples()
        self.assertEqual([item["id"] for item in catalog], ["homology", "rank_nullity", "epsilon_delta"])
        self.assertTrue(all(set(item) == {"id", "title", "description", "goal"} for item in catalog))
        self.assertEqual(load_example_graph().model_dump(), load_example_graph("homology").model_dump())
        catalog[0]["title"] = "caller changed"
        self.assertNotEqual(list_examples()[0]["title"], "caller changed")
        for value in ("../homology", "HOMOLOGY", "missing", "homology_graph.json"):
            with self.subTest(value=value), self.assertRaises(LessonError):
                load_example_graph(value)

    def test_complete_cards_shared_context_and_counts(self):
        union = set()
        for name, nodes, total in (("homology", 8, 53), ("rank_nullity", 6, 41), ("epsilon_delta", 6, 41)):
            graph = load_example_graph(name)
            self.assertEqual(curated_example_id(graph), name)
            self.assertEqual(len(graph.nodes), nodes)
            self.assertEqual(len(graph.study_plan.diagnostics), 2)
            self.assertEqual(len(graph.study_plan.final_tasks), 2)
            self.assertEqual(len(graph.study_plan.criteria), 3)
            before = graph.model_dump()
            for node in graph.nodes:
                card = build_lesson(graph, node.id)
                Lesson.model_validate_json(card.model_dump_json())
                self.assertEqual(card.math_context, graph.study_plan.math_context)
                self.assertEqual(card.source, "curated_example")
                self.assertEqual(len(card.exercise.options), 4)
                self.assertEqual(len(card.followup_exercises), 2)
                self.assertEqual([item.kind for item in card.learning_tasks], ["guided", "independent"])
                self.assertIsNotNone(card.illustration)
                self.assertTrue(all(item.review_status == "curated" for item in card.source_notes))
                self.assertEqual(len(get_study_tasks(graph, node.id, "lesson", card)), 6)
            tasks = self.all_tasks(graph)
            ids = {item.id for item in tasks}
            self.assertEqual(len(tasks), total)
            self.assertEqual(len(ids), total)
            self.assertFalse(union.intersection(ids))
            union.update(ids)
            self.assertTrue(all(len(item.hints) == 3 for item in tasks))
            self.assertEqual(graph.model_dump(), before)
        self.assertEqual(len(union), 135)

    def test_new_examples_exact_context_and_metadata_required(self):
        for name in ("rank_nullity", "epsilon_delta"):
            source = load_example_graph(name)
            for modification in ("context", "no_plan", "label", "rationale", "abilities", "dimensions", "answer"):
                value = source.model_dump()
                if modification == "context": value["study_plan"]["math_context"] += " 使用另一系数或约定。"
                elif modification == "no_plan": value["study_plan"] = None
                elif modification == "label": value["nodes"][0]["label"] += " 修改"
                elif modification == "rationale": value["nodes"][0]["rationale"] = ""
                elif modification == "abilities": value["nodes"][0]["required_abilities"] = []
                elif modification == "dimensions": value["nodes"][0]["required_dimensions"] = ["application"]
                elif modification == "answer": value["study_plan"]["diagnostics"][0]["correct_index"] = 0
                graph = KnowledgeGraph.model_validate(value)
                with self.subTest(name=name, modification=modification):
                    self.assertIsNone(curated_example_id(graph))
                    self.assertIsNone(lesson_builder._curated_lesson(graph, graph.target_id))

    def test_new_modes_can_share_math_but_not_change_objective(self):
        for name in ("rank_nullity", "epsilon_delta"):
            for mode in ("intuition", "application", "proof"):
                graph = load_example_graph(name)
                graph.study_plan.mode = mode
                self.assertEqual(curated_example_id(graph), name)
                self.assertEqual(build_lesson(graph, graph.target_id).math_context, graph.study_plan.math_context)
            graph.study_plan.objective += " 新问题"
            self.assertIsNone(curated_example_id(graph))

    def test_legacy_homology_without_metadata_still_has_exact_53_tasks(self):
        value = load_example_graph().model_dump()
        value.pop("study_plan")
        for node in value["nodes"]:
            for key in ("rationale", "required_abilities", "branch_outcomes", "required_dimensions"):
                node.pop(key)
        graph = KnowledgeGraph.model_validate(value)
        self.assertEqual(curated_example_id(graph), "homology")
        self.assertEqual(len(self.all_tasks(graph)), 53)
        self.assertIn("整数系数", get_study_plan(graph).math_context)

    def test_curated_choice_keys_are_owned_locally_for_all_examples(self):
        for name in ("homology", "rank_nullity", "epsilon_delta"):
            graph = load_example_graph(name)
            node = graph.nodes[0].id
            genuine = build_lesson(graph, node)
            forged = genuine.model_copy(deep=True)
            forged.exercise.correct_index = (genuine.exercise.correct_index + 1) % 4
            forged.exercise.explanation = "client-provided forged answer"
            task = get_study_tasks(graph, node, "exercise", forged)[0]
            self.assertEqual(task.correct_index, genuine.exercise.correct_index)
            self.assertNotEqual(task.reference_answer, forged.exercise.explanation)
            good = build_learning_feedback(graph, node, task.id, str(genuine.exercise.correct_index), lesson=forged)
            self.assertEqual(good.outcome, "correct")
            self.assertFalse(good.review_required)
            bad = build_learning_feedback(graph, node, task.id, str(forged.exercise.correct_index), lesson=forged)
            self.assertEqual(bad.outcome, "incorrect")

    def test_changed_context_never_certifies_imported_curated_answer_key(self):
        for name in ("rank_nullity", "epsilon_delta"):
            graph = load_example_graph(name)
            node = graph.nodes[0].id
            lesson = build_lesson(graph, node)
            graph.study_plan.math_context += " changed"
            feedback = build_learning_feedback(graph, node, f"{node}_exercise", str(lesson.exercise.correct_index), lesson=lesson)
            self.assertTrue(feedback.review_required)
            self.assertIsNone(curated_example_id(graph))

    def test_open_feedback_is_always_reference_comparison(self):
        for name in ("rank_nullity", "epsilon_delta"):
            graph = load_example_graph(name)
            for kind in ("guided", "independent", "retrieval", "final", "mixed"):
                node = graph.target_id
                tasks = get_study_tasks(graph, node, kind, build_lesson(graph, node))
                self.assertTrue(tasks)
                for task in tasks:
                    feedback = build_learning_feedback(graph, node, task.id, task.reference_answer)
                    self.assertEqual(feedback.outcome, "needs_review")
                    self.assertTrue(feedback.review_required)
                    self.assertEqual(feedback.source, "local_reference")

    def test_topic_mixed_task_not_borrowed_from_homology(self):
        for name in ("rank_nullity", "epsilon_delta"):
            graph = load_example_graph(name)
            tasks = get_study_tasks(graph, kind="mixed")
            self.assertEqual(len(tasks), 1)
            self.assertTrue(tasks[0].id.startswith(name))
            self.assertNotIn("同调", tasks[0].question)
            self.assertNotIn("边界链", tasks[0].reference_answer)

    def test_registry_returns_deep_independent_objects(self):
        for name in ("rank_nullity", "epsilon_delta"):
            graph = load_example_graph(name)
            node = graph.target_id
            graph.nodes[0].label = "caller changed"
            self.assertNotEqual(load_example_graph(name).nodes[0].label, "caller changed")
            graph = load_example_graph(name)
            card = build_lesson(graph, node)
            card.exercise.explanation = "caller changed"
            self.assertNotEqual(build_lesson(graph, node).exercise.explanation, "caller changed")

    def test_rank_nullity_primary_matrix_kernel_and_extension_by_exact_arithmetic(self):
        matrix = [[1, 0, 1], [0, 1, 1]]
        kernel = (-1, -1, 1)
        self.assertEqual(product(matrix, kernel), (0, 0))
        self.assertEqual(exact_rank(matrix), 2)
        self.assertEqual(exact_rank([kernel]), 1)
        extension = [[-1, 1, 0], [-1, 0, 1], [1, 0, 0]]
        self.assertEqual(exact_rank(extension), 3)
        for x in range(-3, 4):
            for y in range(-3, 4):
                for z in range(-3, 4):
                    coefficients = (z, x + z, y + z)
                    self.assertEqual(product(extension, coefficients), (x, y, z))
                    self.assertEqual(product(matrix, (x, y, z)), (x + z, y + z))
                    if x + z == 0 and y + z == 0:
                        self.assertEqual((x, y, z), tuple(z * entry for entry in kernel))

    def test_rank_nullity_transfer_and_all_worked_numeric_examples(self):
        matrix = [[1, 0, 1], [0, 1, 1]]
        for vector, answer in (((2,-1,3),(5,2)), ((-2,4,1),(-1,5)), ((3,3,-3),(0,0)), ((4,-2,0),(4,-2))):
            self.assertEqual(product(matrix, vector), answer)
        variant = [[1,0,1,0],[0,1,0,1]]
        basis = [(-1,0,1,0),(0,-1,0,1)]
        self.assertTrue(all(product(variant, vector) == (0,0) for vector in basis))
        self.assertEqual(exact_rank(variant), 2)
        self.assertEqual(exact_rank(basis), 2)
        self.assertEqual(len(variant[0]), exact_rank(variant)+exact_rank(basis))
        self.assertEqual(exact_rank([[1,1,0],[2,2,0]]), 1)
        self.assertEqual(exact_rank([[1,0,0],[0,0,1],[0,0,0]]), 2)
        # The statement itself is also reviewed by the basis-extension proof;
        # these numeric checks validate the finite examples, not a general proof.

    def test_affine_limit_choices_and_invalid_delta_counterexample_exactly(self):
        for numerator in range(1, 20):
            epsilon = Fraction(numerator, 13)
            for scale in (2, 4):
                delta = epsilon / scale
                self.assertGreater(delta, 0)
                for sign in (-1, 1):
                    for fraction in (Fraction(1, 4), Fraction(1, 2), Fraction(3, 4)):
                        x = 3 + sign * fraction * delta
                        self.assertLess(abs(2*x+1-7), epsilon)
            bad_x = 3 + 3*epsilon/4
            self.assertTrue(0 < abs(bad_x-3) < epsilon)
            self.assertGreater(abs(2*bad_x+1-7), epsilon)
            transfer_delta = epsilon/3
            x = 2-transfer_delta/2
            self.assertLess(abs(-3*x+2-(-4)), epsilon)

    def test_limit_domain_points_and_quadratic_transfer(self):
        for delta in (Fraction(1,100),Fraction(1,2),Fraction(1),Fraction(8)):
            x = 3 + min(delta/2,Fraction(1,2))
            self.assertTrue(3 < x < 4)
            self.assertTrue(0 < abs(x-3) < delta)
        for epsilon in (Fraction(1,100),Fraction(1,10),Fraction(1),Fraction(10)):
            delta = min(Fraction(1),epsilon/5)
            for sign in (-1,1):
                x = 2 + sign*delta*Fraction(3,4)
                self.assertLess(abs(x*x-4), epsilon)

    def test_source_locator_matches_verified_editions_and_shapes_safe(self):
        rank = load_example_graph("rank_nullity")
        self.assertIn("3.21", rank.study_plan.source_notes[0].locator)
        self.assertIn("62–63", rank.study_plan.source_notes[0].locator)
        limits = load_example_graph("epsilon_delta")
        self.assertIn("Definition 2、4", limits.study_plan.source_notes[0].locator)
        for graph in (rank, limits):
            for node in graph.nodes:
                illustration = build_lesson(graph,node.id).illustration
                self.assertTrue(all(element.type in ("line","circle","polygon","text") for element in illustration.elements))
                payload = illustration.model_dump_json()
                self.assertNotIn("<svg", payload)
                self.assertNotIn("http", payload)
                self.assertNotIn("script", payload)
        kernel_figure = build_lesson(rank, rank.target_id).illustration
        kernel_line = kernel_figure.elements[0]
        origin = kernel_figure.elements[1]
        self.assertEqual((origin.cx-kernel_line.x1)*(kernel_line.y2-kernel_line.y1),
                         (origin.cy-kernel_line.y1)*(kernel_line.x2-kernel_line.x1))
        limit_figure = build_lesson(limits, limits.target_id).illustration
        self.assertIn("不表示 f(3)未定义", limit_figure.caption)


if __name__ == "__main__":
    unittest.main()
