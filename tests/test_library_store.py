"""Real SQLite checks, always in fresh temporary directories with synthetic data."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
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
import library_store
from library_store import LibraryConflict, LibraryError, LibraryNotFound, LibraryStore
from library_models import StudyState


def graph(*, label="基础概念", node_id="base"):
    return KnowledgeGraph.model_validate({"target_id": node_id,
                                         "nodes": [{"id": node_id, "label": label, "prerequisite_sets": []}]})


def attempt(**updates):
    value = {"id": str(uuid4()), "node_id": "base", "task_id": "exercise:base:0", "answer": "答案",
             "hint_level": 0, "attempt_type": "exercise", "created_at": "2026-10-12T01:00:00.000Z"}
    value.update(updates)
    return value


class LibraryStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mathpath-library-test-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / ".mathpath" / "library.sqlite3"
        self.store = LibraryStore(self.path)

    def history(self, **updates):
        values = {"title": "同调取商", "goal": "为什么同调需要取商", "graph": graph()}
        values.update(updates)
        return self.store.create_history(**values)

    def test_constructing_store_does_not_create_or_read_files(self):
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.path, self.path)

    def test_initial_database_has_known_version_and_only_library_tables(self):
        self.assertEqual(self.store.list_projects(), [])
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], library_store.SCHEMA_VERSION)
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(names, {"projects", "histories", "unresolved_questions", "backup_restore_runs"})

    def test_project_create_trim_rename_and_persist_to_new_store(self):
        project = self.store.create_project("  拓扑学习  ")
        self.assertEqual(project["title"], "拓扑学习")
        renamed = self.store.rename_project(project["id"], "课程作业")
        self.assertEqual(renamed["created_at"], project["created_at"])
        self.assertEqual(LibraryStore(self.path).list_projects(), [renamed])

    def test_history_roundtrip_preserves_notes_attempts_and_reviews(self):
        state = {"mastery": {"base": {"definition": True, "intuition": False, "application": True}},
                 "notes": {"base": "我还需要检查定义"}, "attempts": [attempt()],
                 "reviews": {"base": {"due_at": "2026-10-13T01:00:00.000Z", "last_attempt_at": None,
                                      "interval_days": 1, "streak": 0}},
                 "active_node_id": "base", "study_mode": "proof", "graph_source": "example", "view": "list"}
        history = self.history(state=state)
        self.assertEqual(history["revision"], 1)
        reopened = LibraryStore(self.path).get_history(history["id"])
        self.assertEqual(reopened, history)
        self.assertEqual(reopened["state"]["notes"], state["notes"])
        self.assertEqual(reopened["state"]["attempts"][0]["answer"], "答案")

    def test_history_summary_contains_counts_but_no_whole_state_or_graph(self):
        history = self.history(state={"mastery": {"base": {"definition": True, "intuition": True, "application": True}},
                                      "attempts": [attempt()]})
        summary = self.store.list_histories()[0]
        self.assertEqual(summary["id"], history["id"])
        self.assertEqual((summary["node_count"], summary["lesson_count"], summary["attempt_count"], summary["mastered_count"]),
                         (1, 0, 1, 1))
        self.assertNotIn("graph", summary)
        self.assertNotIn("state", summary)
        self.assertNotIn("migration_key", summary)

    def test_missing_project_cannot_create_history(self):
        with self.assertRaises(LibraryNotFound):
            self.history(project_id=str(uuid4()))
        self.assertEqual(self.store.list_histories(), [])

    def test_batch_project_delete_preserves_histories_and_changes_revisions(self):
        project_a, project_b = self.store.create_project("A"), self.store.create_project("B")
        history_a = self.history(project_id=project_a["id"], state={"notes": {"base": "保留的笔记"}})
        history_b = self.history(project_id=project_b["id"])
        untouched = self.history()
        result = self.store.delete_projects([project_a["id"], project_b["id"]])
        self.assertEqual(result["deleted_ids"], [project_a["id"], project_b["id"]])
        self.assertEqual(self.store.list_projects(), [])
        for value in (history_a, history_b):
            current = self.store.get_history(value["id"])
            self.assertIsNone(current["project_id"])
            self.assertEqual(current["revision"], 2)
            self.assertEqual(current["state"], value["state"])
        self.assertEqual(self.store.get_history(untouched["id"])["revision"], 1)
        self.assertEqual(self.store.get_history(history_a["id"])["state"]["notes"]["base"], "保留的笔记")

    def test_project_batch_delete_is_atomic_when_one_id_missing(self):
        project = self.store.create_project("保留项目")
        history = self.history(project_id=project["id"])
        with self.assertRaises(LibraryNotFound):
            self.store.delete_projects([project["id"], str(uuid4())])
        self.assertEqual(self.store.list_projects(), [project])
        self.assertEqual(self.store.get_history(history["id"]), history)

    def test_storage_failure_after_assignment_update_rolls_back_entire_project_delete(self):
        project = self.store.create_project("保留项目")
        history = self.history(project_id=project["id"], state={"notes": {"base": "不要丢失"}})
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute("""CREATE TRIGGER synthetic_project_failure BEFORE DELETE ON projects
                                  BEGIN SELECT RAISE(ABORT, 'synthetic-secret-error'); END""")
        # This fails after the operation has already attempted to detach histories.
        with self.assertRaises(LibraryError) as caught:
            self.store.delete_projects([project["id"]])
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("synthetic-secret", str(caught.exception))
        self.assertEqual(self.store.list_projects(), [project])
        self.assertEqual(self.store.get_history(history["id"]), history)

    def test_history_batch_delete_does_not_delete_project(self):
        project = self.store.create_project("项目")
        histories = [self.history(project_id=project["id"]) for _ in range(3)]
        self.store.delete_histories([item["id"] for item in histories[:2]])
        self.assertEqual([item["id"] for item in self.store.list_histories()], [histories[2]["id"]])
        self.assertEqual(self.store.list_projects(), [project])

    def test_history_batch_delete_is_atomic_when_one_id_missing(self):
        history = self.history()
        with self.assertRaises(LibraryNotFound):
            self.store.delete_histories([history["id"], str(uuid4())])
        self.assertEqual(self.store.get_history(history["id"]), history)

    def test_move_batch_to_project_and_then_uncategorized(self):
        project = self.store.create_project("拓扑")
        histories = [self.history() for _ in range(2)]
        ids = [item["id"] for item in histories]
        result = self.store.move_histories(ids, project["id"])
        self.assertEqual(result, {"moved_ids": ids, "project_id": project["id"]})
        self.assertEqual(len(self.store.list_histories(project["id"])), 2)
        self.assertEqual(self.store.list_histories(uncategorized=True), [])
        self.store.move_histories(ids, None)
        self.assertEqual(len(self.store.list_histories(uncategorized=True)), 2)
        self.assertEqual(self.store.get_history(ids[0])["revision"], 3)

    def test_move_batch_rolls_back_for_missing_history_or_project(self):
        history = self.history()
        project = self.store.create_project("课程")
        for ids, project_id in (([history["id"], str(uuid4())], project["id"]), ([history["id"]], str(uuid4()))):
            with self.assertRaises(LibraryNotFound):
                self.store.move_histories(ids, project_id)
            self.assertEqual(self.store.get_history(history["id"]), history)

    def test_revision_conflict_preserves_newer_state(self):
        history = self.history()
        newer = self.store.update_history(history["id"], expected_revision=1, state={"notes": {"base": "新内容"}})
        self.assertEqual(newer["revision"], 2)
        with self.assertRaises(LibraryConflict):
            self.store.update_history(history["id"], expected_revision=1, state={"notes": {"base": "旧窗口"}})
        self.assertEqual(self.store.get_history(history["id"]), newer)

    def test_project_deletion_invalidates_old_revision(self):
        project = self.store.create_project("稍后删除")
        history = self.history(project_id=project["id"])
        self.store.delete_projects([project["id"]])
        with self.assertRaises(LibraryConflict):
            self.store.update_history(history["id"], expected_revision=1, title="旧窗口保存")

    def test_replacing_graph_resets_old_state_even_when_ids_match(self):
        history = self.history(state={"notes": {"base": "只对应旧概念"}, "attempts": [attempt()]})
        changed = self.store.update_history(history["id"], expected_revision=1, graph=graph(label="另一个概念"))
        self.assertEqual(changed["state"], StudyState().model_dump(mode="json"))

    def test_replacing_graph_can_supply_matching_new_state(self):
        history = self.history(state={"notes": {"base": "旧笔记"}})
        changed = self.store.update_history(history["id"], expected_revision=1, graph=graph(node_id="new"),
                                            state={"notes": {"new": "新笔记"}, "active_node_id": "new"})
        self.assertEqual(changed["state"]["notes"], {"new": "新笔记"})

    def test_invalid_cross_graph_state_rejected_without_partial_changes(self):
        history = self.history()
        with self.assertRaises(LibraryError):
            self.store.update_history(history["id"], expected_revision=1, title="不应保存", state={"notes": {"missing": "非法"}})
        self.assertEqual(self.store.get_history(history["id"]), history)

    def test_metadata_patch_retains_existing_learning_state(self):
        history = self.history(state={"notes": {"base": "已有笔记"}})
        renamed = self.store.update_history(history["id"], expected_revision=1, title="新标题")
        self.assertEqual(renamed["state"], history["state"])
        self.assertEqual(renamed["title"], "新标题")
        self.assertEqual(renamed["created_at"], history["created_at"])

    def test_same_graph_different_node_order_retains_state(self):
        original = KnowledgeGraph.model_validate({"target_id": "goal", "nodes": [
            {"id": "base", "label": "基础", "prerequisite_sets": []},
            {"id": "goal", "label": "目标", "prerequisite_sets": [["base"]]}]})
        history = self.history(graph=original, state={"notes": {"base": "已有笔记"}})
        reordered = original.model_dump(mode="json")
        reordered["nodes"].reverse()
        changed = self.store.update_history(history["id"], expected_revision=1, graph=reordered)
        self.assertEqual(changed["state"], history["state"])

    def test_migration_key_is_idempotent_and_not_exported(self):
        history = self.history(migration_key="legacy-workspace-v1:" + str(uuid4()))
        # Retry the exact legacy request after the first response was lost.
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            key = connection.execute("SELECT migration_key FROM histories").fetchone()[0]
        duplicate = self.history(migration_key=key)
        self.assertEqual(duplicate, history)
        self.assertEqual(len(self.store.list_histories()), 1)
        self.assertNotIn("migration_key", history)

    def test_parallel_migration_retries_create_one_history(self):
        key = "legacy-workspace-v1:" + str(uuid4())
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.history(migration_key=key), range(16)))
        self.assertEqual(len({item["id"] for item in results}), 1)
        self.assertEqual(len(self.store.list_histories()), 1)

    def test_parallel_creation_uses_independent_connections(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda number: self.store.create_project(f"项目 {number}"), range(24)))
        self.assertEqual(len({item["id"] for item in results}), 24)
        self.assertEqual(len(self.store.list_projects()), 24)

    def test_two_racing_updates_have_exactly_one_winner(self):
        history = self.history()
        def update(title):
            try:
                return self.store.update_history(history["id"], expected_revision=1, title=title)["revision"]
            except LibraryConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(update, ("窗口 A", "窗口 B")))
        self.assertCountEqual(results, [2, "conflict"])

    def test_strict_ids_and_duplicate_batches_rejected(self):
        history = self.history()
        for ids in ([history["id"], history["id"]], [], ["'; DROP TABLE histories;--"], [123]):
            with self.assertRaises(LibraryError):
                self.store.delete_histories(ids)
        with self.assertRaises(LibraryError):
            self.store.get_history("../../credentials")
        self.assertEqual(self.store.get_history(history["id"]), history)

    def test_sql_metacharacters_in_title_are_literal_data(self):
        title = "'); DROP TABLE histories;--"
        project = self.store.create_project(title)
        history = self.history(title=title)
        self.assertEqual(self.store.list_projects()[0]["title"], project["title"])
        self.assertEqual(self.store.get_history(history["id"])["title"], title)

    def test_listing_filters_and_pagination_are_bounded(self):
        project = self.store.create_project("项目")
        for _ in range(3):
            self.history(project_id=project["id"])
        self.history()
        self.assertEqual(len(self.store.list_histories()), 4)
        self.assertEqual(len(self.store.list_histories(project["id"], limit=2)), 2)
        self.assertEqual(len(self.store.list_histories(project["id"], limit=2, offset=2)), 1)
        self.assertEqual(len(self.store.list_histories(uncategorized=True)), 1)
        for changes in ({"limit": 0}, {"limit": 201}, {"limit": True}, {"offset": -1}, {"uncategorized": "true"}):
            with self.assertRaises(LibraryError):
                self.store.list_histories(**changes)

    def test_search_matches_title_and_goal_with_literal_like_metacharacters(self):
        matching = self.history(title="计算_50%\\专题", goal="群的商与拓扑")
        self.history(title="计算a50x专题", goal="普通目标")
        for query in ("_", "%", "\\", "群的商"):
            self.assertEqual([item["id"] for item in self.store.list_histories(query=query)], [matching["id"]])
        self.assertEqual(self.store.list_histories(query="' OR 1=1--"), [])
        for value in (True, 3, "x" * 501):
            with self.assertRaises(LibraryError):
                self.store.list_histories(query=value)

    def test_search_combines_project_filter_and_pagination(self):
        project = self.store.create_project("课程")
        inside = self.history(title="群论", project_id=project["id"])
        self.history(title="群论未分类")
        self.history(title="分析", project_id=project["id"])
        result = self.store.list_histories(project["id"], query="群论", limit=1)
        self.assertEqual([item["id"] for item in result], [inside["id"]])

    def test_state_byte_limit_checks_utf8_bytes_and_leaves_no_record(self):
        attempts = [attempt(answer="界" * 6000) for _ in range(120)]
        with self.assertRaises(LibraryError) as caught:
            self.history(state={"attempts": attempts})
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(self.store.list_histories(), [])

    def test_update_byte_limit_leaves_previous_record_unchanged(self):
        history = self.history()
        with self.assertRaises(LibraryError) as caught:
            self.store.update_history(history["id"], expected_revision=1,
                                      state={"attempts": [attempt(answer="x" * 6000) for _ in range(350)]})
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(self.store.get_history(history["id"]), history)

    def test_no_credentials_are_read_saved_or_exported(self):
        self.path.parent.mkdir(parents=True)
        sentinel = self.path.parent / "api_settings.dpapi"
        sentinel.write_bytes(b"synthetic-credential-canary")
        import chatgpt_login
        import llm_client
        with patch.object(chatgpt_login, "load_session", side_effect=AssertionError("不可读取登录记录")), \
                patch.object(llm_client, "OpenAI", side_effect=AssertionError("不可调用模型")):
            history = self.history()
            self.store.list_projects()
            self.store.list_histories()
            self.store.get_history(history["id"])
        self.assertEqual(sentinel.read_bytes(), b"synthetic-credential-canary")
        self.assertNotIn("synthetic-credential-canary", json.dumps(history))
        self.assertNotIn(b"synthetic-credential-canary", self.path.read_bytes())

    def test_module_functions_resolve_override_lazily_and_stores_are_isolated(self):
        with patch.dict(os.environ, {"MATHPATH_DATA_DIR": str(self.directory)}):
            project = library_store.create_project("覆盖目录")
            self.assertEqual(library_store.default_library_path(), self.path)
            self.assertEqual(library_store.list_projects(), [project])
        other = LibraryStore(self.directory / "other" / "library.sqlite3")
        self.assertEqual(other.list_projects(), [])

    def test_unknown_newer_schema_fails_safely_without_modification(self):
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute("PRAGMA user_version=99")
            connection.execute("CREATE TABLE sentinel(value TEXT)")
            connection.execute("INSERT INTO sentinel VALUES('keep me')")
        with self.assertRaises(LibraryError) as caught:
            self.store.list_projects()
        self.assertEqual(caught.exception.status_code, 503)
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM sentinel").fetchone()[0], "keep me")

    def test_unversioned_unrelated_database_is_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute("CREATE TABLE foreign_data(value TEXT)")
        with self.assertRaises(LibraryError):
            self.store.list_histories()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_corrupt_database_error_does_not_expose_path_or_raw_error(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"synthetic raw secret invalid database")
        with self.assertRaises(LibraryError) as caught:
            self.store.list_projects()
        self.assertNotIn(str(self.path), str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(caught.exception.status_code, 503)

    def test_tampered_stored_state_is_rejected_without_exporting_unknown_fields(self):
        history = self.history()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute("UPDATE histories SET state_json=? WHERE id=?", (json.dumps({"api_key": "secret"}), history["id"]))
        with self.assertRaises(LibraryError) as caught:
            self.store.get_history(history["id"])
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
