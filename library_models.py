"""Strict local library payloads; account and provider settings are never part of them."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from graph_builder import KnowledgeGraph, NodeId, StudyTask
from lesson_builder import Lesson
from study_builder import Feedback as AttemptFeedback, FeedbackStep
from teaching_help import ChatTurn


LibraryId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
TaskId = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_:.-]+$")]
Timestamp = Annotated[str, Field(min_length=20, max_length=40)]
AnswerText = Annotated[str, Field(max_length=6000)]


def valid_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
    except (ValueError, OverflowError):
        raise ValueError("时间必须是带时区的 ISO 8601 格式") from None
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Mastery(StrictModel):
    definition: bool = False
    intuition: bool = False
    application: bool = False


class StudyAttempt(StrictModel):
    id: LibraryId
    node_id: NodeId
    task_id: TaskId
    answer: AnswerText
    feedback: AttemptFeedback | None = None
    hint_level: int = Field(default=0, ge=0, le=3)
    attempt_type: Literal["diagnostic", "guided", "independent", "retrieval", "mixed", "final", "exercise", "followup"]
    outcome: Literal["independent", "hinted", "incorrect", "viewed", "ungraded"] = "ungraded"
    created_at: Timestamp
    task: StudyTask | None = None

    _timestamp = field_validator("created_at")(valid_timestamp)

    @model_validator(mode="after")
    def feedback_matches_task(self):
        if self.task is not None and (self.task.node_id != self.node_id or self.task.id != self.task_id):
            raise ValueError("作答快照必须对应同一知识点和题目")
        if self.feedback is not None and (self.feedback.node_id != self.node_id or self.feedback.task_id != self.task_id):
            raise ValueError("反馈必须对应同一知识点和题目")
        if self.outcome == "independent":
            if self.hint_level != 0:
                raise ValueError("使用了提示的作答不能记为独立完成")
            if self.feedback is not None and (self.feedback.review_required or self.feedback.outcome != "correct"):
                raise ValueError("待核对或未答对的反馈不能记为独立完成")
        return self


class ReviewSchedule(StrictModel):
    due_at: Timestamp
    last_attempt_at: Timestamp | None = None
    interval_days: int = Field(default=1, ge=0, le=3650)
    streak: int = Field(default=0, ge=0, le=100000)

    _due_timestamp = field_validator("due_at")(valid_timestamp)

    @field_validator("last_attempt_at")
    @classmethod
    def optional_timestamp(cls, value):
        return valid_timestamp(value) if value is not None else None


class StudyState(StrictModel):
    version: Literal[1] = 1
    mastery: dict[NodeId, Mastery] = Field(default_factory=dict, max_length=12)
    lessons: dict[NodeId, Lesson] = Field(default_factory=dict, max_length=12)
    notes: dict[NodeId, AnswerText] = Field(default_factory=dict, max_length=12)
    attempts: list[StudyAttempt] = Field(default_factory=list, max_length=500)
    chat_turns: list[ChatTurn] = Field(default_factory=list, max_length=100)
    reviews: dict[NodeId, ReviewSchedule] = Field(default_factory=dict, max_length=12)
    study_mode: Literal["intuition", "application", "proof", "repair"] = "intuition"
    graph_source: Literal["example", "generated"] = "generated"
    diagnostic_answers: dict[TaskId, AnswerText] = Field(default_factory=dict, max_length=24)
    final_answers: dict[TaskId, AnswerText] = Field(default_factory=dict, max_length=24)
    active_node_id: NodeId | None = None
    view: Literal["graph", "list"] = "graph"

    @model_validator(mode="after")
    def unique_attempt_ids(self):
        if len({attempt.id for attempt in self.attempts}) != len(self.attempts):
            raise ValueError("作答记录 ID 必须唯一")
        if len({turn.id for turn in self.chat_turns}) != len(self.chat_turns):
            raise ValueError("问答记录 ID 必须唯一")
        for node_id, lesson in self.lessons.items():
            if node_id != lesson.node_id:
                raise ValueError("学习卡必须对应其所在知识点")
        return self

    def validate_graph(self, graph: KnowledgeGraph) -> None:
        node_ids = {node.id for node in graph.nodes}
        referenced = set(self.mastery) | set(self.lessons) | set(self.notes) | set(self.reviews)
        referenced.update(attempt.node_id for attempt in self.attempts)
        referenced.update(turn.node_id for turn in self.chat_turns if turn.node_id is not None)
        if self.active_node_id is not None:
            referenced.add(self.active_node_id)
        if not referenced <= node_ids:
            raise ValueError("学习记录引用了当前地图之外的知识点")
        if graph.study_plan is not None:
            context = graph.study_plan.math_context
            if any(lesson.math_context and lesson.math_context != context for lesson in self.lessons.values()):
                raise ValueError("学习卡的数学约定与当前地图不一致")


class ProjectCreate(StrictModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("名称必须为非空的一行文本")
        return cleaned


class ProjectRename(ProjectCreate):
    pass


class Project(ProjectCreate):
    id: LibraryId
    created_at: Timestamp
    updated_at: Timestamp


class IdBatch(StrictModel):
    ids: list[LibraryId] = Field(min_length=1, max_length=200)

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("不能重复选择同一记录")
        return value


class HistoryMove(IdBatch):
    project_id: LibraryId | None = None


class HistoryCreate(ProjectCreate):
    goal: str = Field(max_length=5000)
    project_id: LibraryId | None = None
    graph: KnowledgeGraph
    state: StudyState = Field(default_factory=StudyState)
    migration_key: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9:_-]+$")

    @model_validator(mode="after")
    def matching_state(self):
        self.state.validate_graph(self.graph)
        return self


class HistoryUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=5000)
    project_id: LibraryId | None = None
    graph: KnowledgeGraph | None = None
    state: StudyState | None = None

    @model_validator(mode="after")
    def patch_fields(self):
        fields = self.model_fields_set - {"expected_revision"}
        if not fields:
            raise ValueError("至少需要修改一项内容")
        for field in fields - {"project_id"}:
            if getattr(self, field) is None:
                raise ValueError("内容字段不能设为 null")
        if self.title is not None:
            self.title = ProjectCreate(title=self.title).title
        if self.graph is not None and self.state is not None:
            self.state.validate_graph(self.graph)
        return self


class History(StrictModel):
    id: LibraryId
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(max_length=5000)
    project_id: LibraryId | None
    graph: KnowledgeGraph
    state: StudyState
    revision: int = Field(ge=1)
    created_at: Timestamp
    updated_at: Timestamp

    @model_validator(mode="after")
    def matching_state(self):
        self.state.validate_graph(self.graph)
        return self


class HistorySummary(StrictModel):
    id: LibraryId
    title: str
    goal: str
    project_id: LibraryId | None
    revision: int
    created_at: Timestamp
    updated_at: Timestamp
    node_count: int
    lesson_count: int
    attempt_count: int
    mastered_count: int


class ProblemCreate(StrictModel):
    """Only learning snapshots belong in the unresolved-question collection."""

    history_id: LibraryId | None = None
    node_id: NodeId | None = None
    goal: str = Field(default="", max_length=5000)
    node_label: str = Field(default="", max_length=300)
    question: str = Field(min_length=1, max_length=6000)
    response: str = Field(default="", max_length=6000)
    reason: Literal["model_failure", "uncertain", "user_marked"] = "user_marked"

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("未解决的问题不能为空")
        return cleaned

    @model_validator(mode="after")
    def snapshot_for_unsaved_node(self):
        if self.history_id is None and self.node_id is not None and not self.node_label.strip():
            raise ValueError("未保存地图的知识点问题需要保留名称")
        return self


class Problem(ProblemCreate):
    id: LibraryId
    status: Literal["open", "resolved"]
    created_at: Timestamp
    updated_at: Timestamp

    _created_timestamp = field_validator("created_at")(valid_timestamp)
    _updated_timestamp = field_validator("updated_at")(valid_timestamp)


class ProblemUpdate(StrictModel):
    status: Literal["open", "resolved"]


class BackupProject(Project):
    _created_timestamp = field_validator("created_at")(valid_timestamp)
    _updated_timestamp = field_validator("updated_at")(valid_timestamp)


class BackupHistory(History):
    _created_timestamp = field_validator("created_at")(valid_timestamp)
    _updated_timestamp = field_validator("updated_at")(valid_timestamp)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        return ProjectCreate(title=value).title


class BackupEnvelope(StrictModel):
    """An explicit learning-only interchange format, independent of account settings."""

    format: Literal["mathpath_library_backup"]
    version: Literal[1]
    created_at: Timestamp
    projects: list[BackupProject] = Field(max_length=5000)
    histories: list[BackupHistory] = Field(max_length=5000)
    problems: list[Problem] = Field(max_length=10000)

    _created_timestamp = field_validator("created_at")(valid_timestamp)

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("备份格式版本不受支持")
        return value

    @model_validator(mode="after")
    def complete_references(self):
        for records in (self.projects, self.histories, self.problems):
            if len({record.id for record in records}) != len(records):
                raise ValueError("备份中的同类记录 ID 必须唯一")
        project_ids = {project.id for project in self.projects}
        histories = {history.id: history for history in self.histories}
        if any(history.project_id is not None and history.project_id not in project_ids
               for history in self.histories):
            raise ValueError("备份历史引用了不存在的项目")
        open_identities = set()
        for problem in self.problems:
            if problem.history_id is None:
                # Deleting a history deliberately leaves independent snapshots.
                continue
            history = histories.get(problem.history_id)
            if history is None:
                raise ValueError("备份问题引用了不存在的历史")
            if problem.node_id is not None and problem.node_id not in {node.id for node in history.graph.nodes}:
                raise ValueError("备份问题引用了历史之外的知识点")
            if problem.status == "open":
                identity = (problem.history_id, problem.node_id, problem.goal, problem.node_label, problem.question)
                if identity in open_identities:
                    raise ValueError("同一历史中的未解决问题不能重复")
                open_identities.add(identity)
        return self
