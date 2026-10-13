"""Floating conversation API checks using a temporary learning library only."""
from datetime import datetime, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import main


class ChatAPITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mathpath-chat-api-")
        self.environment = patch.dict(os.environ, {"MATHPATH_DATA_DIR": self.temporary.name})
        self.environment.start()
        self.old_desktop = main.app.state.desktop_local_only
        main.app.state.desktop_local_only = False
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8427")
        self.graph = self.client.get("/example").json()

    def tearDown(self):
        self.client.close()
        main.app.state.desktop_local_only = self.old_desktop
        self.environment.stop()
        self.temporary.cleanup()

    def turn(self, node=None):
        return {"id": str(uuid4()), "node_id": node, "question": "为什么取商？",
                "response": "先比较两个循环的差。", "source": "model_candidate",
                "review_required": True, "answer_status": "answered",
                "created_at": datetime.now(timezone.utc).isoformat()}

    def test_local_question_without_graph_is_queued_without_model_or_login(self):
        with patch("teaching_help.generate_text") as model, patch.object(main, "start_connection") as login:
            response = self.client.post("/study/chat", json={"question": "数学目标从哪里开始？"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["source"], "local_reference")
            self.assertTrue(response.json()["review_required"])
            self.assertEqual(response.json()["answer_status"], "unanswered")
            self.assertIsNotNone(response.json()["problem_id"])
            self.assertFalse(response.json()["problem_save_failed"])
            problems = self.client.get("/library/problems").json()
            self.assertEqual(problems[0]["id"], response.json()["problem_id"])
            self.assertIsNone(problems[0]["history_id"])
            self.assertEqual(response.headers["cache-control"], "no-store")
            model.assert_not_called()
            login.assert_not_called()

    def test_foreign_origin_and_wrong_host_cannot_trigger_chat(self):
        with patch.object(main, "build_learning_chat") as chat:
            for headers in ({"Origin": "https://foreign.invalid"}, {"Origin": "null"},
                            {"Host": "127.0.0.1:8000"}, {"Host": "foreign.invalid:8427"}):
                self.assertEqual(self.client.post("/study/chat", json={"question": "test", "use_model": True},
                                                 headers=headers).status_code, 403)
            chat.assert_not_called()

    def test_invalid_payload_does_not_echo_user_question(self):
        canary = "synthetic-user-question-not-echo-941"
        for body in ({"question": canary, "api_key": "unused"},
                     {"question": canary, "node_id": "not_in_any_graph"},
                     {"question": canary, "turns": [self.turn()] * 11}):
            response = self.client.post("/study/chat", json=body)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertNotIn(canary, response.text)

    def test_model_chat_contains_last_turn_and_forces_candidate_flags(self):
        node = self.graph["target_id"]
        prior = self.turn(node)
        with patch("teaching_help.generate_text", return_value=json.dumps({"response": "相差一个边界的循环归为同一类。",
                   "source": "local_reference", "review_required": False, "answer_status": "answered"})) as model:
            response = self.client.post("/study/chat", json={"graph": self.graph, "node_id": node,
                "question": "请接着解释差是边界是什么意思。", "turns": [prior], "use_model": True})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["source"], "model_candidate")
            self.assertTrue(response.json()["review_required"])
            self.assertIsNone(response.json()["problem_id"])
            self.assertEqual(self.client.get("/library/problems").json(), [])
            model.assert_called_once()
            prompt = model.call_args.args[0]
            self.assertIn(prior["question"], prompt)
            self.assertIn(prior["response"], prompt)
            self.assertIn(node, prompt)

    def test_chat_roundtrip_and_legacy_state_default(self):
        record = self.client.post("/library/histories", json={"title": "对话测试", "goal": "理解同调",
            "graph": self.graph, "state": {}}).json()
        self.assertEqual(record["state"]["chat_turns"], [])
        state = record["state"]
        state["chat_turns"] = [self.turn(self.graph["target_id"])]
        response = self.client.patch("/library/histories/" + record["id"],
            json={"expected_revision": record["revision"], "state": state})
        self.assertEqual(response.status_code, 200, response.text)
        loaded = self.client.get("/library/histories/" + record["id"]).json()
        self.assertEqual(loaded["state"]["chat_turns"], state["chat_turns"])
        self.assertEqual(loaded["state"]["mastery"], {})
        self.assertEqual(loaded["state"]["attempts"], [])

    def test_uncertain_answer_and_manual_mark_share_one_open_record(self):
        answer = {"response": "这一步的条件不足，需要进一步核对。", "source": "model_candidate",
                  "review_required": True, "answer_status": "uncertain"}
        question = "缺少哪些条件？"
        with patch("teaching_help.generate_text", return_value=json.dumps(answer)):
            result = self.client.post("/study/chat", json={"question": question, "use_model": True}).json()
        problem = self.client.post("/library/problems", json={"question": question, "goal": "自由提问",
            "response": answer["response"], "reason": "user_marked"}).json()
        self.assertEqual(problem["id"], result["problem_id"])
        self.assertEqual(len(self.client.get("/library/problems").json()), 1)
        self.assertEqual(self.client.patch("/library/problems/" + problem["id"], json={"status": "resolved"}).status_code, 200)
        self.assertEqual(self.client.get("/library/problems").json(), [])
        resolved = self.client.get("/library/problems", params={"status": "resolved"}).json()
        self.assertEqual(resolved[0]["id"], problem["id"])
        reopened = self.client.patch("/library/problems/" + problem["id"], json={"status": "open"})
        self.assertEqual(reopened.status_code, 200, reopened.text)

    def test_failed_model_is_queued_without_storing_provider_exception(self):
        exception_canary = "synthetic-provider-body-secret-719"
        with patch("teaching_help.generate_text", side_effect=RuntimeError(exception_canary)):
            result = self.client.post("/study/chat", json={"question": "请解释这个不完整的证明。", "use_model": True})
        self.assertEqual(result.status_code, 502)
        self.assertNotIn(exception_canary, result.text)
        self.assertIsNotNone(result.json()["problem_id"])
        queued = self.client.get("/library/problems").json()[0]
        self.assertEqual(queued["reason"], "model_failure")
        self.assertEqual(queued["response"], "")
        self.assertNotIn(exception_canary, json.dumps(queued))

    def test_problem_storage_failure_is_reported_without_losing_response(self):
        with patch.object(main.library_store, "create_problem", side_effect=main.library_store.LibraryError(
                "本机暂时无法保存", status_code=503)):
            result = self.client.post("/study/chat", json={"question": "没有学习卡时如何开始？"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["response"])
        self.assertTrue(result.json()["problem_save_failed"])
        self.assertIsNone(result.json()["problem_id"])

    def test_deleted_history_does_not_drop_unanswered_question(self):
        result = self.client.post("/study/chat", json={"graph": self.graph, "node_id": self.graph["target_id"],
            "history_id": str(uuid4()), "question": "仍不理解这里为什么取商。"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()["problem_save_failed"])
        queued = self.client.get("/library/problems").json()[0]
        self.assertIsNone(queued["history_id"])
        self.assertEqual(queued["node_id"], self.graph["target_id"])
        self.assertTrue(queued["node_label"])

    def test_scope_and_reference_lookup_do_not_generate_a_graph(self):
        with patch.object(main, "build_graph") as model:
            scope = self.client.post("/study/scope", json={"text": "我想学习数学", "mode": "proof"})
            self.assertEqual(scope.status_code, 200, scope.text)
            self.assertTrue(scope.json()["needs_selection"])
            self.assertGreaterEqual(len(scope.json()["options"]), 3)
            books = self.client.post("/study/references", json={"graph": self.graph, "node_id": self.graph["target_id"]})
            self.assertEqual(books.status_code, 200, books.text)
            self.assertTrue(any("Hatcher" in book["author"] for book in books.json()["books"]))
            model.assert_not_called()
        for route in ("/study/scope", "/study/references", "/library/problems"):
            result = self.client.post(route, json={"question": "not sent"}, headers={"Origin": "https://foreign.invalid"})
            self.assertEqual(result.status_code, 403)


if __name__ == "__main__":
    unittest.main()
