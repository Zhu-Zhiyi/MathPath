"""MathPath 的离线回归检查：不读取登录记录，不访问模型或网络。

在项目目录运行：python -B -m unittest discover -s tests -v
"""

from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import graph_builder
import llm_client
from graph_builder import GraphError, KnowledgeGraph
from planner import PlanError, current_learning_status
from pydantic import ValidationError


def graph_of(nodes, target="goal"):
    return KnowledgeGraph.model_validate({
        "target_id": target,
        "nodes": [{"id": node_id, "label": node_id, "prerequisite_sets": groups}
                  for node_id, groups in nodes],
    })


def event(kind, **values):
    return SimpleNamespace(type=kind, **values)


def completed(output=None):
    return event("response.completed", response=SimpleNamespace(status="completed", output=output, output_text=""))


@contextmanager
def fake_model(events):
    """Replace both credential access and the SDK before calling real generate_text."""
    session = {
        "access_token": "synthetic-test-token",
        "scopes": ["resource.invoke", "chatgpt.tokens.use.direct"],
        "expires_at": 9_999_999_999,
    }
    client = MagicMock()
    client.__enter__.return_value = client
    stream = MagicMock()
    stream.__enter__.return_value = iter(events)
    client.responses.create.return_value = stream
    with patch.object(llm_client, "get_usable_session", return_value=session), \
            patch.object(llm_client, "OpenAI", return_value=client):
        yield client


