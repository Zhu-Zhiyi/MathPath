"""Transactional local project/history library, with no credential reads or model calls."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from graph_builder import KnowledgeGraph
from library_models import (BackupEnvelope, History, HistoryCreate, HistorySummary, HistoryUpdate,
                            IdBatch, LibraryId, Problem, ProblemCreate, ProblemUpdate,
                            Project, ProjectCreate, StudyState)


SCHEMA_VERSION = 3
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_BACKUP_BYTES = 50 * 1024 * 1024
_ID_ADAPTER = TypeAdapter(LibraryId)


class LibraryError(Exception):
    """Only fixed, safe messages leave this boundary."""

    def __init__(self, message: str, *, status_code: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class LibraryNotFound(LibraryError):
    def __init__(self):
        super().__init__("所选项目或历史记录已不存在，请刷新后重试。", status_code=404, code="not_found")


class LibraryConflict(LibraryError):
    def __init__(self):
        super().__init__("这条历史已在其他窗口更新，请重新打开后再保存。", status_code=409, code="revision_conflict")


def _invalid() -> LibraryError:
    return LibraryError("项目或学习记录的格式不正确。", status_code=422, code="invalid_payload")


def _storage_error() -> LibraryError:
    return LibraryError("本机学习记录暂时无法读取或保存，请稍后重试。", status_code=503, code="storage_unavailable")


def _invalid_backup() -> LibraryError:
    return LibraryError("备份格式或学习记录引用不正确，请选择 MathPath 导出的完整备份。",
                        status_code=422, code="invalid_backup")


def _backup_too_large() -> LibraryError:
    return LibraryError("完整备份超过 50 MiB 或记录数量上限，请先减少学习记录。",
                        status_code=413, code="backup_too_large")


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _backup_json(value) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise _invalid_backup() from None
    if len(encoded) > MAX_BACKUP_BYTES:
        raise _backup_too_large()
    return encoded


def _validated_backup(payload) -> tuple[BackupEnvelope, str]:
    if isinstance(payload, BackupEnvelope):
        # Revalidate even model instances; model_construct must not bypass the
        # learning-only allowlist or relationship checks at a storage boundary.
        payload = payload.model_dump(mode="json")
    if isinstance(payload, (bytes, str)):
        try:
            raw = payload.encode("utf-8") if isinstance(payload, str) else payload
            if len(raw) > MAX_BACKUP_BYTES:
                raise _backup_too_large()
            payload = json.loads(raw, object_pairs_hook=_strict_object,
                                 parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            raise _invalid_backup() from None
    _backup_json(payload)
    try:
        envelope = BackupEnvelope.model_validate(payload)
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise _invalid_backup() from None
    for history in envelope.histories:
        _encode_state(history.state)
    canonical = envelope.model_dump(mode="json")
    # File whitespace, key order and list order do not turn one backup into
    # multiple imports. Export time and all actual learning content are included.
    for collection in ("projects", "histories", "problems"):
        canonical[collection].sort(key=lambda record: record["id"])
    digest = hashlib.sha256(_backup_json(canonical)).hexdigest()
    return envelope, digest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validated_id(value) -> str:
    try:
        return _ID_ADAPTER.validate_python(value, strict=True)
    except ValidationError:
        raise _invalid() from None


def _validated_batch(values) -> list[str]:
    try:
        return IdBatch(ids=values).ids
    except ValidationError:
        raise _invalid() from None


def _encode_state(state: StudyState) -> str:
    value = state.model_dump_json()
    if len(value.encode("utf-8")) > MAX_STATE_BYTES:
        raise LibraryError("这条学习记录过大，请减少作答或笔记后再保存。", status_code=413, code="state_too_large")
    return value


def _graph_identity(graph: KnowledgeGraph) -> str:
    value = graph.model_dump(mode="json")
    value["nodes"] = [
        {**node, "prerequisite_sets": sorted(sorted(group) for group in node["prerequisite_sets"])}
        for node in sorted(value["nodes"], key=lambda node: node["id"])
    ]
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _counts(graph: KnowledgeGraph, state: StudyState) -> tuple[int, int, int, int]:
    return (len(graph.nodes), len(state.lessons), len(state.attempts),
            sum(item.definition and item.intuition and item.application for item in state.mastery.values()))


def default_library_path() -> Path:
    configured = os.environ.get("MATHPATH_DATA_DIR")
    base = Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parent
    return base / ".mathpath" / "library.sqlite3"


class LibraryStore:
    """A new connection per operation; SQLite serializes the small write transactions."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else default_library_path()

    def _initialize(self, connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version not in (0, 1, 2):
            raise _storage_error()
        connection.execute("BEGIN IMMEDIATE")
        try:
            # Another thread may have initialized while this thread waited.
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == SCHEMA_VERSION:
                connection.commit()
                return
            if version not in (0, 1, 2):
                raise _storage_error()
            if version == 0 and connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                raise _storage_error()
            if version in (1, 2):
                # Refuse unrelated databases with coincidentally matching versions.
                names = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"projects", "histories"} <= names or "backup_restore_runs" in names:
                    raise _storage_error()
                if (version == 1 and "unresolved_questions" in names) or (version == 2 and "unresolved_questions" not in names):
                    raise _storage_error()
                columns = {row[1] for row in connection.execute("PRAGMA table_info(histories)")}
                expected = {"id", "title", "goal", "project_id", "graph_json", "state_json", "revision",
                            "created_at", "updated_at", "node_count", "lesson_count", "attempt_count", "mastered_count", "migration_key"}
                project_columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
                if not expected <= columns or not {"id", "title", "created_at", "updated_at"} <= project_columns:
                    raise _storage_error()
                if version == 2:
                    problem_columns = {row[1] for row in connection.execute("PRAGMA table_info(unresolved_questions)")}
                    expected_problems = set(Problem.model_fields) | {"dedupe_key"}
                    if not expected_problems <= problem_columns:
                        raise _storage_error()
            else:
                self._create_library_tables(connection)
            if version in (0, 1):
                self._create_problem_table(connection)
            connection.execute("""CREATE TABLE backup_restore_runs (
                digest TEXT PRIMARY KEY CHECK(length(digest)=64),
                imported_at TEXT NOT NULL,
                project_count INTEGER NOT NULL CHECK(project_count >= 0),
                history_count INTEGER NOT NULL CHECK(history_count >= 0),
                problem_count INTEGER NOT NULL CHECK(problem_count >= 0))""")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @staticmethod
    def _create_problem_table(connection: sqlite3.Connection) -> None:
        connection.execute("""CREATE TABLE unresolved_questions (
                id TEXT PRIMARY KEY,
                history_id TEXT REFERENCES histories(id) ON DELETE SET NULL,
                node_id TEXT, goal TEXT NOT NULL, node_label TEXT NOT NULL,
                question TEXT NOT NULL, response TEXT NOT NULL,
                reason TEXT NOT NULL CHECK(reason IN ('model_failure','uncertain','user_marked')),
                status TEXT NOT NULL CHECK(status IN ('open','resolved')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                dedupe_key TEXT NOT NULL)""")
        connection.execute("CREATE INDEX problem_updated ON unresolved_questions(status,updated_at DESC)")
        # Stable identity survives deletion of its original history. A UNIQUE
        # expression on current nullable history_id would block FK SET NULL
        # when different histories had the same question.
        connection.execute("CREATE UNIQUE INDEX problem_open_identity ON unresolved_questions(dedupe_key) WHERE status='open'")

    @staticmethod
    def _create_library_tables(connection: sqlite3.Connection) -> None:
        connection.execute("""CREATE TABLE projects (
            id TEXT PRIMARY KEY, title TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        connection.execute("""CREATE TABLE histories (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, goal TEXT NOT NULL,
            project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
            graph_json TEXT NOT NULL, state_json TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            node_count INTEGER NOT NULL, lesson_count INTEGER NOT NULL,
            attempt_count INTEGER NOT NULL, mastered_count INTEGER NOT NULL,
            migration_key TEXT UNIQUE)""")
        connection.execute("CREATE INDEX history_project_updated ON histories(project_id, updated_at DESC)")
        connection.execute("CREATE INDEX history_updated ON histories(updated_at DESC)")

    @contextmanager
    def _connection(self, *, write=False):
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            self._initialize(connection)
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except (sqlite3.Error, OSError):
            if connection is not None:
                connection.rollback()
            raise _storage_error() from None
        except BaseException:
            if connection is not None and write:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _project(row: sqlite3.Row) -> dict:
        try:
            return Project.model_validate(dict(row)).model_dump(mode="json")
        except ValidationError:
            raise _storage_error() from None

    @staticmethod
    def _history(row: sqlite3.Row) -> dict:
        try:
            if len(row["state_json"].encode("utf-8")) > MAX_STATE_BYTES:
                raise ValueError
            graph = KnowledgeGraph.model_validate_json(row["graph_json"])
            state = StudyState.model_validate_json(row["state_json"])
            return History(id=row["id"], title=row["title"], goal=row["goal"], project_id=row["project_id"],
                           graph=graph, state=state, revision=row["revision"],
                           created_at=row["created_at"], updated_at=row["updated_at"]).model_dump(mode="json")
        except (ValidationError, ValueError, AttributeError, TypeError):
            raise _storage_error() from None

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict:
        try:
            keys = HistorySummary.model_fields
            return HistorySummary.model_validate({key: row[key] for key in keys}).model_dump(mode="json")
        except (ValidationError, KeyError, IndexError):
            raise _storage_error() from None

    @staticmethod
    def _require_ids(connection: sqlite3.Connection, table: str, ids: list[str]) -> None:
        # table comes exclusively from a fixed literal at the call sites.
        placeholders = ",".join("?" for _ in ids)
        rows = connection.execute(f"SELECT id FROM {table} WHERE id IN ({placeholders})", ids).fetchall()
        if {row["id"] for row in rows} != set(ids):
            raise LibraryNotFound()

    @staticmethod
    def _require_project(connection: sqlite3.Connection, project_id: str | None) -> None:
        if project_id is not None and connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
            raise LibraryNotFound()

    def list_projects(self) -> list[dict]:
        with self._connection() as connection:
            return [self._project(row) for row in connection.execute(
                "SELECT id,title,created_at,updated_at FROM projects ORDER BY updated_at DESC,id").fetchall()]

    def create_project(self, title: str) -> dict:
        try:
            title = ProjectCreate(title=title).title
        except ValidationError:
            raise _invalid() from None
        record = {"id": str(uuid4()), "title": title, "created_at": _now(), "updated_at": _now()}
        with self._connection(write=True) as connection:
            connection.execute("INSERT INTO projects(id,title,created_at,updated_at) VALUES (?,?,?,?)",
                               (record["id"], title, record["created_at"], record["updated_at"]))
        return record

    def rename_project(self, project_id: str, title: str) -> dict:
        project_id = _validated_id(project_id)
        try:
            title = ProjectCreate(title=title).title
        except ValidationError:
            raise _invalid() from None
        with self._connection(write=True) as connection:
            self._require_project(connection, project_id)
            connection.execute("UPDATE projects SET title=?,updated_at=? WHERE id=?", (title, _now(), project_id))
            return self._project(connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    def delete_projects(self, ids: list[str]) -> dict:
        ids = _validated_batch(ids)
        placeholders = ",".join("?" for _ in ids)
        with self._connection(write=True) as connection:
            self._require_ids(connection, "projects", ids)
            # Update revisions so a stale page cannot restore a deleted assignment.
            connection.execute(f"UPDATE histories SET project_id=NULL,revision=revision+1,updated_at=? WHERE project_id IN ({placeholders})",
                               [_now(), *ids])
            connection.execute(f"DELETE FROM projects WHERE id IN ({placeholders})", ids)
        return {"deleted_ids": ids}

    def list_histories(self, project_id: str | None = None, *, uncategorized: bool = False, query: str = "",
                       limit: int = 100, offset: int = 0) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0 or type(uncategorized) is not bool:
            raise _invalid()
        if project_id is not None:
            project_id = _validated_id(project_id)
        if uncategorized and project_id is not None:
            raise _invalid()
        if type(query) is not str or len(query) > 500:
            raise _invalid()
        conditions, arguments = [], []
        if project_id is not None:
            conditions.append("project_id=?")
            arguments.append(project_id)
        elif uncategorized:
            conditions.append("project_id IS NULL")
        if query.strip():
            # LIKE metacharacters must search literally; no wildcard injection.
            literal = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("(title LIKE ? ESCAPE '\\' OR goal LIKE ? ESCAPE '\\')")
            arguments.extend(["%" + literal + "%"] * 2)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self._connection() as connection:
            self._require_project(connection, project_id)
            columns = ",".join(HistorySummary.model_fields)
            rows = connection.execute("SELECT " + columns + " FROM histories" + where + " ORDER BY updated_at DESC,id LIMIT ? OFFSET ?",
                                      [*arguments, limit, offset]).fetchall()
            return [self._summary(row) for row in rows]

    def create_history(self, *, title: str, goal: str, graph: KnowledgeGraph | dict,
                       state: StudyState | dict | None = None, project_id: str | None = None,
                       migration_key: str | None = None) -> dict:
        try:
            payload = HistoryCreate(title=title, goal=goal, graph=graph,
                                    state=state if state is not None else StudyState(),
                                    project_id=project_id, migration_key=migration_key)
        except ValidationError:
            raise _invalid() from None
        state_json = _encode_state(payload.state)
        history_id, timestamp = str(uuid4()), _now()
        with self._connection(write=True) as connection:
            if migration_key is not None:
                existing = connection.execute("SELECT * FROM histories WHERE migration_key=?", (migration_key,)).fetchone()
                if existing is not None:
                    return self._history(existing)
            self._require_project(connection, payload.project_id)
            connection.execute("""INSERT INTO histories (
                id,title,goal,project_id,graph_json,state_json,revision,created_at,updated_at,
                node_count,lesson_count,attempt_count,mastered_count,migration_key)
                VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?)""",
                (history_id, payload.title, payload.goal, payload.project_id,
                 payload.graph.model_dump_json(), state_json, timestamp, timestamp,
                 *_counts(payload.graph, payload.state), migration_key))
            return self._history(connection.execute("SELECT * FROM histories WHERE id=?", (history_id,)).fetchone())

    def get_history(self, history_id: str) -> dict:
        history_id = _validated_id(history_id)
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM histories WHERE id=?", (history_id,)).fetchone()
            if row is None:
                raise LibraryNotFound()
            return self._history(row)

    def update_history(self, history_id: str, payload: HistoryUpdate | dict | None = None, **changes) -> dict:
        history_id = _validated_id(history_id)
        if payload is not None and changes:
            raise _invalid()
        try:
            patch = payload if isinstance(payload, HistoryUpdate) else HistoryUpdate.model_validate(payload if payload is not None else changes)
        except (ValidationError, TypeError):
            raise _invalid() from None
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT * FROM histories WHERE id=?", (history_id,)).fetchone()
            if row is None:
                raise LibraryNotFound()
            if row["revision"] != patch.expected_revision:
                raise LibraryConflict()
            current = History.model_validate(self._history(row))
            fields = patch.model_fields_set
            graph = patch.graph if "graph" in fields else current.graph
            graph_changed = "graph" in fields and _graph_identity(graph) != _graph_identity(current.graph)
            # Replacing a graph without its state starts fresh. Matching ID names
            # alone do not prove old lessons, answers or mastery remain applicable.
            state = patch.state if "state" in fields else (StudyState() if graph_changed else current.state)
            try:
                state.validate_graph(graph)
            except ValueError:
                raise _invalid() from None
            state_json = _encode_state(state)
            project_id = patch.project_id if "project_id" in fields else current.project_id
            self._require_project(connection, project_id)
            title = patch.title if "title" in fields else current.title
            goal = patch.goal if "goal" in fields else current.goal
            connection.execute("""UPDATE histories SET title=?,goal=?,project_id=?,graph_json=?,state_json=?,
                revision=revision+1,updated_at=?,node_count=?,lesson_count=?,attempt_count=?,mastered_count=? WHERE id=?""",
                (title, goal, project_id, graph.model_dump_json(), state_json, _now(), *_counts(graph, state), history_id))
            if graph_changed:
                # A snapshot keeps its original wording when labels change.
                # Only a removed node loses its history link; its question and
                # mathematical context still survive as an independent record.
                node_ids = [node.id for node in graph.nodes]
                placeholders = ",".join("?" for _ in node_ids)
                connection.execute(f"""UPDATE unresolved_questions SET history_id=NULL
                    WHERE history_id=? AND node_id IS NOT NULL AND node_id NOT IN ({placeholders})""",
                    [history_id, *node_ids])
            return self._history(connection.execute("SELECT * FROM histories WHERE id=?", (history_id,)).fetchone())

    def delete_histories(self, ids: list[str]) -> dict:
        ids = _validated_batch(ids)
        placeholders = ",".join("?" for _ in ids)
        with self._connection(write=True) as connection:
            self._require_ids(connection, "histories", ids)
            connection.execute(f"DELETE FROM histories WHERE id IN ({placeholders})", ids)
        return {"deleted_ids": ids}

    def move_histories(self, ids: list[str], project_id: str | None) -> dict:
        ids = _validated_batch(ids)
        if project_id is not None:
            project_id = _validated_id(project_id)
        placeholders = ",".join("?" for _ in ids)
        with self._connection(write=True) as connection:
            self._require_ids(connection, "histories", ids)
            self._require_project(connection, project_id)
            connection.execute(f"UPDATE histories SET project_id=?,revision=revision+1,updated_at=? WHERE id IN ({placeholders})",
                               [project_id, _now(), *ids])
        return {"moved_ids": ids, "project_id": project_id}

    @staticmethod
    def _problem(row: sqlite3.Row) -> dict:
        try:
            # Only the public learning snapshot is returned. Internal database
            # identities and other local configuration never leave this boundary.
            return Problem.model_validate({key: row[key] for key in Problem.model_fields}).model_dump(mode="json")
        except (ValidationError, KeyError, IndexError):
            raise _storage_error() from None

    def list_problems(self, *, status: str = "open", query: str = "", limit: int = 100, offset: int = 0) -> list[dict]:
        if status not in ("open", "resolved", "all") or type(status) is not str:
            raise _invalid()
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise _invalid()
        if type(query) is not str or len(query) > 500:
            raise _invalid()
        conditions, arguments = [], []
        if status != "all":
            conditions.append("status=?")
            arguments.append(status)
        if query.strip():
            literal = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("(question LIKE ? ESCAPE '\\' OR goal LIKE ? ESCAPE '\\' OR node_label LIKE ? ESCAPE '\\')")
            arguments.extend(["%" + literal + "%"] * 3)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM unresolved_questions" + where +
                                      " ORDER BY updated_at DESC,id LIMIT ? OFFSET ?", [*arguments, limit, offset]).fetchall()
            return [self._problem(row) for row in rows]

    def create_problem(self, **payload) -> dict:
        try:
            value = ProblemCreate.model_validate(payload)
        except ValidationError:
            raise _invalid() from None
        with self._connection(write=True) as connection:
            if value.history_id is not None:
                history = connection.execute("SELECT goal,graph_json FROM histories WHERE id=?", (value.history_id,)).fetchone()
                if history is None:
                    raise LibraryNotFound()
                try:
                    graph = KnowledgeGraph.model_validate_json(history["graph_json"])
                except ValidationError:
                    raise _storage_error() from None
                label = ""
                if value.node_id is not None:
                    node = next((node for node in graph.nodes if node.id == value.node_id), None)
                    if node is None:
                        raise _invalid()
                    label = node.label
                # Saved context is authoritative; caller snapshots are only used
                # when there is no associated history yet.
                value = value.model_copy(update={"goal": history["goal"], "node_label": label})
            identity = json.dumps([value.history_id, value.node_id, value.goal, value.node_label, value.question],
                                  ensure_ascii=False, separators=(",", ":"))
            dedupe_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            existing = connection.execute("SELECT * FROM unresolved_questions WHERE dedupe_key=? AND status='open'",
                                          (dedupe_key,)).fetchone()
            if existing is not None:
                self._problem(existing)
                # Retrying an uncertain response or marking it manually should
                # retain one open question rather than produce duplicates.
                priority = {"model_failure": 0, "uncertain": 1, "user_marked": 2}
                reason = value.reason if priority[value.reason] > priority[existing["reason"]] else existing["reason"]
                response = value.response if value.response.strip() else existing["response"]
                if reason != existing["reason"] or response != existing["response"]:
                    connection.execute("UPDATE unresolved_questions SET response=?,reason=?,updated_at=? WHERE id=?",
                                       (response, reason, _now(), existing["id"]))
                return self._problem(connection.execute("SELECT * FROM unresolved_questions WHERE id=?",
                                                        (existing["id"],)).fetchone())
            problem_id, timestamp = str(uuid4()), _now()
            connection.execute("""INSERT INTO unresolved_questions
                (id,history_id,node_id,goal,node_label,question,response,reason,status,created_at,updated_at,dedupe_key)
                VALUES (?,?,?,?,?,?,?,?,'open',?,?,?)""",
                (problem_id, value.history_id, value.node_id, value.goal, value.node_label, value.question,
                 value.response, value.reason, timestamp, timestamp, dedupe_key))
            return self._problem(connection.execute("SELECT * FROM unresolved_questions WHERE id=?", (problem_id,)).fetchone())

    def get_problem(self, problem_id: str) -> dict:
        problem_id = _validated_id(problem_id)
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM unresolved_questions WHERE id=?", (problem_id,)).fetchone()
            if row is None:
                raise LibraryNotFound()
            return self._problem(row)

    def update_problem(self, problem_id: str, status: str) -> dict:
        problem_id = _validated_id(problem_id)
        try:
            status = ProblemUpdate(status=status).status
        except ValidationError:
            raise _invalid() from None
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT * FROM unresolved_questions WHERE id=?", (problem_id,)).fetchone()
            if row is None:
                raise LibraryNotFound()
            if row["status"] != status:
                if status == "open" and connection.execute(
                        "SELECT 1 FROM unresolved_questions WHERE dedupe_key=? AND status='open' AND id!=?",
                        (row["dedupe_key"], problem_id)).fetchone() is not None:
                    raise LibraryError("同一个问题已有未解决记录，请先处理那条记录。", status_code=409, code="problem_already_open")
                connection.execute("UPDATE unresolved_questions SET status=?,updated_at=? WHERE id=?", (status, _now(), problem_id))
            return self._problem(connection.execute("SELECT * FROM unresolved_questions WHERE id=?", (problem_id,)).fetchone())

    def delete_problems(self, ids: list[str]) -> dict:
        ids = _validated_batch(ids)
        placeholders = ",".join("?" for _ in ids)
        with self._connection(write=True) as connection:
            self._require_ids(connection, "unresolved_questions", ids)
            connection.execute(f"DELETE FROM unresolved_questions WHERE id IN ({placeholders})", ids)
        return {"deleted_ids": ids}

    @staticmethod
    def _backup_counts(envelope: BackupEnvelope, *, already_restored: bool) -> dict:
        return {"projects": len(envelope.projects), "histories": len(envelope.histories),
                "problems": len(envelope.problems), "already_restored": already_restored}

    def _has_restored_readonly(self, digest: str) -> bool:
        """Preview must not create the library or migrate an existing schema."""
        if not self.path.exists():
            return False
        connection = None
        try:
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True,
                                         timeout=10, isolation_level=None)
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backup_restore_runs'").fetchone()
            if table is None:
                return False
            return connection.execute("SELECT 1 FROM backup_restore_runs WHERE digest=?", (digest,)).fetchone() is not None
        except (sqlite3.Error, OSError):
            raise _storage_error() from None
        finally:
            if connection is not None:
                connection.close()

    def export_backup(self) -> dict:
        """Read a consistent complete library, without pagination or account data."""
        payload = {"format": "mathpath_library_backup", "version": 1, "created_at": _now(),
                   "projects": [], "histories": [], "problems": []}
        queries = (("projects", "projects", 5000,
                    "SELECT id,title,created_at,updated_at FROM projects ORDER BY id", self._project),
                   ("histories", "histories", 5000, "SELECT * FROM histories ORDER BY id", self._history),
                   ("problems", "unresolved_questions", 10000,
                    "SELECT * FROM unresolved_questions ORDER BY id", self._problem))
        size = len(_backup_json(payload))
        with self._connection() as connection:
            connection.execute("BEGIN")
            for key, table, maximum, query, convert in queries:
                if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > maximum:
                    raise _backup_too_large()
                # Iterate rows so an oversized library is rejected before loading
                # thousands of near-limit histories into memory.
                for row in connection.execute(query):
                    record = convert(row)
                    size += len(_backup_json(record)) + 1
                    if size > MAX_BACKUP_BYTES:
                        raise _backup_too_large()
                    payload[key].append(record)
        try:
            envelope, _digest = _validated_backup(payload)
        except LibraryError as error:
            if error.code == "invalid_backup":
                raise _storage_error() from None
            raise
        return envelope.model_dump(mode="json")

    def preview_backup(self, payload) -> dict:
        envelope, digest = _validated_backup(payload)
        return self._backup_counts(envelope, already_restored=self._has_restored_readonly(digest))

    def restore_backup(self, payload, *, repeat: bool = False) -> dict:
        """Atomically append a validated backup using fresh record identities."""
        if type(repeat) is not bool:
            raise _invalid()
        envelope, digest = _validated_backup(payload)
        import_run_id = str(uuid4())
        project_ids = {record.id: str(uuid4()) for record in envelope.projects}
        history_ids = {record.id: str(uuid4()) for record in envelope.histories}
        with self._connection(write=True) as connection:
            if not repeat and connection.execute("SELECT 1 FROM backup_restore_runs WHERE digest=?", (digest,)).fetchone() is not None:
                return self._backup_counts(envelope, already_restored=True)
            for table, records, maximum in (("projects", envelope.projects, 5000),
                                             ("histories", envelope.histories, 5000),
                                             ("unresolved_questions", envelope.problems, 10000)):
                if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] + len(records) > maximum:
                    raise _backup_too_large()
            for project in envelope.projects:
                connection.execute("INSERT INTO projects(id,title,created_at,updated_at) VALUES (?,?,?,?)",
                                   (project_ids[project.id], project.title, project.created_at, project.updated_at))
            for history in envelope.histories:
                connection.execute("""INSERT INTO histories (
                    id,title,goal,project_id,graph_json,state_json,revision,created_at,updated_at,
                    node_count,lesson_count,attempt_count,mastered_count,migration_key)
                    VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,NULL)""",
                    (history_ids[history.id], history.title, history.goal,
                     project_ids[history.project_id] if history.project_id is not None else None,
                     history.graph.model_dump_json(), _encode_state(history.state),
                     history.created_at, history.updated_at, *_counts(history.graph, history.state)))
            for problem in envelope.problems:
                history_id = history_ids[problem.history_id] if problem.history_id is not None else None
                if history_id is not None:
                    # New questions in a restored history can still merge with
                    # an existing open question through the ordinary API.
                    identity = [history_id, problem.node_id, problem.goal, problem.node_label, problem.question]
                else:
                    # Distinct snapshots from two deleted histories may now have
                    # identical visible text. Their original IDs distinguish them.
                    identity = ["restored_unlinked_problem", import_run_id, problem.id]
                dedupe_key = hashlib.sha256(json.dumps(identity, ensure_ascii=False,
                                                       separators=(",", ":")).encode("utf-8")).hexdigest()
                connection.execute("""INSERT INTO unresolved_questions
                    (id,history_id,node_id,goal,node_label,question,response,reason,status,created_at,updated_at,dedupe_key)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid4()), history_id, problem.node_id, problem.goal, problem.node_label, problem.question,
                     problem.response, problem.reason, problem.status, problem.created_at, problem.updated_at, dedupe_key))
            connection.execute("""INSERT INTO backup_restore_runs
                (digest,imported_at,project_count,history_count,problem_count) VALUES (?,?,?,?,?)
                ON CONFLICT(digest) DO UPDATE SET imported_at=excluded.imported_at,
                    project_count=excluded.project_count,history_count=excluded.history_count,
                    problem_count=excluded.problem_count""",
                (digest, _now(), len(envelope.projects), len(envelope.histories), len(envelope.problems)))
        return self._backup_counts(envelope, already_restored=False)


