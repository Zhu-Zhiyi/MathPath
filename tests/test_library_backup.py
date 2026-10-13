"""Learning-only full backup checks using synthetic temporary SQLite libraries."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import json
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
from lesson_builder import build_lesson, load_example_graph
from library_models import BackupEnvelope
import library_store
from library_store import LibraryError, LibraryStore


TIMESTAMP = "2026-10-13T04:05:06.000Z"


def simple_graph(node_id="base", label="基础概念"):
    return KnowledgeGraph.model_validate({"target_id": node_id,
        "nodes": [{"id": node_id, "label": label, "prerequisite_sets": []}]})


class LibraryBackupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mathpath-backup-test-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.source = LibraryStore(self.directory / "source" / "library.sqlite3")
        self.target = LibraryStore(self.directory / "target" / "library.sqlite3")

    def seed(self, store=None, *, full=False):
        store = store or self.source
        project = store.create_project("拓扑学习")
        graph = load_example_graph("homology") if full else simple_graph()
        state = {}
        if full:
            node_id = graph.nodes[0].id
            lesson = build_lesson(graph, node_id)
            task = lesson.learning_tasks[0]
            state = {"notes": {node_id: "需要保留的笔记"},
                     "mastery": {node_id: {"definition": True, "intuition": True, "application": False}},
                     "lessons": {node_id: lesson.model_dump(mode="json")},
                     "attempts": [{"id": str(uuid4()), "node_id": node_id, "task_id": task.id,
                         "answer": "我的作答", "hint_level": 1, "attempt_type": task.kind,
                         "outcome": "hinted", "created_at": TIMESTAMP, "task": task.model_dump(mode="json")}],
                     "chat_turns": [{"id": str(uuid4()), "node_id": node_id, "question": "这一步为什么？",
                         "response": "先检查数学约定。", "source": "local_reference", "review_required": True,
                         "answer_status": "uncertain", "created_at": TIMESTAMP}],
                     "reviews": {node_id: {"due_at": "2026-10-14T04:05:06.000Z",
                         "last_attempt_at": TIMESTAMP, "interval_days": 1, "streak": 2}},
                     "diagnostic_answers": {"diagnostic_a": "诊断作答"},
                     "final_answers": {"final_a": "迁移作答"}, "active_node_id": node_id,
                     "graph_source": "example", "study_mode": "proof", "view": "list"}
        history = store.create_history(title="理解同调", goal="理解同调为什么取商", graph=graph, state=state,
                                       project_id=project["id"], migration_key="fixture:local")
        open_problem = store.create_problem(history_id=history["id"], node_id=graph.nodes[0].id,
                                            question="我还没理解这里", response="保留回答快照", reason="uncertain")
        resolved = store.create_problem(history_id=history["id"], question="另一个问题", reason="user_marked")
        resolved = store.update_problem(resolved["id"], "resolved")
        orphan_history = store.create_history(title="会删除的地图", goal="孤立快照的目标", graph=simple_graph())
        orphan = store.create_problem(history_id=orphan_history["id"], node_id="base", question="地图删除后仍保留")
        store.delete_histories([orphan_history["id"]])
        orphan = store.get_problem(orphan["id"])
        return project, history, (open_problem, resolved, orphan)

    def unchanged(self, store):
        backup = store.export_backup()
        backup.pop("created_at")
        return backup

    def assert_invalid(self, backup, *, code="invalid_backup"):
        before = self.unchanged(self.target) if self.target.path.exists() else None
        with self.assertRaises(LibraryError) as caught:
            self.target.restore_backup(backup)
        self.assertEqual(caught.exception.code, code)
        if before is None:
            self.assertFalse(self.target.path.exists())
        else:
            self.assertEqual(self.unchanged(self.target), before)

    def test_complete_roundtrip_preserves_every_learning_snapshot_and_relationship(self):
        source_project, source_history, source_problems = self.seed(full=True)
        backup = self.source.export_backup()
        self.assertEqual(backup["format"], "mathpath_library_backup")
        self.assertEqual(backup["version"], 1)
        self.assertNotIn("migration_key", backup["histories"][0])
        result = self.target.restore_backup(backup)
        self.assertEqual(result, {"projects": 1, "histories": 1, "problems": 3, "already_restored": False})
        restored = self.target.export_backup()
        project, history = restored["projects"][0], restored["histories"][0]
        self.assertNotEqual(project["id"], source_project["id"])
        self.assertNotEqual(history["id"], source_history["id"])
        self.assertEqual(history["project_id"], project["id"])
        for key in ("title", "goal", "graph", "state", "created_at", "updated_at"):
            self.assertEqual(history[key], source_history[key])
        self.assertEqual(history["revision"], 1)
        original_by_question = {problem["question"]: problem for problem in source_problems}
        for problem in restored["problems"]:
            original = original_by_question[problem["question"]]
            self.assertNotEqual(problem["id"], original["id"])
            self.assertEqual(problem["history_id"], history["id"] if original["history_id"] else None)
            for key in ("node_id", "goal", "node_label", "response", "reason", "status", "created_at", "updated_at"):
                self.assertEqual(problem[key], original[key])

    def test_restore_appends_without_overwriting_existing_records_or_reusing_source_ids(self):
        self.seed()
        existing_project = self.target.create_project("本机已有项目")
        existing = self.target.create_history(title="本机学习", goal="本机目标", graph=simple_graph(),
            state={"notes": {"base": "本机笔记"}}, project_id=existing_project["id"])
        self.target.restore_backup(self.source.export_backup())
        self.assertEqual(self.target.get_history(existing["id"]), existing)
        self.assertEqual(len(self.target.list_projects()), 2)
        self.assertEqual(len(self.target.list_histories()), 2)

    def test_repeated_file_restore_is_idempotent_and_preview_reports_it(self):
        self.seed()
        backup = self.source.export_backup()
        self.assertFalse(self.target.preview_backup(backup)["already_restored"])
        self.target.restore_backup(backup)
        before = self.unchanged(self.target)
        self.assertTrue(self.target.preview_backup(backup)["already_restored"])
        self.assertTrue(self.target.restore_backup(backup)["already_restored"])
        self.assertEqual(self.unchanged(self.target), before)

    def test_explicit_repeat_can_recover_deleted_import_and_preserves_current_records(self):
        self.seed()
        existing = self.target.create_history(title="本机保留学习", goal="本机保留目标", graph=simple_graph())
        backup = self.source.export_backup()
        self.target.restore_backup(backup)
        imported = next(history for history in self.target.list_histories() if history["id"] != existing["id"])
        self.target.delete_histories([imported["id"]])
        self.target.delete_projects([project["id"] for project in self.target.list_projects()])
        self.target.delete_problems([problem["id"] for problem in self.target.list_problems(status="all")])
        self.assertTrue(self.target.restore_backup(backup)["already_restored"])
        self.assertEqual(len(self.target.list_histories()), 1)
        self.assertEqual(self.target.get_history(existing["id"]), existing)
        recovered = self.target.restore_backup(backup, repeat=True)
        self.assertFalse(recovered["already_restored"])
        self.assertEqual((len(self.target.list_projects()), len(self.target.list_histories()),
                          len(self.target.list_problems(status="all"))), (1, 2, 3))
        self.assertEqual(self.target.get_history(existing["id"]), existing)

    def test_explicit_repeat_appends_distinct_linked_and_unlinked_problem_records(self):
        self.seed()
        backup = self.source.export_backup()
        self.target.restore_backup(backup)
        self.target.restore_backup(backup, repeat=True)
        self.assertEqual((len(self.target.list_projects()), len(self.target.list_histories()),
                          len(self.target.list_problems(status="all"))), (2, 2, 6))
        self.assertTrue(self.target.preview_backup(backup)["already_restored"])
        self.assertTrue(self.target.restore_backup(backup)["already_restored"])

    def test_repeat_flag_is_strict_boolean(self):
        self.seed()
        backup = self.source.export_backup()
        for value in (1, "true", None):
            with self.assertRaises(LibraryError):
                self.target.restore_backup(backup, repeat=value)
        self.assertFalse(self.target.path.exists())

    def test_canonical_hash_ignores_json_and_record_order(self):
        self.seed()
        backup = self.source.export_backup()
        self.target.restore_backup(backup)
        reordered = dict(reversed(list(copy.deepcopy(backup).items())))
        reordered["problems"].reverse()
        text = json.dumps(reordered, ensure_ascii=False, indent=4)
        self.assertTrue(self.target.restore_backup(text)["already_restored"])

    def test_concurrent_restore_of_same_backup_imports_exactly_once(self):
        self.seed()
        backup = self.source.export_backup()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.target.restore_backup, [backup, backup]))
        self.assertEqual(sorted(result["already_restored"] for result in results), [False, True])
        self.assertEqual(len(self.target.list_histories()), 1)
        self.assertEqual(len(self.target.list_problems(status="all")), 3)

    def test_preview_on_new_location_does_not_create_directory_or_database(self):
        self.seed()
        preview = self.target.preview_backup(self.source.export_backup())
        self.assertEqual(preview, {"projects": 1, "histories": 1, "problems": 3, "already_restored": False})
        self.assertFalse(self.target.path.parent.exists())

    def test_export_is_not_truncated_by_history_or_problem_list_pagination(self):
        project = self.source.create_project("超过一页")
        for index in range(205):
            history = self.source.create_history(title=f"历史 {index}", goal="目标", graph=simple_graph(),
                                                  project_id=project["id"])
            self.source.create_problem(history_id=history["id"], node_id="base", question=f"问题 {index}")
        self.assertEqual(len(self.source.list_histories(limit=200)), 200)
        self.assertEqual(len(self.source.list_problems(limit=200)), 200)
        backup = self.source.export_backup()
        self.assertEqual((len(backup["histories"]), len(backup["problems"])), (205, 205))
        self.assertEqual(self.target.restore_backup(backup)["histories"], 205)
        self.assertEqual(len(self.target.export_backup()["histories"]), 205)

    def test_project_delete_uncategorized_assignment_and_orphan_problems_roundtrip(self):
        project, history, _problems = self.seed()
        self.source.delete_projects([project["id"]])
        backup = self.source.export_backup()
        self.assertIsNone(backup["histories"][0]["project_id"])
        self.target.restore_backup(backup)
        self.assertEqual(self.target.list_projects(), [])
        self.assertEqual(len(self.target.list_histories(uncategorized=True)), 1)
        self.assertEqual(sum(problem["history_id"] is None for problem in self.target.list_problems(status="all")), 1)

    def test_distinct_open_problem_snapshots_survive_after_two_origin_histories_deleted(self):
        ids = []
        for _ in range(2):
            history = self.source.create_history(title="相同地图", goal="相同目标", graph=simple_graph())
            self.source.create_problem(history_id=history["id"], node_id="base", question="相同问题")
            ids.append(history["id"])
        self.source.delete_histories(ids)
        self.target.restore_backup(self.source.export_backup())
        problems = self.target.list_problems()
        self.assertEqual(len(problems), 2)
        self.assertTrue(all(problem["history_id"] is None for problem in problems))

    def test_restored_linked_open_problem_retains_ordinary_retry_deduplication(self):
        self.seed()
        self.target.restore_backup(self.source.export_backup())
        history = self.target.list_histories()[0]
        original = next(problem for problem in self.target.list_problems()
                        if problem["history_id"] == history["id"])
        retried = self.target.create_problem(history_id=history["id"], node_id="base", question=original["question"])
        self.assertEqual(retried["id"], original["id"])

    def test_map_replacement_detaches_old_problem_snapshots_and_backup_remains_valid(self):
        _project, history, problems = self.seed()
        changed = self.source.update_history(history["id"], expected_revision=1, graph=simple_graph("other"))
        self.assertEqual(changed["graph"]["target_id"], "other")
        for original in problems[:2]:
            problem = self.source.get_problem(original["id"])
            self.assertEqual(problem["history_id"], None if original["node_id"] else history["id"])
            self.assertEqual(problem["goal"], original["goal"])
            self.assertEqual(problem["created_at"], original["created_at"])
        self.target.restore_backup(self.source.export_backup())
        self.assertEqual(len(self.target.list_problems(status="all")), 3)

    def test_top_level_and_nested_provider_credentials_are_rejected_without_writes(self):
        self.seed()
        valid = self.source.export_backup()
        for mutate in (lambda value: value.update({"api_key": "synthetic-not-a-key"}),
                       lambda value: value["projects"][0].update({"provider": "not-learning-data"}),
                       lambda value: value["histories"][0]["state"].update({"access_token": "synthetic"}),
                       lambda value: value["problems"][0].update({"authorization": "synthetic"})):
            with self.subTest(mutate=mutate):
                candidate = copy.deepcopy(valid)
                mutate(candidate)
                self.assert_invalid(candidate)

    def test_duplicate_record_ids_rejected_for_each_collection(self):
        self.seed()
        valid = self.source.export_backup()
        for collection in ("projects", "histories", "problems"):
            candidate = copy.deepcopy(valid)
            candidate[collection].append(copy.deepcopy(candidate[collection][0]))
            with self.subTest(collection=collection):
                self.assert_invalid(candidate)

    def test_unknown_project_history_or_node_reference_rejected_atomically(self):
        self.seed()
        valid = self.source.export_backup()
        candidates = []
        project = copy.deepcopy(valid)
        project["histories"][0]["project_id"] = str(uuid4())
        candidates.append(project)
        history = copy.deepcopy(valid)
        linked = next(problem for problem in history["problems"] if problem["history_id"] is not None)
        linked["history_id"] = str(uuid4())
        candidates.append(history)
        node = copy.deepcopy(valid)
        linked = next(problem for problem in node["problems"] if problem["history_id"] is not None)
        linked["node_id"] = "unknown_node"
        candidates.append(node)
        for candidate in candidates:
            self.assert_invalid(candidate)

    def test_bad_format_version_boolean_version_or_timestamp_rejected(self):
        self.seed()
        valid = self.source.export_backup()
        mutations = [("format", "another-format"), ("version", 2), ("version", True),
                     ("created_at", "2026-10-13T04:05:06.000")]
        for key, value in mutations:
            candidate = copy.deepcopy(valid)
            candidate[key] = value
            self.assert_invalid(candidate)
        for collection in ("projects", "histories", "problems"):
            candidate = copy.deepcopy(valid)
            candidate[collection][0]["updated_at"] = "2026-10-13T04:05:06.000"
            self.assert_invalid(candidate)

    def test_raw_json_duplicate_fields_nan_and_invalid_text_rejected(self):
        for text in ('{"format":"mathpath_library_backup","format":"mathpath_library_backup"}',
                     '{"version":NaN}', 'not-json', '{'):
            self.assert_invalid(text)

    def test_restore_revalidates_cross_graph_state_and_task_snapshots(self):
        self.seed(full=True)
        valid = self.source.export_backup()
        node = copy.deepcopy(valid)
        node["histories"][0]["state"]["notes"]["unknown_node"] = "不可引用"
        self.assert_invalid(node)
        snapshot = copy.deepcopy(valid)
        snapshot["histories"][0]["state"]["attempts"][0]["task"]["id"] = "different_task"
        self.assert_invalid(snapshot)

    def test_record_cap_rejected_before_writes(self):
        self.seed()
        candidate = self.source.export_backup()
        template = candidate["projects"][0]
        candidate["projects"] = [{**template, "id": str(uuid4())} for _ in range(5001)]
        self.assert_invalid(candidate)

    def test_restore_rejects_combined_record_limit_atomically(self):
        self.seed()
        self.target.list_projects()
        with closing(sqlite3.connect(self.target.path, isolation_level=None)) as connection:
            connection.execute("BEGIN")
            connection.executemany("INSERT INTO projects(id,title,created_at,updated_at) VALUES (?,?,?,?)",
                                   [(str(uuid4()), "已有项目", TIMESTAMP, TIMESTAMP) for _ in range(5000)])
            connection.commit()
        before = self.unchanged(self.target)
        with self.assertRaises(LibraryError) as caught:
            self.target.restore_backup(self.source.export_backup())
        self.assertEqual(caught.exception.code, "backup_too_large")
        self.assertEqual(self.unchanged(self.target), before)

    def test_backup_byte_cap_applies_to_raw_and_parsed_payload_and_export(self):
        self.seed()
        valid = self.source.export_backup()
        self.assertEqual(library_store.MAX_BACKUP_BYTES, 50 * 1024 * 1024)
        with patch.object(library_store, "MAX_BACKUP_BYTES", 200):
            self.assert_invalid(valid, code="backup_too_large")
            self.assert_invalid(json.dumps(valid), code="backup_too_large")
            with self.assertRaises(LibraryError) as caught:
                self.source.export_backup()
            self.assertEqual(caught.exception.code, "backup_too_large")

    def test_per_history_state_byte_cap_is_retained(self):
        self.seed(full=True)
        backup = self.source.export_backup()
        with patch.object(library_store, "MAX_STATE_BYTES", 200):
            self.assert_invalid(backup, code="state_too_large")

    def test_failure_mid_import_rolls_back_all_records_and_idempotency_marker(self):
        self.seed()
        self.target.create_project("保留项目")
        before = self.unchanged(self.target)
        with closing(sqlite3.connect(self.target.path, isolation_level=None)) as connection:
            connection.execute("""CREATE TRIGGER fail_problem_import BEFORE INSERT ON unresolved_questions
                                  BEGIN SELECT RAISE(ABORT,'synthetic-private-storage-message'); END""")
        backup = self.source.export_backup()
        with self.assertRaises(LibraryError) as caught:
            self.target.restore_backup(backup)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("synthetic-private", str(caught.exception))
        self.assertEqual(self.unchanged(self.target), before)
        self.assertFalse(self.target.preview_backup(backup)["already_restored"])
        with closing(sqlite3.connect(self.target.path, isolation_level=None)) as connection:
            connection.execute("DROP TRIGGER fail_problem_import")
        self.assertFalse(self.target.restore_backup(backup)["already_restored"])

    def test_failure_recording_restore_marker_rolls_back_preceding_inserts(self):
        self.seed()
        self.target.create_project("保留项目")
        before = self.unchanged(self.target)
        with closing(sqlite3.connect(self.target.path, isolation_level=None)) as connection:
            connection.execute("""CREATE TRIGGER fail_marker BEFORE INSERT ON backup_restore_runs
                                  BEGIN SELECT RAISE(ABORT,'synthetic-marker-failure'); END""")
        with self.assertRaises(LibraryError):
            self.target.restore_backup(self.source.export_backup())
        self.assertEqual(self.unchanged(self.target), before)

    def test_explicit_repeat_marker_failure_rolls_back_all_added_records(self):
        self.seed()
        backup = self.source.export_backup()
        self.target.restore_backup(backup)
        before = self.unchanged(self.target)
        with closing(sqlite3.connect(self.target.path, isolation_level=None)) as connection:
            connection.execute("""CREATE TRIGGER fail_repeat_marker BEFORE UPDATE ON backup_restore_runs
                                  BEGIN SELECT RAISE(ABORT,'synthetic-repeat-marker-failure'); END""")
        with self.assertRaises(LibraryError):
            self.target.restore_backup(backup, repeat=True)
        self.assertEqual(self.unchanged(self.target), before)

    def downgrade(self, version):
        with closing(sqlite3.connect(self.source.path, isolation_level=None)) as connection:
            connection.execute("DROP TABLE backup_restore_runs")
            if version == 1:
                connection.execute("DROP TABLE unresolved_questions")
            connection.execute(f"PRAGMA user_version={version}")

    def test_schema_two_preview_is_readonly_then_restore_migrates_without_data_loss(self):
        project, history, _problems = self.seed()
        backup = self.source.export_backup()
        self.downgrade(2)
        bytes_before = self.source.path.read_bytes()
        self.assertFalse(self.source.preview_backup(backup)["already_restored"])
        self.assertEqual(self.source.path.read_bytes(), bytes_before)
        self.source.restore_backup(backup)
        self.assertEqual(self.source.get_history(history["id"]), history)
        self.assertEqual(len(self.source.list_problems(status="all")), 6)
        with closing(sqlite3.connect(self.source.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_schema_one_migration_preserves_old_history_learning_content(self):
        _project, history, _problems = self.seed(full=True)
        self.downgrade(1)
        self.assertEqual(self.source.get_history(history["id"]), history)
        self.assertEqual(self.source.list_problems(status="all"), [])
        self.assertEqual(len(self.source.export_backup()["histories"]), 1)
        with closing(sqlite3.connect(self.source.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_export_never_reads_provider_files_or_adds_internal_database_fields(self):
        self.seed(full=True)
        # Synthetic private files are adjacent but are not backup resources.
        private = self.source.path.parent / "account-token.dpapi"
        private.write_bytes(b"SYNTHETIC_PRIVATE_SENTINEL")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("no file reads")), \
             patch.object(Path, "read_text", side_effect=AssertionError("no file reads")):
            backup = self.source.export_backup()
        text = json.dumps(backup)
        self.assertNotIn("SYNTHETIC_PRIVATE_SENTINEL", text)
        self.assertNotIn("migration_key", text)
        self.assertNotIn("dedupe_key", text)
        self.assertNotIn("backup_restore_runs", text)
        self.assertEqual(set(backup), {"format", "version", "created_at", "projects", "histories", "problems"})
        self.assertIsInstance(BackupEnvelope.model_validate(backup), BackupEnvelope)


if __name__ == "__main__":
    unittest.main()
