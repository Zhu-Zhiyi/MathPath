"""End-to-end backup routes with temporary records and no account access."""
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import main


class BackupAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="mathpath-backup-api-")
        self.environment = patch.dict(os.environ, {"MATHPATH_DATA_DIR": self.directory.name})
        self.environment.start()
        self.previous = main.app.state.desktop_local_only
        main.app.state.desktop_local_only = False
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8427")

    def tearDown(self):
        self.client.close()
        main.app.state.desktop_local_only = self.previous
        self.environment.stop()
        self.directory.cleanup()

    def empty_backup(self):
        return {"format": "mathpath_library_backup", "version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(), "projects": [], "histories": [], "problems": []}

    def test_preview_does_not_create_a_database_or_read_account_config(self):
        with patch.object(main, "get_public_settings") as config, patch.object(main, "start_connection") as auth:
            response = self.client.post("/library/backup/preview", json=self.empty_backup())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"projects": 0, "histories": 0, "problems": 0, "already_restored": False})
        self.assertFalse((Path(self.directory.name) / ".mathpath/library.sqlite3").exists())
        self.assertEqual(response.headers["cache-control"], "no-store")
        config.assert_not_called()
        auth.assert_not_called()

    def test_full_export_restore_repeat_and_relationships(self):
        graph = self.client.get("/example").json()
        project = self.client.post("/library/projects", json={"title": "完整备份项目"}).json()
        history = self.client.post("/library/histories", json={"title": "学习历史", "goal": "原目标",
            "project_id": project["id"], "graph": graph, "state": {"notes": {graph["target_id"]: "自己的数学笔记"}}}).json()
        problem = self.client.post("/library/problems", json={"history_id": history["id"], "node_id": graph["target_id"],
            "question": "还不明白这里为什么要取商。"}).json()
        exported = self.client.get("/library/backup")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("attachment", exported.headers["content-disposition"])
        backup = exported.json()
        self.assertEqual(backup["histories"][0]["state"]["notes"][graph["target_id"]], "自己的数学笔记")
        self.assertEqual(backup["problems"][0]["id"], problem["id"])
        restored = self.client.post("/library/backup/restore", json=backup)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertFalse(restored.json()["already_restored"])
        records = self.client.get("/library/histories").json()
        self.assertEqual(len(records), 2)
        added = next(item for item in records if item["id"] != history["id"])
        self.assertNotEqual(added["project_id"], project["id"])
        added_problem = next(item for item in self.client.get("/library/problems").json() if item["id"] != problem["id"])
        self.assertEqual(added_problem["history_id"], added["id"])
        repeat = self.client.post("/library/backup/restore", json=backup)
        self.assertTrue(repeat.json()["already_restored"])
        self.assertEqual(len(self.client.get("/library/histories").json()), 2)
        explicit = self.client.post("/library/backup/restore?repeat=true", json=backup)
        self.assertEqual(explicit.status_code, 200, explicit.text)
        self.assertFalse(explicit.json()["already_restored"])
        self.assertEqual(len(self.client.get("/library/histories").json()), 3)

    def test_invalid_backup_is_rejected_without_echo_or_partial_restore(self):
        canary = "synthetic-auth-text-should-not-echo-741"
        value = self.empty_backup()
        value["api_key"] = canary
        result = self.client.post("/library/backup/restore", json=value)
        self.assertEqual(result.status_code, 422)
        self.assertNotIn(canary, result.text)
        self.assertFalse((Path(self.directory.name) / ".mathpath/library.sqlite3").exists())

    def test_foreign_origin_cannot_export_or_restore_private_learning_data(self):
        with patch.object(main.library_store, "export_backup") as export, patch.object(main.library_store, "restore_backup") as restore:
            self.assertEqual(self.client.get("/library/backup", headers={"Origin": "https://foreign.invalid"}).status_code, 403)
            self.assertEqual(self.client.post("/library/backup/restore", json=self.empty_backup(),
                headers={"Origin": "https://foreign.invalid"}).status_code, 403)
        export.assert_not_called()
        restore.assert_not_called()

    def test_example_catalog_and_all_cards_are_offline(self):
        with patch.object(main, "generate_text") as model:
            catalog = self.client.get("/examples").json()
            self.assertEqual({item["id"] for item in catalog}, {"homology", "rank_nullity", "epsilon_delta"})
            for item in catalog:
                graph = self.client.get("/example", params={"example_id": item["id"]}).json()
                for node in graph["nodes"]:
                    lesson = self.client.post("/lesson", json={"graph": graph, "node_id": node["id"]})
                    self.assertEqual(lesson.status_code, 200, lesson.text)
                    self.assertEqual(lesson.json()["source"], "curated_example")
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
