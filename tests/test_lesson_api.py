"""学习卡 HTTP 边界的离线检查；所有潜在模型/凭证入口都被阻断。"""

import copy
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from chatgpt_login import LoginError
from lesson_builder import LessonError


class LessonAPITests(TestCase):
    def setUp(self):
        guard = patch("lesson_builder.generate_text", side_effect=AssertionError("离线测试不可调用模型"))
        guard.start()
        self.addCleanup(guard.stop)
        self.client = TestClient(main.app)
        self.graph = self.client.get("/example").json()

    def test_sample_lessons_and_plan_work_through_http(self):
        for node in self.graph["nodes"]:
            response = self.client.post("/lesson", json={"graph": self.graph, "node_id": node["id"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["source"], "curated_example")
            self.assertEqual(response.json()["node_id"], node["id"])
        result = self.client.post("/plan", json={"graph": self.graph, "known_ids": ["chains_as_formal_sums"]})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["focus_id"], "boundary_operator")

    def test_unknown_node_and_invalid_graph_are_rejected_before_builder(self):
        with patch.object(main, "build_lesson", side_effect=AssertionError("非法请求不可调用构建器")):
            response = self.client.post("/lesson", json={"graph": self.graph, "node_id": "unknown"})
            self.assertEqual(response.status_code, 422)
            invalid = copy.deepcopy(self.graph)
            invalid["nodes"][1]["prerequisite_sets"] = [["unknown"]]
            response = self.client.post("/lesson", json={"graph": invalid, "node_id": "boundary_operator"})
            self.assertEqual(response.status_code, 422)

    def test_network_and_model_format_failures_have_safe_http_errors(self):
        body = {"graph": self.graph, "node_id": self.graph["target_id"]}
        for failure, status in [(LoginError("与 OpenAI 的 TLS 连接失败。"), 503),
                                (LessonError("学习卡未通过格式校验。"), 502)]:
            with patch.object(main, "build_lesson", side_effect=failure):
                response = self.client.post("/lesson", json=body)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), {"detail": str(failure)})

    def test_lesson_input_does_not_accept_extra_fields(self):
        response = self.client.post("/lesson", json={"graph": self.graph, "node_id": self.graph["target_id"],
                                                    "api_key": "synthetic-secret-not-used"})
        self.assertEqual(response.status_code, 422)
