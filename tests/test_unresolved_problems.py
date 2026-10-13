"""Durable question records and schema migration using synthetic temporary data only."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from graph_builder import KnowledgeGraph
from library_models import ProblemCreate, ProblemUpdate
import library_store
from library_store import LibraryError, LibraryNotFound, LibraryStore
from pydantic import ValidationError


def graph():
    return KnowledgeGraph.model_validate({"target_id": "base", "nodes": [
        {"id": "base", "label": "真实存储的知识点名称", "prerequisite_sets": []}]})


class UnresolvedProblemTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mathpath-unresolved-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / ".mathpath" / "library.sqlite3"
        self.store = LibraryStore(self.path)

    def history(self, **updates):
        return self.store.create_history(**{"title": "已有学习记录", "goal": "真实存储的目标", "graph": graph(), **updates})

    def problem(self, **updates):
        return self.store.create_problem(**{"question": "这一步为什么成立？", "reason": "model_failure", **updates})

    def test_general_question_without_graph_or_history_is_durable(self):
        value = self.problem()
        self.assertIsNone(value["history_id"])
        self.assertIsNone(value["node_id"])
        self.assertEqual(value["status"], "open")
        self.assertEqual(LibraryStore(self.path).get_problem(value["id"]), value)
        self.assertEqual(self.store.list_problems(), [value])
        self.assertNotIn("dedupe_key", value)

    def test_saved_history_context_is_derived_and_node_is_validated(self):
        history = self.history()
        value = self.problem(history_id=history["id"], node_id="base", goal="伪造目标", node_label="伪造名称")
        self.assertEqual(value["goal"], history["goal"])
        self.assertEqual(value["node_label"], "真实存储的知识点名称")
        self.assertEqual(value["node_id"], "base")
        with self.assertRaises(LibraryError):
            self.problem(history_id=history["id"], node_id="missing")
        with self.assertRaises(LibraryNotFound):
            self.problem(history_id=str(uuid4()))
        self.assertEqual(len(self.store.list_problems()), 1)

    def test_unsaved_node_needs_label_snapshot(self):
        with self.assertRaises(ValidationError):
            ProblemCreate(question="问题", node_id="base")
        value = self.problem(node_id="base", node_label="当前未保存名称", goal="当前目标")
        self.assertEqual(value["node_label"], "当前未保存名称")
        self.assertEqual(value["goal"], "当前目标")

    def test_duplicate_open_question_is_idempotent_and_manual_reason_wins(self):
        original = self.problem(response="已有说明")
        retry = self.problem()
        self.assertEqual(retry, original)
        marked = self.problem(reason="user_marked")
        self.assertEqual(marked["id"], original["id"])
        self.assertEqual(marked["created_at"], original["created_at"])
        self.assertEqual(marked["response"], "已有说明")
        self.assertEqual(marked["reason"], "user_marked")
        repeated = self.problem(reason="uncertain", response="最近的暂定解释")
        self.assertEqual(repeated["id"], original["id"])
        self.assertEqual(repeated["reason"], "user_marked")
        self.assertEqual(repeated["response"], "最近的暂定解释")
        self.assertEqual(len(self.store.list_problems()), 1)

    def test_distinct_scope_or_question_does_not_merge(self):
        a, b = self.history(), self.history()
        values = [self.problem(), self.problem(goal="另一目标"), self.problem(question="另一问题"),
                  self.problem(history_id=a["id"]), self.problem(history_id=b["id"])]
        self.assertEqual(len({value["id"] for value in values}), 5)

    def test_parallel_retries_create_exactly_one_open_problem(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.problem(), range(24)))
        self.assertEqual(len({item["id"] for item in results}), 1)
        self.assertEqual(len(self.store.list_problems()), 1)

    def test_resolve_and_reopen_are_explicit_and_preserve_original_content(self):
        original = self.problem(response="参考说明")
        resolved = self.store.update_problem(original["id"], "resolved")
        self.assertEqual(resolved["question"], original["question"])
        self.assertEqual(resolved["created_at"], original["created_at"])
        self.assertEqual(self.store.list_problems(), [])
        self.assertEqual(self.store.list_problems(status="resolved"), [resolved])
        reopened = self.store.update_problem(original["id"], "open")
        self.assertEqual(reopened["status"], "open")
        self.assertEqual(reopened["response"], original["response"])
        self.assertEqual(self.store.update_problem(original["id"], "open"), reopened)

    def test_repeat_after_resolution_creates_new_open_entry_and_reopen_conflict_is_safe(self):
        original = self.problem()
        self.store.update_problem(original["id"], "resolved")
        fresh = self.problem()
        self.assertNotEqual(fresh["id"], original["id"])
        with self.assertRaises(LibraryError) as caught:
            self.store.update_problem(original["id"], "open")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.store.get_problem(original["id"])["status"], "resolved")
        self.assertEqual(len(self.store.list_problems(status="all")), 2)

    def test_deleting_project_keeps_question_and_associated_history(self):
        project = self.store.create_project("保留问题")
        history = self.history(project_id=project["id"])
        value = self.problem(history_id=history["id"], node_id="base")
        self.store.delete_projects([project["id"]])
        self.assertIsNone(self.store.get_history(history["id"])["project_id"])
        self.assertEqual(self.store.get_problem(value["id"]), value)

    def test_history_deletion_keeps_two_same_questions_from_distinct_histories(self):
        histories = [self.history(), self.history()]
        values = [self.problem(history_id=item["id"], node_id="base") for item in histories]
        self.store.delete_histories([item["id"] for item in histories])
        for original in values:
            current = self.store.get_problem(original["id"])
            self.assertIsNone(current["history_id"])
            for key in ("node_id", "node_label", "goal", "question", "response", "created_at", "status"):
                self.assertEqual(current[key], original[key])
        self.assertEqual(len(self.store.list_problems()), 2)

    def test_changed_history_graph_does_not_rewrite_existing_question_snapshot(self):
        history = self.history()
        value = self.problem(history_id=history["id"], node_id="base")
        changed = graph().model_dump(mode="json")
        changed["nodes"][0]["label"] = "后来修改的知识点名称"
        self.store.update_history(history["id"], expected_revision=1, graph=changed, goal="后来修改的目标")
        self.assertEqual(self.store.get_problem(value["id"]), value)
        fresh = self.problem(history_id=history["id"], node_id="base")
        self.assertNotEqual(fresh["id"], value["id"])
        self.assertEqual(fresh["node_label"], "后来修改的知识点名称")

    def test_search_metacharacters_are_literal_and_filters_combine_with_pagination(self):
        literal = self.problem(question="计算_50%\\问题")
        self.problem(question="计算a50x普通问题")
        for query in ("_", "%", "\\"):
            self.assertEqual([value["id"] for value in self.store.list_problems(query=query)], [literal["id"]])
        self.assertEqual(self.store.list_problems(query="' OR 1=1--"), [])
        self.store.update_problem(literal["id"], "resolved")
        self.assertEqual(self.store.list_problems(query="%"), [])
        self.assertEqual(len(self.store.list_problems(status="all", limit=1, offset=1)), 1)

    def test_strict_payloads_reject_unknown_fields_blank_text_coercion_and_oversize(self):
        for updates in ({"question": " "}, {"question": "x" * 6001}, {"question": 3}, {"response": "x" * 6001},
                        {"goal": "x" * 5001}, {"node_label": "x" * 301}, {"reason": "api_key"},
                        {"history_id": "../../auth"}, {"api_key": "synthetic-credential-canary"}):
            with self.subTest(updates=list(updates)), self.assertRaises(LibraryError):
                self.problem(**updates)
        for status in (True, "answered", None):
            with self.assertRaises(ValidationError):
                ProblemUpdate(status=status)
        self.assertEqual(self.store.list_problems(), [])

    def test_list_arguments_are_strict_bounded_and_status_allowlisted(self):
        for changes in ({"status": True}, {"status": "anything"}, {"limit": 0}, {"limit": 201}, {"limit": True},
                        {"offset": -1}, {"offset": True}, {"query": "x" * 501}, {"query": 4}):
            with self.assertRaises(LibraryError):
                self.store.list_problems(**changes)

    def test_batch_delete_is_atomic_and_does_not_delete_histories(self):
        history = self.history()
        first, second = self.problem(history_id=history["id"]), self.problem(question="第二问题")
        with self.assertRaises(LibraryNotFound):
            self.store.delete_problems([first["id"], str(uuid4())])
        self.assertEqual(len(self.store.list_problems()), 2)
        self.assertEqual(self.store.delete_problems([first["id"], second["id"]])["deleted_ids"], [first["id"], second["id"]])
        self.assertEqual(self.store.list_problems(), [])
        self.assertEqual(self.store.get_history(history["id"]), history)

    def test_v1_migration_preserves_projects_states_revisions_and_legacy_chat(self):
        project = self.store.create_project("旧版项目")
        legacy_turn = {"id": str(uuid4()), "node_id": "base", "question": "旧问题", "response": "旧解释",
                       "source": "local_reference", "review_required": True, "created_at": "2026-10-12T01:00:00.000Z"}
        history = self.history(project_id=project["id"], state={"notes": {"base": "旧版笔记"}, "chat_turns": [legacy_turn]})
        old_state = history["state"]
        old_state["chat_turns"][0].pop("answer_status")
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute("DROP TABLE unresolved_questions")
            connection.execute("DROP TABLE backup_restore_runs")
            connection.execute("UPDATE histories SET state_json=? WHERE id=?", (json.dumps(old_state), history["id"]))
            connection.execute("PRAGMA user_version=1")
        restored = LibraryStore(self.path)
        self.assertEqual(restored.list_problems(), [])
        self.assertEqual(restored.list_projects(), [project])
        current = restored.get_history(history["id"])
        self.assertEqual(current["revision"], history["revision"])
        self.assertEqual(current["state"]["notes"], {"base": "旧版笔记"})
        self.assertEqual(current["state"]["chat_turns"][0]["answer_status"], "answered")
        with closing(sqlite3.connect(self.path)) as connection:
            from library_store import SCHEMA_VERSION
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_unrelated_v1_database_is_rejected_without_modification(self):
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute("CREATE TABLE sentinel(value TEXT)")
            connection.execute("INSERT INTO sentinel VALUES('preserve')")
            connection.execute("PRAGMA user_version=1")
        with self.assertRaises(LibraryError):
            self.store.list_problems()
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT value FROM sentinel").fetchone()[0], "preserve")
            self.assertEqual(connection.execute("SELECT count(*) FROM sqlite_master WHERE name='unresolved_questions'").fetchone()[0], 0)

    def test_storage_error_does_not_expose_path_or_raw_error(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"synthetic secret not a database")
        with self.assertRaises(LibraryError) as caught:
            self.problem()
        self.assertNotIn("synthetic secret", str(caught.exception))
        self.assertNotIn(str(self.path), str(caught.exception))
        self.assertEqual(caught.exception.status_code, 503)

    def test_module_api_is_lazy_isolated_and_never_reads_credentials(self):
        directory = self.path.parent.parent
        with patch.dict(os.environ, {"MATHPATH_DATA_DIR": str(directory)}), \
                patch("chatgpt_login.load_session", side_effect=AssertionError("不可读取真实凭证")), \
                patch("llm_client.OpenAI", side_effect=AssertionError("不可调用模型")):
            value = library_store.create_problem(question="本机记录", reason="user_marked")
            self.assertEqual(library_store.get_problem(value["id"]), value)
            self.assertEqual(library_store.list_problems(), [value])
            library_store.update_problem(value["id"], "resolved")
            library_store.delete_problems([value["id"]])
        other = LibraryStore(directory / "other.sqlite3")
        self.assertEqual(other.list_problems(), [])


if __name__ == "__main__":
    unittest.main()