class MathPathTests(unittest.TestCase):
    def setUp(self):
        # Fail immediately if a later test accidentally omits its offline mock.
        for name in ("get_usable_session", "OpenAI"):
            guard = patch.object(llm_client, name, side_effect=AssertionError("必须使用离线模型模拟"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_and_requires_every_member_and_ready_is_not_known(self):
        graph = graph_of([("a", []), ("b", [["a"]]), ("goal", [["a", "b"]])])
        initial = current_learning_status(graph, [])
        self.assertEqual(initial.ready_ids, ["a"])
        self.assertEqual(initial.known_ids, [])
        partial = current_learning_status(graph, ["a"])
        self.assertEqual(partial.recommended_ids, ["b"])
        self.assertIn("goal", partial.blocked_ids)
        complete_group = current_learning_status(graph, ["a", "b"])
        self.assertEqual(complete_group.recommended_ids, ["goal"])

    def test_or_alternative_suffices_but_other_candidates_are_preserved(self):
        graph = graph_of([("a", []), ("b", []), ("c", []), ("goal", [["a", "b"], ["c"]])])
        initial = current_learning_status(graph, [])
        self.assertEqual(initial.required_ids, ["c", "goal"])
        self.assertEqual(initial.recommended_ids, ["c"])
        result = current_learning_status(graph, ["c"])
        self.assertEqual(set(result.ready_ids), {"a", "b", "goal"})
        self.assertEqual(result.required_ids, ["goal"])
        self.assertEqual(result.selected_ids, ["c", "goal"])
        self.assertEqual(result.selected_groups[0].group_index, 1)
        self.assertEqual(result.focus_id, "goal")

    def test_shared_prerequisites_make_global_route_cheaper_than_local_greedy(self):
        graph = graph_of([
            ("s", []), ("p", [["s"]]), ("a", []), ("b", []), ("c", []),
            ("x", [["a"], ["p"]]), ("y", [["b"], ["p"]]), ("z", [["c"], ["p"]]),
            ("goal", [["x", "y", "z"]]),
        ])
        result = current_learning_status(graph, [])
        # Two shared prerequisites cost less than three separate ones, even though
        # each child individually has a cheaper separate branch.
        self.assertEqual(result.required_ids, ["s", "p", "x", "y", "z", "goal"])
        self.assertEqual(result.recommended_ids, ["s"])
        self.assertEqual({g.node_id: g.group_index for g in result.selected_groups},
                         {"p": 0, "x": 1, "y": 1, "z": 1, "goal": 0})

    def test_known_advanced_node_stops_expansion_without_inferring_ancestors(self):
        graph = graph_of([("a", []), ("b", [["a"]]), ("goal", [["b"]])])
        result = current_learning_status(graph, ["b"])
        self.assertEqual(result.known_ids, ["b"])
        self.assertEqual(result.selected_ids, ["b", "goal"])
        self.assertEqual(result.required_ids, ["goal"])
        self.assertEqual(result.recommended_ids, ["goal"])
        self.assertIn("a", result.ready_ids)

    def test_known_target_is_completed(self):
        graph = graph_of([("a", []), ("goal", [["a"]])])
        result = current_learning_status(graph, ["goal"])
        self.assertTrue(result.completed)
        self.assertEqual(result.selected_ids, ["goal"])
        for name in ("ready_ids", "blocked_ids", "required_ids", "recommended_ids", "selected_groups"):
            self.assertEqual(getattr(result, name), [])
        self.assertIsNone(result.focus_id)

    def test_duplicate_and_unknown_known_ids_are_rejected(self):
        graph = graph_of([("a", []), ("goal", [["a"]])])
        for known in (["a", "a"], ["unknown"]):
            with self.subTest(known=known), self.assertRaises(PlanError):
                current_learning_status(graph, known)

    def test_invalid_references_cycles_and_unrelated_nodes_are_rejected(self):
        valid = graph_of([("a", []), ("goal", [["a"]])]).model_dump()
        bad = []
        missing = copy.deepcopy(valid)
        missing["nodes"][-1]["prerequisite_sets"] = [["missing"]]
        bad.append(missing)
        cyclic = copy.deepcopy(valid)
        cyclic["nodes"][0]["prerequisite_sets"] = [["goal"]]
        bad.append(cyclic)
        unrelated = copy.deepcopy(valid)
        unrelated["nodes"].append({"id": "other", "label": "other", "prerequisite_sets": []})
        bad.append(unrelated)
        duplicate = copy.deepcopy(valid)
        duplicate["nodes"].append(copy.deepcopy(duplicate["nodes"][0]))
        bad.append(duplicate)
        empty_group = copy.deepcopy(valid)
        empty_group["nodes"][-1]["prerequisite_sets"] = [[]]
        bad.append(empty_group)
        for index, payload in enumerate(bad):
            with self.subTest(case=index), self.assertRaises(ValidationError):
                KnowledgeGraph.model_validate(payload)

    def test_equal_cost_route_is_stable_and_does_not_mutate_inputs(self):
        graph = graph_of([("b", []), ("a", []), ("goal", [["a"], ["b"]])])
        original = copy.deepcopy(graph.model_dump())
        known = []
        first = current_learning_status(graph, known)
        second = current_learning_status(graph, known)
        self.assertEqual(first.required_ids, ["b", "goal"])
        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(graph.model_dump(), original)
        self.assertEqual(known, [])

    def test_delta_done_and_thin_completed_do_not_duplicate_text(self):
        for thin_output in (None, []):
            events = [
                event("response.output_text.delta", output_index=1, content_index=0, delta="乙"),
                event("response.output_text.delta", output_index=0, content_index=0, delta="甲"),
                event("response.output_text.done", output_index=0, content_index=0, text="甲"),
                event("response.output_text.done", output_index=1, content_index=0, text="乙"),
                completed(thin_output),
            ]
            with self.subTest(output=thin_output), fake_model(events):
                self.assertEqual(llm_client.generate_text("目标"), "甲乙")

    def test_build_graph_uses_real_offline_model_parser_and_json_schema(self):
        payload = graph_of([("a", []), ("goal", [["a"]])]).model_dump()
        text = json.dumps(payload, ensure_ascii=False)
        events = [event("response.output_text.done", output_index=0, content_index=0, text=text), completed()]
        with fake_model(events) as client:
            result = graph_builder.build_graph("数学目标")
        self.assertEqual(result.model_dump(), payload)
        options = client.responses.create.call_args.kwargs
        self.assertEqual(options["input"], [{"role": "user", "content": "数学目标"}])
        self.assertEqual(options["instructions"], graph_builder.GRAPH_INSTRUCTIONS)
        self.assertEqual(options["text"]["format"]["schema"], KnowledgeGraph.model_json_schema())
        self.assertTrue(options["text"]["format"]["strict"])
        self.assertFalse(options["store"])

    def test_missing_or_unsuccessful_completion_is_rejected_without_leaking(self):
        secret = "synthetic-secret: must-not-appear"
        cases = [
            [event("response.output_text.delta", output_index=0, content_index=0, delta=secret)],
            [event("response.incomplete", response=SimpleNamespace(message=secret))],
            [event("response.failed", response=SimpleNamespace(error=SimpleNamespace(code=secret, message=secret)))],
            [event("error", code=secret, message=secret)],
            [completed()],
        ]
        for index, events in enumerate(cases):
            with self.subTest(case=index), fake_model(events), self.assertRaises(llm_client.ModelError) as caught:
                llm_client.generate_text("目标")
            self.assertNotIn(secret, str(caught.exception))

    def test_invalid_model_json_is_rejected_without_echoing_raw_output(self):
        secret = "synthetic-secret: must-not-appear"
        events = [event("response.output_text.done", output_index=0, content_index=0, text=secret), completed()]
        with fake_model(events), self.assertRaises(GraphError) as caught:
            graph_builder.build_graph("数学目标")
        self.assertNotIn(secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
