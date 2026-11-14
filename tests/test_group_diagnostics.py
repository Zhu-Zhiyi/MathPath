"""AND/OR 组解释及单步假设预览；只计算合成图，不访问学习库或模型。"""

import copy
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from graph_builder import KnowledgeGraph
from planner import current_learning_status


def graph_of(nodes, target="goal"):
    return KnowledgeGraph.model_validate({
        "target_id": target,
        "nodes": [{"id": node_id, "label": node_id, "prerequisite_sets": groups}
                  for node_id, groups in nodes],
    })


def group_map(status):
    return {(group.node_id, group.group_index): group for group in status.prerequisite_groups}


def preview_map(status):
    return {preview.node_id: preview.newly_ready_ids for preview in status.unlock_previews}


class GroupDiagnosticsTests(unittest.TestCase):
    def test_partial_and_group_does_not_unlock_until_last_missing_member(self):
        graph = graph_of([("a", []), ("b", []), ("goal", [["b", "a"]])])
        initial = current_learning_status(graph, [])
        group = group_map(initial)[("goal", 0)]
        self.assertEqual(group.prerequisite_ids, ["b", "a"])
        self.assertEqual(group.satisfied_ids, [])
        self.assertEqual(group.missing_ids, ["b", "a"])
        self.assertFalse(group.satisfied)
        self.assertTrue(group.selected)
        self.assertEqual(preview_map(initial), {"a": [], "b": []})

        partial = current_learning_status(graph, ["a"])
        group = group_map(partial)[("goal", 0)]
        self.assertEqual(group.satisfied_ids, ["a"])
        self.assertEqual(group.missing_ids, ["b"])
        self.assertFalse(group.satisfied)
        self.assertEqual(preview_map(partial), {"b": ["goal"]})

        ready = current_learning_status(graph, ["a", "b"])
        self.assertTrue(group_map(ready)[("goal", 0)].satisfied)
        self.assertEqual(preview_map(ready), {"goal": []})

    def test_or_routes_remain_separate_and_preview_deduplicates_target(self):
        graph = graph_of([("a", []), ("b", []), ("c", []),
                          ("goal", [["a", "b"], ["c"], ["b", "c"]])])
        initial = current_learning_status(graph, [])
        self.assertEqual(preview_map(initial), {"a": [], "b": [], "c": ["goal"]})
        groups = group_map(initial)
        self.assertFalse(groups[("goal", 0)].selected)
        self.assertTrue(groups[("goal", 1)].selected)
        self.assertFalse(groups[("goal", 2)].selected)
        partial = current_learning_status(graph, ["b"])
        self.assertEqual(preview_map(partial), {"a": ["goal"], "c": ["goal"]})
        self.assertEqual(group_map(partial)[("goal", 2)].missing_ids, ["c"])

        already_ready = current_learning_status(graph, ["c"])
        self.assertTrue(group_map(already_ready)[("goal", 1)].satisfied)
        self.assertFalse(group_map(already_ready)[("goal", 0)].satisfied)
        self.assertEqual(preview_map(already_ready), {"a": [], "b": [], "goal": []})

    def test_shared_prerequisite_unlocks_two_children_without_transitive_target(self):
        graph = graph_of([("a", []), ("x", [["a"]]), ("y", [["a"]]),
                          ("goal", [["x", "y"]])])
        status = current_learning_status(graph, [])
        self.assertEqual(preview_map(status), {"a": ["x", "y"]})
        self.assertNotIn("goal", preview_map(status)["a"])

    def test_known_advanced_node_does_not_imply_its_prerequisites(self):
        graph = graph_of([("a", []), ("x", [["a"]]), ("goal", [["x"]])])
        status = current_learning_status(graph, ["x"])
        groups = group_map(status)
        self.assertEqual(groups[("x", 0)].missing_ids, ["a"])
        self.assertFalse(groups[("x", 0)].selected)
        self.assertTrue(groups[("goal", 0)].satisfied)
        self.assertEqual(preview_map(status), {"a": [], "goal": []})
        self.assertEqual(status.known_ids, ["x"])

    def test_modes_use_planning_dimensions_without_granting_full_mastery(self):
        graph = graph_of([("a", []), ("b", []), ("goal", [["a", "b"]])])
        mastery = {"a": {"definition": True, "intuition": True, "application": False}}
        intuition = current_learning_status(graph, [], mode="intuition", mastery=mastery)
        self.assertEqual(intuition.known_ids, [])
        self.assertEqual(intuition.planning_known_ids, ["a"])
        self.assertEqual(group_map(intuition)[("goal", 0)].satisfied_ids, ["a"])
        self.assertEqual(preview_map(intuition), {"b": ["goal"]})

        proof = current_learning_status(graph, [], mode="proof", mastery=mastery)
        self.assertEqual(proof.planning_known_ids, [])
        self.assertEqual(group_map(proof)[("goal", 0)].satisfied_ids, [])
        self.assertEqual(preview_map(proof), {"a": [], "b": []})

    def test_node_specific_dimension_requirement_drives_group_explanation(self):
        graph = graph_of([("a", []), ("b", []), ("goal", [["a", "b"]])])
        graph.nodes[0].required_dimensions = ["definition"]
        status = current_learning_status(graph, [], mode="proof", mastery={"a": {"definition": True}})
        self.assertEqual(status.known_ids, [])
        self.assertEqual(status.planning_known_ids, ["a"])
        self.assertEqual(group_map(status)[("goal", 0)].missing_ids, ["b"])
        self.assertEqual(preview_map(status), {"b": ["goal"]})

    def test_completed_target_has_no_unlock_preview_or_selected_group(self):
        graph = graph_of([("a", []), ("goal", [["a"]])])
        status = current_learning_status(graph, ["goal"])
        self.assertTrue(status.completed)
        self.assertEqual(status.unlock_previews, [])
        self.assertEqual(status.planning_known_ids, ["goal"])
        self.assertFalse(group_map(status)[("goal", 0)].selected)
        self.assertEqual(group_map(status)[("goal", 0)].missing_ids, ["a"])

    def test_inputs_and_prior_results_are_not_mutated_by_previews(self):
        graph = graph_of([("a", []), ("b", []), ("goal", [["a", "b"]])])
        known = []
        mastery = {"a": {"definition": True, "intuition": True, "application": False}}
        original = (copy.deepcopy(graph.model_dump()), copy.deepcopy(known), copy.deepcopy(mastery))
        first = current_learning_status(graph, known, mode="intuition", mastery=mastery)
        snapshot = first.model_dump()
        later = current_learning_status(graph, ["a", "b"])
        later.prerequisite_groups[0].prerequisite_ids.append("unrelated")
        self.assertEqual(first.model_dump(), snapshot)
        self.assertEqual((graph.model_dump(), known, mastery), original)

    def test_all_known_subsets_match_independent_direct_permission_truth_tables(self):
        # Permission masks encode each complete AND group; OR alternatives remain
        # distinct rows. Compare all states, including unusual self-reported advanced
        # nodes, with the set difference after one hypothetical completion.
        examples = [
            [("a", []), ("goal", [["a"]])],
            [("a", []), ("b", []), ("goal", [["a", "b"]])],
            [("a", []), ("b", []), ("c", []), ("goal", [["a", "b"], ["c"]])],
            [("a", []), ("x", [["a"]]), ("y", [["a"]]), ("goal", [["x", "y"]])],
            [("a", []), ("b", [["a"]]), ("c", [["b"], ["a"]]), ("goal", [["b", "c"]])],
        ]
        for example in examples:
            graph = graph_of(example)
            ids = [node.id for node in graph.nodes]
            bits = {node_id: 1 << index for index, node_id in enumerate(ids)}
            permissions = {node.id: [sum(bits[member] for member in group)
                                    for group in node.prerequisite_sets] or [0]
                           for node in graph.nodes}

            def available(state):
                return {node_id for node_id in ids if not state & bits[node_id]
                        and any(state & mask == mask for mask in permissions[node_id])}

            for state in range(1 << len(ids)):
                known = [node_id for node_id in ids if state & bits[node_id]]
                with self.subTest(example=example, known=known):
                    result = current_learning_status(graph, known)
                    expected_ready = set() if graph.target_id in known else available(state)
                    self.assertEqual(set(result.ready_ids), expected_ready)
                    self.assertEqual(set(preview_map(result)), expected_ready)
                    for node_id, newly in preview_map(result).items():
                        expected = available(state | bits[node_id]) - available(state)
                        self.assertEqual(set(newly), expected)
                        self.assertEqual(len(newly), len(set(newly)))
                    groups = group_map(result)
                    self.assertEqual(len(groups), sum(len(node.prerequisite_sets) for node in graph.nodes))
                    chosen = {(item.node_id, item.group_index) for item in result.selected_groups}
                    for node in graph.nodes:
                        for index, members in enumerate(node.prerequisite_sets):
                            group = groups[(node.id, index)]
                            self.assertEqual(group.prerequisite_ids, members)
                            self.assertEqual(group.satisfied_ids, [item for item in members if item in known])
                            self.assertEqual(group.missing_ids, [item for item in members if item not in known])
                            self.assertEqual(group.satisfied, all(item in known for item in members))
                            self.assertEqual(group.selected, (node.id, index) in chosen)


if __name__ == "__main__":
    unittest.main()
