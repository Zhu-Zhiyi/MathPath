"""学习卡缓存离线回归：额度去重、身份边界、过期与并发失败恢复。"""

from concurrent.futures import Future
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import lesson_builder as builder
import llm_client
from graph_builder import KnowledgeGraph
from lesson_builder import LessonError
from llm_client import ModelError


def graph_with_routes():
    return KnowledgeGraph.model_validate({
        "target_id": "goal",
        "nodes": [
            {"id": "a", "label": "基础甲", "prerequisite_sets": []},
            {"id": "b", "label": "基础乙", "prerequisite_sets": []},
            {"id": "c", "label": "替代基础", "prerequisite_sets": []},
            {"id": "goal", "label": "离线测试目标", "prerequisite_sets": [["a", "b"], ["c"]]},
        ],
    })


def generated_card(node_id="goal"):
    return {
        "node_id": node_id, "title": "离线模拟学习卡",
        "definition": "这是测试夹具，不代表真实模型生成。",
        "intuition": "一个简短直觉。", "example": "一个具体例子。", "proof_idea": "一个推理要点。",
        "exercise": {"question": "离线测试题", "options": ["甲", "乙", "丙", "丁"],
                     "correct_index": 1, "explanation": "离线参考答案解释。", "dimension": "intuition"},
        "source": "generated",
    }


def generated_output(prompt, **kwargs):
    return json.dumps(generated_card(json.loads(prompt)["selected_node_id"]), ensure_ascii=False)


