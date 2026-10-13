"""Local API, storage boundaries and learning-mode checks, using fresh data only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from graph_builder import KnowledgeGraph
from planner import current_learning_status
from teaching_help import HelpInput, build_learning_help


class LibraryStudyAPITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mathpath-v04-api-")
        self.environment = patch.dict(os.environ, {"MATHPATH_DATA_DIR": self.temporary.name})
        self.environment.start()
        self.previous_desktop = main.app.state.desktop_local_only
        main.app.state.desktop_local_only = False
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8427")
        self.graph = self.client.get("/example").json()

    def tearDown(self):
        self.client.close()
        main.app.state.desktop_local_only = self.previous_desktop
        self.environment.stop()
        self.temporary.cleanup()

    def history(self, project_id=None, title="同调学习"):
        result = self.client.post("/library/histories", json={"title": title, "goal": "理解取商",
            "project_id": project_id, "graph": self.graph,
            "state": {"graph_source": "example", "notes": {self.graph["target_id"]: "先说明差是边界"}}})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_save_restore_move_and_project_delete_keep_history(self):
        project = self.client.post("/library/projects", json={"title": "拓扑"}).json()
        record = self.history(project["id"])
        loaded = self.client.get("/library/histories/" + record["id"]).json()
        self.assertEqual(loaded["state"]["notes"][self.graph["target_id"]], "先说明差是边界")
        deleted = self.client.post("/library/projects/delete", json={"ids": [project["id"]]})
        self.assertEqual(deleted.status_code, 200)
        retained = self.client.get("/library/histories/" + record["id"]).json()
        self.assertIsNone(retained["project_id"])
        self.assertGreater(retained["revision"], record["revision"])
        self.assertEqual(self.client.get("/library/histories?project_id=uncategorized").json()[0]["id"], record["id"])

    def test_batch_missing_id_rolls_back_and_stale_save_conflicts(self):
        first, second = self.history(title="第一条"), self.history(title="第二条")
        response = self.client.post("/library/histories/delete", json={"ids": [first["id"], str(uuid4())]})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/library/histories/" + first["id"]).status_code, 200)
        updated = self.client.patch("/library/histories/" + first["id"],
            json={"expected_revision": first["revision"], "title": "更新标题"})
        self.assertEqual(updated.status_code, 200)
        conflict = self.client.patch("/library/histories/" + first["id"],
            json={"expected_revision": first["revision"], "title": "过期标题"})
        self.assertEqual(conflict.status_code, 409)
        deleted = self.client.post("/library/histories/delete", json={"ids": [first["id"], second["id"]]})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/library/histories").json(), [])

    def test_foreign_sites_and_bad_host_cannot_mutate_library_or_call_models(self):
        with patch.object(main.library_store, "create_project") as write, patch.object(main, "build_learning_feedback") as model:
            for headers in ({"Origin": "https://foreign.invalid"}, {"Origin": "null"},
                            {"Host": "127.0.0.1:8428"}, {"Host": "foreign.invalid:8427"}):
                with self.subTest(headers=headers):
                    self.assertEqual(self.client.post("/library/projects", json={"title": "不写入"}, headers=headers).status_code, 403)
                    self.assertEqual(self.client.post("/study/feedback", json={}, headers=headers).status_code, 403)
            write.assert_not_called()
            model.assert_not_called()

    def test_invalid_learning_payloads_do_not_echo_private_text(self):
        canary = "synthetic-secret-never-echo-698e"
        for path, body in (("/library/projects", {"title": "project", "api_key": canary}),
                           ("/study/feedback", {"answer": canary}),
                           ("/study/help", {"question": canary})):
            with self.subTest(path=path):
                result = self.client.post(path, json=body)
                self.assertEqual(result.status_code, 422)
                self.assertNotIn(canary, result.text)

    def test_list_search_is_literal_and_never_includes_full_state(self):
        record = self.history(title="百分号%学习")
        response = self.client.get("/library/histories", params={"query": "%"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertNotIn("state", response.json()[0])
        self.assertNotIn("graph", response.json()[0])
        self.assertEqual(response.json()[0]["id"], record["id"])
        self.assertEqual(self.client.get("/library/histories", params={"query": "不存在"}).json(), [])

    def test_tasks_and_local_feedback_do_not_call_model_or_auth(self):
        with patch("study_builder.generate_text") as model, patch.object(main, "start_connection") as auth:
            response = self.client.post("/study/tasks", json={"graph": self.graph, "kind": "lesson",
                "node_id": self.graph["nodes"][0]["id"]})
            self.assertEqual(response.status_code, 200, response.text)
            task = next(task for task in response.json()["tasks"] if task["format"] == "choice")
            feedback = self.client.post("/study/feedback", json={"graph": self.graph, "node_id": task["node_id"],
                "task_id": task["id"], "answer": str(task["correct_index"]), "use_model": False})
            self.assertEqual(feedback.status_code, 200, feedback.text)
            self.assertEqual(feedback.json()["source"], "local_check")
            self.assertEqual(feedback.json()["outcome"], "correct")
            model.assert_not_called()
            auth.assert_not_called()

    def test_local_card_help_never_generates_and_does_not_grade_proof(self):
        node = self.graph["nodes"][0]["id"]
        with patch("teaching_help.generate_text") as model:
            response = self.client.post("/study/help", json={"graph": self.graph, "node_id": node,
                "action": "check_proof", "question": "我认为所有循环都是边界。"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["source"], "local_reference")
            self.assertTrue(response.json()["review_required"])
            self.assertIn("不会自动判定", response.json()["response"])
            model.assert_not_called()


class LearningModeTests(unittest.TestCase):
    def setUp(self):
        self.graph = KnowledgeGraph.model_validate({"target_id": "target", "nodes": [
            {"id": "root", "label": "基础概念", "prerequisite_sets": []},
            {"id": "target", "label": "目标", "prerequisite_sets": [["root"]]},
        ]})

    def test_intuition_boundary_is_separate_from_full_mastery(self):
        status = current_learning_status(self.graph, [], mode="intuition",
            mastery={"root": {"definition": True, "intuition": True, "application": False}})
        self.assertEqual(status.known_ids, [])
        self.assertEqual(status.planning_known_ids, ["root"])
        self.assertEqual(status.recommended_ids, ["target"])
        self.assertFalse(status.completed)

    def test_proof_requires_all_three_by_default_and_legacy_stays_strict(self):
        state = {"root": {"definition": True, "intuition": True, "application": False}}
        proof = current_learning_status(self.graph, [], mode="proof", mastery=state)
        legacy = current_learning_status(self.graph, [])
        self.assertEqual(proof.recommended_ids, ["root"])
        self.assertEqual(legacy.recommended_ids, ["root"])

    def test_node_requirement_can_override_mode_boundary(self):
        payload = self.graph.model_dump()
        payload["nodes"][0]["required_dimensions"] = ["definition"]
        graph = KnowledgeGraph.model_validate(payload)
        result = current_learning_status(graph, [], mode="proof", mastery={"root": {"definition": True}})
        self.assertEqual(result.recommended_ids, ["target"])


class FocusedHelpModelTests(unittest.TestCase):
    def test_explicit_model_help_is_always_labelled_candidate(self):
        graph = KnowledgeGraph.model_validate({"target_id": "a", "nodes": [
            {"id": "a", "label": "概念", "prerequisite_sets": []}]})
        response = {"response": "请补充这里采用的定义。", "source": "local_reference", "review_required": False}
        with patch("teaching_help.generate_text", return_value=json.dumps(response)) as model:
            result = build_learning_help(HelpInput(graph=graph, node_id="a", action="proof_step",
                question="为什么成立？", use_model=True))
        self.assertEqual(result.source, "model_candidate")
        self.assertTrue(result.review_required)
        model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