# Runtime callers can use these functions; data location is resolved lazily so
# offline test overrides and desktop startup configure it before any DB access.
def list_projects():
    return LibraryStore().list_projects()


def create_project(title):
    return LibraryStore().create_project(title)


def rename_project(project_id, title):
    return LibraryStore().rename_project(project_id, title)


def delete_projects(ids):
    return LibraryStore().delete_projects(ids)


def list_histories(project_id=None, *, uncategorized=False, query="", limit=100, offset=0):
    return LibraryStore().list_histories(project_id, uncategorized=uncategorized, query=query, limit=limit, offset=offset)


def create_history(**payload):
    return LibraryStore().create_history(**payload)


def get_history(history_id):
    return LibraryStore().get_history(history_id)


def update_history(history_id, payload=None, **changes):
    return LibraryStore().update_history(history_id, payload, **changes)


def delete_histories(ids):
    return LibraryStore().delete_histories(ids)


def move_histories(ids, project_id):
    return LibraryStore().move_histories(ids, project_id)


def list_problems(*, status="open", query="", limit=100, offset=0):
    return LibraryStore().list_problems(status=status, query=query, limit=limit, offset=offset)


def create_problem(**payload):
    return LibraryStore().create_problem(**payload)


def get_problem(problem_id):
    return LibraryStore().get_problem(problem_id)


def update_problem(problem_id, status):
    return LibraryStore().update_problem(problem_id, status)


def delete_problems(ids):
    return LibraryStore().delete_problems(ids)


def export_backup():
    return LibraryStore().export_backup()


def preview_backup(payload):
    return LibraryStore().preview_backup(payload)


def restore_backup(payload, *, repeat=False):
    return LibraryStore().restore_backup(payload, repeat=repeat)
