"""Validate new lesson content and vector-data boundaries without model/auth access."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

import lesson_builder as builder
import main
from graph_builder import KnowledgeGraph

PROJECT = Path(__file__).resolve().parents[1]


class LessonEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.records = json.loads((PROJECT / "examples" / "homology_lessons.json").read_text(encoding="utf-8"))
        self.graph = builder.load_example_graph()
        self.sample = copy.deepcopy(self.records["boundary_operator"])
        builder.clear_lesson_cache()
        self.addCleanup(builder.clear_lesson_cache)

    def test_every_curated_lesson_has_followup_questions_and_a_valid_vector_illustration_offline(self):
        with patch.object(builder, "generate_text", side_effect=AssertionError("Curated lessons must remain offline")):
            for node in self.graph.nodes:
                with self.subTest(node=node.id):
                    card = builder.build_lesson(self.graph, node.id)
                    self.assertEqual(["basic", "challenge"], [item.level for item in card.followup_exercises])
                    self.assertNotEqual(card.followup_exercises[0].question, card.exercise.question)
                    self.assertIsNotNone(card.illustration)
                    self.assertTrue(card.illustration.alt.strip())
                    self.assertEqual(card.model_dump(), builder.Lesson.model_validate_json(card.model_dump_json()).model_dump())

    def test_legacy_cards_remain_readable_with_no_new_sections(self):
        self.sample.pop("followup_exercises")
        self.sample.pop("illustration")
        card = builder.Lesson.model_validate(self.sample)
        self.assertEqual([], card.followup_exercises)
        self.assertIsNone(card.illustration)

    def test_followup_questions_reject_missing_answers_invalid_levels_and_excess(self):
        for change in [{"answer": "   "}, {"hint": ""}, {"question": ""}, {"level": "ungraded"}, {"answer": "x" * 1401}]:
            with self.subTest(change=change):
                value = copy.deepcopy(self.sample)
                value["followup_exercises"][0].update(change)
                with self.assertRaises(ValidationError):
                    builder.Lesson.model_validate(value)
        value = copy.deepcopy(self.sample)
        value["followup_exercises"] *= 2
        with self.assertRaises(ValidationError):
            builder.Lesson.model_validate(value)

    def test_svg_scripts_external_resources_and_event_fields_are_not_supported(self):
        attacks = [
            {"type": "svg", "markup": "<svg onload='alert(1)'/>"},
            {"type": "image", "href": "https://untrusted.example/track"},
            {"type": "text", "x": 1, "y": 1, "text": "label", "tone": "ink", "anchor": "start", "onclick": "run()"},
            {"type": "line", "x1": 1, "y1": 1, "x2": 2, "y2": 2, "tone": "url(#external)", "arrow": False, "dashed": False},
        ]
        for element in attacks:
            with self.subTest(element=element):
                value = copy.deepcopy(self.sample)
                value["illustration"]["elements"] = [element]
                with self.assertRaises(ValidationError):
                    builder.Lesson.model_validate(value)
        value = copy.deepcopy(self.sample)
        value["illustration"]["url"] = "file:///private"
        with self.assertRaises(ValidationError):
            builder.Lesson.model_validate(value)

    def test_coordinates_reject_coercion_nonfinite_and_outside_canvas(self):
        circle = {"type": "circle", "cx": 100, "cy": 100, "r": 20, "tone": "green", "fill": False}
        for field, bad in [("cx", True), ("cx", "100"), ("cx", float("nan")), ("cy", float("inf")),
                           ("cx", -1), ("cx", 641), ("cy", 361), ("r", 0), ("r", 151)]:
            with self.subTest(field=field, bad=bad):
                value = copy.deepcopy(self.sample)
                value["illustration"]["elements"] = [circle | {field: bad}]
                with self.assertRaises(ValidationError):
                    builder.Lesson.model_validate(value)
        polygon = {"type": "polygon", "points": [[0, 0], [50, 361], [100, 0]], "tone": "blue", "fill": True}
        with self.assertRaises(ValidationError):
            builder.IllustrationPolygon.model_validate(polygon)

    def test_empty_or_overlong_drawings_and_blank_labels_are_rejected(self):
        element = {"type": "text", "x": 10, "y": 10, "text": "label", "tone": "ink", "anchor": "start"}
        for elements in [[], [element] * 61, [element | {"text": "  "}], [element | {"text": "x" * 51}]]:
            with self.subTest(length=len(elements)):
                value = copy.deepcopy(self.sample)
                value["illustration"]["elements"] = elements
                with self.assertRaises(ValidationError):
                    builder.Lesson.model_validate(value)

    def test_generated_output_schema_has_strict_objects_and_supported_unions(self):
        schema = builder.Lesson.model_json_schema()
        self.assertIn("followup_exercises", schema["required"])
        self.assertIn("illustration", schema["required"])

        def visit(value):
            if isinstance(value, dict):
                for unsupported in ["default", "oneOf", "discriminator"]:
                    self.assertNotIn(unsupported, value)
                if value.get("type") == "object":
                    self.assertIs(value.get("additionalProperties"), False)
                    self.assertEqual(set(value["properties"]), set(value["required"]))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(schema)

    def test_api_serves_enriched_example_without_auth_or_model(self):
        with patch.object(builder, "generate_text", side_effect=AssertionError("No model in fixture endpoint")):
            with TestClient(main.app) as client:
                response = client.post("/lesson", json={"graph": self.graph.model_dump(), "node_id": "boundary_operator"})
        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual(2, len(result["followup_exercises"]))
        self.assertIsInstance(result["illustration"], dict)
        self.assertEqual("curated_example", result["source"])

    def test_cached_new_content_is_not_shared_between_callers(self):
        graph = KnowledgeGraph.model_validate({"target_id": "goal", "nodes": [
            {"id": "goal", "label": "an isolated test", "prerequisite_sets": []}]})
        value = copy.deepcopy(self.sample) | {"node_id": "goal", "source": "generated"}
        # This is a generated fixture for a different graph, so its new tasks
        # must refer to the same selected node as the rest of the lesson.
        for task in value.get("learning_tasks", []):
            task["node_id"] = "goal"
            task["source"] = "generated"
        with patch.object(builder, "generate_text", return_value=json.dumps(value, ensure_ascii=False)) as model:
            first = builder.build_lesson(graph, "goal")
            first.followup_exercises[0].answer = "caller edit"
            first.illustration.caption = "caller edit"
            second = builder.build_lesson(graph, "goal")
        self.assertEqual(1, model.call_count)
        self.assertEqual(value["followup_exercises"][0]["answer"], second.followup_exercises[0].answer)
        self.assertEqual(value["illustration"]["caption"], second.illustration.caption)


if __name__ == "__main__":
    unittest.main()