class LessonCacheTests(unittest.TestCase):
    def setUp(self):
        builder.clear_lesson_cache()
        self.addCleanup(builder.clear_lesson_cache)
        for name in ("get_usable_session", "OpenAI"):
            guard = patch.object(llm_client, name, side_effect=AssertionError("缓存测试不得读取授权或调用真实模型"))
            guard.start()
            self.addCleanup(guard.stop)

    def tearDown(self):
        builder.clear_lesson_cache()

    def test_repeated_request_uses_one_call_and_returns_independent_nested_objects(self):
        graph = graph_with_routes()
        with patch.object(builder, "generate_text", side_effect=generated_output) as model:
            first = builder.build_lesson(graph, "goal")
            second = builder.build_lesson(graph, "goal")
            self.assertIsNot(first, second)
            self.assertIsNot(first.exercise, second.exercise)
            first.definition = "调用者修改的内容"
            first.exercise.options[0] = "调用者修改的选项"
            third = builder.build_lesson(graph, "goal")
        self.assertEqual(1, model.call_count)
        self.assertEqual(generated_card()["definition"], second.definition)
        self.assertEqual("甲", second.exercise.options[0])
        self.assertEqual(generated_card() | {"followup_exercises": [], "illustration": None,
                                            "math_context": "", "source_notes": [], "learning_tasks": []}, third.model_dump())

    def test_semantic_order_changes_share_cache_but_labels_and_and_or_do_not(self):
        graph = graph_with_routes()
        reordered = graph.model_dump()
        reordered["nodes"].reverse()
        reordered["nodes"][0]["prerequisite_sets"].reverse()
        for group in reordered["nodes"][0]["prerequisite_sets"]:
            group.reverse()
        reordered = KnowledgeGraph.model_validate(reordered)
        relabelled = graph.model_copy(deep=True)
        relabelled.nodes[0].label = "另一项基础数学内容"
        changed_route = graph.model_dump()
        changed_route["nodes"][-1]["prerequisite_sets"] = [["a", "b", "c"]]
        changed_route = KnowledgeGraph.model_validate(changed_route)
        with patch.object(builder, "generate_text", side_effect=generated_output) as model:
            builder.build_lesson(graph, "goal")
            builder.build_lesson(reordered, "goal")
            self.assertEqual(1, model.call_count)
            builder.build_lesson(relabelled, "goal")
            builder.build_lesson(changed_route, "goal")
        self.assertEqual(3, model.call_count)

    def test_selected_node_is_part_of_cache_identity(self):
        graph = graph_with_routes()
        with patch.object(builder, "generate_text", side_effect=generated_output) as model:
            self.assertEqual("goal", builder.build_lesson(graph, "goal").node_id)
            self.assertEqual("a", builder.build_lesson(graph, "a").node_id)
            builder.build_lesson(graph, "a")
        self.assertEqual(2, model.call_count)

    def test_ttl_expiration_is_separate_from_lru_capacity(self):
        graph = graph_with_routes()
        with patch.object(builder, "_CACHE_TTL_SECONDS", 10), \
             patch.object(builder, "_CACHE_MAX_ENTRIES", 64), \
             patch.object(builder, "monotonic", return_value=100) as clock, \
             patch.object(builder, "generate_text", side_effect=generated_output) as model:
            builder.build_lesson(graph, "goal")
            clock.return_value = 109
            builder.build_lesson(graph, "goal")
            self.assertEqual(1, model.call_count)
            clock.return_value = 111
            builder.build_lesson(graph, "goal")
        self.assertEqual(2, model.call_count)

    def test_lru_evicts_least_recently_used_without_expiry(self):
        graphs = []
        for label in ("目标甲", "目标乙", "目标丙"):
            graph = graph_with_routes()
            graph.nodes[-1].label = label
            graphs.append(graph)
        with patch.object(builder, "_CACHE_MAX_ENTRIES", 2), \
             patch.object(builder, "_CACHE_TTL_SECONDS", 1800), \
             patch.object(builder, "monotonic", return_value=100), \
             patch.object(builder, "generate_text", side_effect=generated_output) as model:
            builder.build_lesson(graphs[0], "goal")
            builder.build_lesson(graphs[1], "goal")
            builder.build_lesson(graphs[0], "goal")  # 甲成为最近使用，乙应被淘汰。
            builder.build_lesson(graphs[2], "goal")
            self.assertEqual(3, model.call_count)
            builder.build_lesson(graphs[0], "goal")
            self.assertEqual(3, model.call_count)
            builder.build_lesson(graphs[1], "goal")
        self.assertEqual(4, model.call_count)

    def test_model_and_instructions_invalidate_cache_and_match_actual_request(self):
        graph = graph_with_routes()
        original_instructions = builder.LESSON_INSTRUCTIONS
        with patch.object(builder, "generate_text", side_effect=generated_output) as model:
            builder.build_lesson(graph, "goal")
            with patch.object(builder, "MODEL", "offline-alternate-model"):
                builder.build_lesson(graph, "goal")
                self.assertEqual("offline-alternate-model", model.call_args.kwargs["model"])
            with patch.object(builder, "LESSON_INSTRUCTIONS", original_instructions + "\n离线版本变更。"):
                builder.build_lesson(graph, "goal")
                self.assertEqual(builder.LESSON_INSTRUCTIONS, model.call_args.kwargs["instructions"])
        self.assertEqual(3, model.call_count)

    def test_schema_change_invalidates_cache(self):
        graph = graph_with_routes()
        schema = copy.deepcopy(builder.Lesson.model_json_schema())
        schema["description"] = "离线模拟 schema 版本变更"
        with patch.object(builder, "generate_text", side_effect=generated_output) as model:
            builder.build_lesson(graph, "goal")
            with patch.object(builder.Lesson, "model_json_schema", return_value=schema):
                builder.build_lesson(graph, "goal")
                self.assertEqual(schema, model.call_args.kwargs["json_schema"])
        self.assertEqual(2, model.call_count)

    def test_model_failure_is_not_cached_and_next_request_can_recover(self):
        graph = graph_with_routes()
        failure = ModelError("离线模拟暂时失败")
        with patch.object(builder, "generate_text", side_effect=[failure, json.dumps(generated_card())]) as model:
            with self.assertRaises(ModelError):
                builder.build_lesson(graph, "goal")
            builder.build_lesson(graph, "goal")
            builder.build_lesson(graph, "goal")
        self.assertEqual(2, model.call_count)

    def test_invalid_model_results_are_not_cached(self):
        invalid_results = [
            "synthetic-private-marker is not JSON",
            json.dumps({**generated_card(), "definition": " "}),
            json.dumps({**generated_card(), "node_id": "a"}),
            json.dumps({**generated_card(), "source": "curated_example"}),
        ]
        for invalid in invalid_results:
            with self.subTest(output=invalid[:30]):
                builder.clear_lesson_cache()
                with patch.object(builder, "generate_text", side_effect=[invalid, json.dumps(generated_card())]) as model:
                    with self.assertRaises(LessonError) as error:
                        builder.build_lesson(graph_with_routes(), "goal")
                    self.assertNotIn("synthetic-private-marker", str(error.exception))
                    builder.build_lesson(graph_with_routes(), "goal")
                    builder.build_lesson(graph_with_routes(), "goal")
                self.assertEqual(2, model.call_count)

    def concurrent_requests(self, *, failure=None, clear_while_pending=False):
        """在 leader 阻塞且两个 waiter 已登记后释放；不用 sleep 猜时序。"""
        graph = graph_with_routes()
        leader_entered = threading.Event()
        release_leader = threading.Event()
        waiters_entered = threading.Event()
        observed_waiters = set()
        observation_lock = threading.Lock()
        outcomes = {}
        outcome_lock = threading.Lock()
        original_result = Future.result
        threads = []

        def model_output(prompt, **kwargs):
            leader_entered.set()
            if not release_leader.wait(10):
                raise AssertionError("离线测试未释放 leader")
            if failure is not None:
                raise failure
            return generated_output(prompt, **kwargs)

        def observe_waiter(future, *args, **kwargs):
            name = threading.current_thread().name
            if name.startswith("cache-waiter-"):
                with observation_lock:
                    observed_waiters.add(name)
                    if len(observed_waiters) == 2:
                        waiters_entered.set()
            return original_result(future, *args, **kwargs)

        def worker(name):
            try:
                outcome = builder.build_lesson(graph, "goal")
            except BaseException as exc:
                outcome = exc
            with outcome_lock:
                outcomes[name] = outcome

        def start_thread(name):
            thread = threading.Thread(target=worker, args=(name,), name=name, daemon=True)
            threads.append(thread)
            thread.start()

        with patch.object(builder, "generate_text", side_effect=model_output) as model, \
             patch.object(Future, "result", new=observe_waiter):
            try:
                start_thread("cache-leader")
                self.assertTrue(leader_entered.wait(5), "leader 没有进入模拟生成")
                if clear_while_pending:
                    builder.clear_lesson_cache()
                start_thread("cache-waiter-1")
                start_thread("cache-waiter-2")
                self.assertTrue(waiters_entered.wait(5), "两个请求没有等待同一 pending")
            finally:
                release_leader.set()
                for thread in threads:
                    thread.join(5)
            self.assertTrue(all(not thread.is_alive() for thread in threads), "并发请求没有结束")
            self.assertEqual(1, model.call_count, "同一 pending 不应产生多个模型请求")
        self.assertEqual(3, len(outcomes))
        return outcomes

    def test_concurrent_success_has_one_model_call_and_independent_results(self):
        outcomes = self.concurrent_requests()
        for outcome in outcomes.values():
            self.assertIsInstance(outcome, builder.Lesson)
        values = list(outcomes.values())
        self.assertEqual(3, len({id(value) for value in values}))
        self.assertEqual(3, len({id(value.exercise) for value in values}))
        values[0].exercise.options[0] = "并发调用者修改"
        for value in values[1:]:
            self.assertEqual("甲", value.exercise.options[0])

    def test_clear_success_cache_does_not_destroy_pending_deduplication(self):
        outcomes = self.concurrent_requests(clear_while_pending=True)
        self.assertTrue(all(isinstance(outcome, builder.Lesson) for outcome in outcomes.values()))

    def test_concurrent_failure_is_broadcast_without_waiter_retries_and_later_recovers(self):
        failure = ModelError("离线模拟并发暂时失败")
        outcomes = self.concurrent_requests(failure=failure)
        for outcome in outcomes.values():
            self.assertIsInstance(outcome, ModelError)
            self.assertEqual(str(failure), str(outcome))
        with patch.object(builder, "generate_text", side_effect=generated_output) as model:
            builder.build_lesson(graph_with_routes(), "goal")
            builder.build_lesson(graph_with_routes(), "goal")
        self.assertEqual(1, model.call_count)

    def test_missing_or_invalid_local_resources_produce_safe_error_without_model_fallback(self):
        example_data = json.loads((PROJECT / "examples" / "homology_graph.json").read_text(encoding="utf-8"))
        graph = KnowledgeGraph.model_validate(example_data)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(builder, "_EXAMPLE_DIR", Path(folder)), \
             patch.object(builder, "generate_text", side_effect=AssertionError("本地资源坏了不能自动联网")) as model:
            with self.assertRaises(LessonError) as error:
                builder.load_example_graph()
            self.assertNotIn(folder, str(error.exception))
            with self.assertRaises(LessonError):
                builder.build_lesson(graph_with_routes(), "goal")
            Path(folder, "homology_graph.json").write_text("synthetic-private-bad-json", encoding="utf-8")
            with self.assertRaises(LessonError) as error:
                builder.load_example_graph()
            self.assertNotIn("synthetic-private", str(error.exception))
            Path(folder, "homology_graph.json").write_text(json.dumps(example_data), encoding="utf-8")
            with self.assertRaises(LessonError):
                builder.build_lesson(graph, graph.target_id)
            Path(folder, "homology_lessons.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(LessonError):
                builder.build_lesson(graph, graph.target_id)
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
