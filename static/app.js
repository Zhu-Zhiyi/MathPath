"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const STORAGE_KEY = "mathpath.v1.workspace";
const MAX_TEXT_LENGTH = 5000;
const MAX_IMPORT_BYTES = 3 * 1024 * 1024;
const MAX_BACKUP_BYTES = 50 * 1024 * 1024;
const NARROW_SCREEN = "(max-width: 759px)";
const MASTERY_DIMENSIONS = ["definition", "intuition", "application"];
const DIMENSION_LABELS = { definition: "知道定义", intuition: "理解直觉", application: "会使用" };
const ui = {
  exampleSelect: document.getElementById("example-select"),
  fullBackup: document.getElementById("full-backup-button"), restoreBackup: document.getElementById("restore-backup-button"),
  restoreBackupFile: document.getElementById("restore-backup-file"), backupMessage: document.getElementById("backup-message"),
  selectAllProblems: document.getElementById("select-all-problems"), problemSelectedCount: document.getElementById("problem-selected-count"), deleteProblems: document.getElementById("delete-problems"),
  scopePanel: document.getElementById("scope-panel"), scopeReason: document.getElementById("scope-reason"), scopeOptions: document.getElementById("scope-options"), scopeConfirm: document.getElementById("scope-confirm"), scopeCancel: document.getElementById("scope-cancel"),
  chatScopePanel: document.getElementById("chat-scope-panel"), chatScopeReason: document.getElementById("chat-scope-reason"), chatScopeOptions: document.getElementById("chat-scope-options"), chatScopeCancel: document.getElementById("chat-scope-cancel"),
  goalBooks: document.getElementById("goal-books"), goalBooksContent: document.getElementById("goal-books-content"), lessonBooks: document.getElementById("lesson-books"), lessonBooksContent: document.getElementById("lesson-books-content"),
  problemsButton: document.getElementById("problems-button"), libraryHistoryTab: document.getElementById("library-history-tab"), libraryProblemsTab: document.getElementById("library-problems-tab"), historyLibraryContent: document.getElementById("history-library-content"), problemLibraryContent: document.getElementById("problem-library-content"), problemSearch: document.getElementById("problem-search"), problemFilter: document.getElementById("problem-filter"), problemRefresh: document.getElementById("problem-refresh"), problemMessage: document.getElementById("problem-message"), problemList: document.getElementById("problem-list"), problemLoadMore: document.getElementById("problem-load-more"), chatKeepProblem: document.getElementById("chat-keep-problem"),
  chatLauncher: document.getElementById("chat-launcher"),
  chatWindow: document.getElementById("chat-window"),
  chatTitlebar: document.getElementById("chat-titlebar"),
  chatBody: document.getElementById("chat-body"),
  chatResetPosition: document.getElementById("chat-reset-position"),
  chatCollapse: document.getElementById("chat-collapse"),
  chatClose: document.getElementById("chat-close"),
  chatResizeGrip: document.getElementById("chat-resize-grip"),
  chatContext: document.getElementById("chat-context"),
  chatContextNote: document.getElementById("chat-context-note"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatQuestion: document.getElementById("chat-question"),
  chatUseModel: document.getElementById("chat-use-model"),
  chatModeNote: document.getElementById("chat-mode-note"),
  chatStatus: document.getElementById("chat-status"),
  chatCancel: document.getElementById("chat-cancel"),
  chatSend: document.getElementById("chat-send"),
  libraryButton: document.getElementById("library-button"),
  libraryOverlay: document.getElementById("library-overlay"),
  libraryPanel: document.getElementById("library-panel"),
  libraryClose: document.getElementById("library-close"),
  historyTitle: document.getElementById("current-history-title"),
  historyProject: document.getElementById("current-history-project"),
  historySaveStatus: document.getElementById("history-save-status"),
  historySaveRetry: document.getElementById("history-save-retry"),
  studyMode: document.getElementById("study-mode"),
  studyGoalPanel: document.getElementById("study-goal-panel"),
  studyObjective: document.getElementById("study-objective"),
  studyCriteria: document.getElementById("study-criteria"),
  mathContext: document.getElementById("math-context"),
  studySources: document.getElementById("study-sources"),
  diagnosticTasks: document.getElementById("diagnostic-tasks"),
  finalCheckButton: document.getElementById("final-check-button"),
  finalCheckSection: document.getElementById("final-check-section"),
  finalCheckTasks: document.getElementById("final-check-tasks"),
  reviewSummary: document.getElementById("review-summary"),
  reviewList: document.getElementById("review-list"),
  mixedPracticeButton: document.getElementById("mixed-practice-button"),
  mixedPracticeTasks: document.getElementById("mixed-practice-tasks"),
  lessonNotes: document.getElementById("lesson-notes"),
  learningEvidence: document.getElementById("learning-evidence"),
  attemptHistory: document.getElementById("attempt-history"),
  adaptivePracticeTasks: document.getElementById("adaptive-practice-tasks"),
  targetedHelpActions: document.getElementById("targeted-help-actions"),
  targetedHelpInput: document.getElementById("targeted-help-input"),
  targetedHelpResult: document.getElementById("targeted-help-result"),
  projectNavigation: document.getElementById("project-navigation"),
  projectManagement: document.getElementById("project-management"),
  projectManageList: document.getElementById("project-manage-list"),
  projectCreateForm: document.getElementById("project-create-form"),
  projectCreateTitle: document.getElementById("project-create-title"),
  manageProjects: document.getElementById("manage-projects"),
  selectAllProjects: document.getElementById("select-all-projects"),
  deleteProjects: document.getElementById("delete-projects"),
  projectSelectedCount: document.getElementById("project-selected-count"),
  historySearch: document.getElementById("history-search"),
  historyList: document.getElementById("history-list"),
  libraryMessage: document.getElementById("library-message"),
  selectAllHistories: document.getElementById("select-all-histories"),
  historySelectedCount: document.getElementById("history-selected-count"),
  moveHistoryProject: document.getElementById("move-history-project"),
  moveHistories: document.getElementById("move-histories"),
  deleteHistories: document.getElementById("delete-histories"),
  historyLoadMore: document.getElementById("history-load-more"),
  libraryConfirmation: document.getElementById("library-confirmation"),
  libraryConfirmDescription: document.getElementById("library-confirm-description"),
  libraryConfirmYes: document.getElementById("library-confirm-yes"),
  libraryConfirmNo: document.getElementById("library-confirm-no"),
  modelSettingsButton: document.getElementById("model-settings-button"),
  modelProviderStatus: document.getElementById("model-provider-status"),
  modelSettingsOverlay: document.getElementById("model-settings-overlay"),
  modelSettingsPanel: document.getElementById("model-settings-panel"),
  modelSettingsClose: document.getElementById("model-settings-close"),
  modelSettingsForm: document.getElementById("model-settings-form"),
  modelSettingsActive: document.getElementById("model-settings-active"),
  modelProvider: document.getElementById("model-provider"),
  modelApiFields: document.getElementById("model-api-fields"),
  chatgptLoginSection: document.getElementById("chatgpt-login-section"),
  chatgptLoginButton: document.getElementById("chatgpt-login-button"),
  chatgptLoginStatus: document.getElementById("chatgpt-login-status"),
  modelBaseUrl: document.getElementById("model-base-url"),
  modelModel: document.getElementById("model-model"),
  modelApiKey: document.getElementById("model-api-key"),
  modelApiFormat: document.getElementById("model-api-format"),
  modelOutputMode: document.getElementById("model-output-mode"),
  modelSettingsSave: document.getElementById("model-settings-save"),
  modelSettingsClear: document.getElementById("model-settings-clear"),
  modelSettingsTest: document.getElementById("model-settings-test"),
  modelSettingsMessage: document.getElementById("model-settings-message"),
  modelSettingsError: document.getElementById("model-settings-error"),
  form: document.getElementById("goal-form"),
  input: document.getElementById("goal-input"),
  generate: document.getElementById("generate-button"),
  example: document.getElementById("example-button"),
  generationMessage: document.getElementById("generation-message"),
  generationError: document.getElementById("generation-error"),
  generationErrorText: document.getElementById("generation-error-text"),
  generationRetry: document.getElementById("generation-retry"),
  target: document.getElementById("target-label"),
  source: document.getElementById("graph-source"),
  canvas: document.getElementById("graph-canvas"),
  viewport: document.getElementById("graph-viewport"),
  workspace: document.getElementById("workspace"),
  graphToolbar: document.querySelector(".graph-toolbar"),
  graphView: document.getElementById("graph-view-button"),
  listView: document.getElementById("list-view-button"),
  nodeBrowser: document.getElementById("node-browser"),
  nodeSearch: document.getElementById("node-search"),
  nodeList: document.getElementById("node-list"),
  progressSummary: document.getElementById("progress-summary"),
  progressBar: document.getElementById("progress-bar"),
  progressDetail: document.getElementById("progress-detail"),
  export: document.getElementById("export-button"),
  import: document.getElementById("import-button"),
  importFile: document.getElementById("import-file"),
  reset: document.getElementById("reset-button"),
  retry: document.getElementById("retry-button"),
  error: document.getElementById("error-message"),
  errorText: document.getElementById("error-text"),
  heading: document.getElementById("learning-heading"),
  message: document.getElementById("plan-message"),
  count: document.getElementById("known-count"),
  ready: document.getElementById("ready-list"),
  empty: document.getElementById("empty-message"),
  neutralLegend: document.getElementById("neutral-legend"),
  routeLegend: document.getElementById("route-legend"),
  pathSection: document.getElementById("path-section"),
  pathList: document.getElementById("path-list"),
  allReadySection: document.getElementById("all-ready-section"),
  allReadyTitle: document.getElementById("all-ready-title"),
  allReadyList: document.getElementById("all-ready-list"),
  zoomOut: document.getElementById("zoom-out"),
  zoomIn: document.getElementById("zoom-in"),
  zoomLabel: document.getElementById("zoom-label"),
  fitWidth: document.getElementById("fit-width"),
  fitAll: document.getElementById("fit-all"),
  actualSize: document.getElementById("actual-size"),
  storageMessage: document.getElementById("storage-message"),
  storageButton: document.getElementById("storage-button"),
  lessonPanel: document.getElementById("lesson-panel"),
  lessonTitle: document.getElementById("lesson-title"),
  lessonClose: document.getElementById("lesson-close"),
  lessonPrevious: document.getElementById("lesson-previous"),
  lessonNext: document.getElementById("lesson-next"),
  lessonSource: document.getElementById("lesson-source"),
  lessonStatus: document.getElementById("lesson-status"),
  lessonError: document.getElementById("lesson-error"),
  lessonErrorText: document.getElementById("lesson-error-text"),
  lessonRetry: document.getElementById("lesson-retry"),
  lessonContent: document.getElementById("lesson-content"),
  prerequisiteRule: document.getElementById("prerequisite-rule"),
  prerequisiteGroups: document.getElementById("prerequisite-groups"),
  lessonDefinition: document.getElementById("lesson-definition"),
  lessonIntuition: document.getElementById("lesson-intuition"),
  illustrationSection: document.getElementById("lesson-illustration-section"),
  illustrationTitle: document.getElementById("lesson-illustration-title"),
  illustrationViewport: document.getElementById("lesson-illustration-viewport"),
  illustrationCaption: document.getElementById("lesson-illustration-caption"),
  illustrationZoom: document.getElementById("lesson-illustration-zoom"),
  lessonExample: document.getElementById("lesson-example"),
  lessonProof: document.getElementById("lesson-proof"),
  masteryChecks: Object.fromEntries(MASTERY_DIMENSIONS.map(key => [key, document.getElementById(`mastery-${key}`)])),
  masteryAll: document.getElementById("mastery-all"),
  masteryClear: document.getElementById("mastery-clear"),
  masteryHint: document.getElementById("mastery-hint"),
  exerciseForm: document.getElementById("exercise-form"),
  exerciseDimension: document.getElementById("exercise-dimension"),
  exerciseQuestion: document.getElementById("exercise-question"),
  exerciseOptions: document.getElementById("exercise-options"),
  exerciseSubmit: document.getElementById("exercise-submit"),
  exerciseFeedback: document.getElementById("exercise-feedback"),
  exerciseExplanation: document.getElementById("exercise-explanation"),
  exerciseMark: document.getElementById("exercise-mark"),
  followupSection: document.getElementById("followup-section"),
  followupList: document.getElementById("followup-list"),
};

let graph = null;
const MIGRATION_KEY = "mathpath.v04.legacy-import";
const CURRENT_HISTORY_KEY = "mathpath.v04.current-history";
let currentHistory = null;
let studyState = emptyStudyState();
let historyEpoch = 0;
let historyDirty = 0;
let historySaved = 0;
let historySavePromise = null;
let historySaveTimer = null;
let historyConflict = false;
let libraryInitialized = false;
let libraryAvailable = false;
let historySwitching = false;
let libraryLoading = false;
let libraryActionBusy = false;
let projectFilter = "all";
let libraryProjects = [];
let libraryHistories = [];
let selectedHistories = new Set();
let selectedProjects = new Set();
let libraryLoadVersion = 0;
let libraryOpener = null;
let libraryConfirmationAction = null;
let backupPreviewVersion = 0;
const libraryInert = new Map();
let studyTaskVersion = 0;
let learningFeedbackVersion = 0;
const taskViews = new Map();
let chatOpened = false;
let chatCollapsed = false;
let chatRect = null;
let chatPointer = null;
let chatSending = false;
let chatController = null;
let chatRequestVersion = 0;
let chatEphemeralTurns = [];
let chatContextChosen = false;
let chatPendingQuestion = null;
let chatUnresolvedCandidate = null;
let chatScopeApproved = null;
let libraryTab = "histories";
let problemRecords = [];
let selectedProblems = new Set();
let problemLoadVersion = 0;
let problemBusy = false;
let scopeChecking = false;
let scopeVersion = 0;
let scopeController = null;
let scopeResult = null;
let selectedScopeId = null;
let bookGoalVersion = 0;
let bookLessonVersion = 0;
const bookCache = new Map();
let nodeById = new Map();
let layout = null;
let knownIds = new Set();
let mastery = new Map();
let activeLessonId = null;
let lessonCache = new Map();
let lessonVersion = 0;
let lessonController = null;
let lessonLoading = false;
let prerequisiteVersion = 0;
let prerequisiteViews = [];
let prerequisiteGroupViews = [];
const prerequisiteRequests = new Map();
let graphSource = "example";
let plan = null;
let pending = false;
let planVersion = 0;
let planController = null;
let graphRequestVersion = 0;
let graphController = null;
let graphLoading = false;
let failedSource = null;
let saveEnabled = true;
let saveTimer = null;
let zoom = 1;
let zoomMode = "width";
let importVersion = 0;
let lessonOpener = null;
let lessonOpenerContainer = null;
let lessonOpenerId = null;
const inertBackground = new Map();
const narrowScreen = window.matchMedia(NARROW_SCREEN);
let viewMode = narrowScreen.matches ? "list" : "graph";
let viewChosen = false;
let modelSettings = null;
let modelSettingsLoading = false;
let modelSettingsSaving = false;
let modelSettingsTesting = false;
let modelSettingsLoadVersion = 0;
let modelSettingsLoadController = null;
let modelSettingsNeedsReload = false;
let modelSettingsOpener = null;
const modelSettingsInert = new Map();
let chatgptConnection = null;
let chatgptLoginStarting = false;
let chatgptStatusLoading = false;
let chatgptStatusError = "";
let chatgptStatusVersion = 0;
let chatgptStatusController = null;
let chatgptPollTimer = null;
let chatgptPollCount = 0;
const MAX_CHATGPT_STATUS_POLLS = 150;
const DEFAULT_MODEL_SETTINGS = {
  provider: "chatgpt", base_url: "https://api.openai.com/v1", model: "",
  api_format: "chat_completions", output_mode: "json_object", has_api_key: false, revision: "default",
};

function emptyStudyState() {
  return { version: 1, mastery: {}, lessons: {}, notes: {}, attempts: [], reviews: {},
    chat_turns: [],
    study_mode: "intuition", diagnostic_answers: {}, final_answers: {},
    active_node_id: null, view: "graph", graph_source: "generated" };
}

function studyModeForModel() {
  return ["intuition", "application", "proof"].includes(ui.studyMode.value) ? ui.studyMode.value : "intuition";
}

function plainText(value, maximum = 6000) {
  return typeof value === "string" ? value.slice(0, maximum) : "";
}

// Only an explicit allowlist of learning data is ever stored or exported.
function validateStudyState(value, validatedGraph) {
  if (!value || typeof value !== "object" || Array.isArray(value) || value.version !== 1) throw new Error("invalid-workspace");
  const next = emptyStudyState();
  const ids = new Set(validatedGraph.nodes.map(node => node.id));
  const savedChatTurns = value.chat_turns === undefined ? [] : value.chat_turns;
  if (!Array.isArray(savedChatTurns) || savedChatTurns.length > 100) throw new Error("invalid-workspace");
  const turnIds = new Set();
  next.chat_turns = savedChatTurns.map(turn => { const checked = validateChatTurn(turn, ids); if (turnIds.has(checked.id)) throw new Error("invalid-workspace"); turnIds.add(checked.id); return checked; });
  next.mastery = Object.fromEntries(validateMastery(value.mastery || {}, validatedGraph));
  if (!["intuition", "application", "proof", "repair"].includes(value.study_mode || "intuition")) throw new Error("invalid-workspace");
  next.study_mode = value.study_mode || "intuition";
  next.graph_source = value.graph_source === "example" ? "example" : "generated";
  next.view = value.view === "list" ? "list" : "graph";
  next.active_node_id = ids.has(value.active_node_id) ? value.active_node_id : null;
  for (const [id, lesson] of Object.entries(value.lessons || {})) {
    if (!ids.has(id)) throw new Error("invalid-workspace");
    next.lessons[id] = validateLesson(lesson, id);
  }
  for (const [id, note] of Object.entries(value.notes || {})) {
    if (!ids.has(id) || typeof note !== "string" || note.length > 6000) throw new Error("invalid-workspace");
    next.notes[id] = note;
  }
  if (!Array.isArray(value.attempts || []) || (value.attempts || []).length > 500) throw new Error("invalid-workspace");
  const types = ["diagnostic", "guided", "independent", "retrieval", "mixed", "final", "exercise", "followup"];
  const outcomes = ["independent", "hinted", "incorrect", "viewed", "ungraded"];
  for (const attempt of value.attempts || []) {
    if (!attempt || !ids.has(attempt.node_id) || typeof attempt.id !== "string" || typeof attempt.task_id !== "string" ||
      attempt.task_id.length > 120 || typeof attempt.answer !== "string" || attempt.answer.length > 6000 ||
      !Number.isInteger(attempt.hint_level) || attempt.hint_level < 0 || attempt.hint_level > 3 ||
      !types.includes(attempt.attempt_type) || !outcomes.includes(attempt.outcome) || !Number.isFinite(Date.parse(attempt.created_at))) throw new Error("invalid-workspace");
    next.attempts.push({ id: attempt.id, node_id: attempt.node_id, task_id: attempt.task_id,
      answer: attempt.answer, hint_level: attempt.hint_level, attempt_type: attempt.attempt_type,
      outcome: attempt.outcome, created_at: attempt.created_at,
      task: attempt.task ? validateTask(attempt.task, ids) : null,
      feedback: attempt.feedback === null || attempt.feedback === undefined ? null : validateFeedback(attempt.feedback) });
    if (next.attempts.at(-1).task && (next.attempts.at(-1).task.id !== attempt.task_id || next.attempts.at(-1).task.node_id !== attempt.node_id)) throw new Error("invalid-workspace");
    if (next.attempts.at(-1).feedback && (next.attempts.at(-1).feedback.task_id !== attempt.task_id || next.attempts.at(-1).feedback.node_id !== attempt.node_id)) throw new Error("invalid-workspace");
  }
  for (const [id, review] of Object.entries(value.reviews || {})) {
    if (!ids.has(id) || !review || !Number.isFinite(Date.parse(review.due_at)) ||
      !Number.isInteger(review.interval_days) || review.interval_days < 0 || review.interval_days > 3650 ||
      !Number.isInteger(review.streak) || review.streak < 0 ||
      (review.last_attempt_at !== null && !Number.isFinite(Date.parse(review.last_attempt_at)))) throw new Error("invalid-workspace");
    next.reviews[id] = { due_at: review.due_at, interval_days: review.interval_days, streak: review.streak, last_attempt_at: review.last_attempt_at };
  }
  for (const key of ["diagnostic_answers", "final_answers"]) {
    for (const [id, answer] of Object.entries(value[key] || {})) {
      if (id.length > 120 || typeof answer !== "string" || answer.length > 6000) throw new Error("invalid-workspace");
      next[key][id] = answer;
    }
  }
  return next;
}

function collectStudyState() {
  const value = { ...studyState, mastery: Object.fromEntries(mastery),
    lessons: { ...studyState.lessons, ...Object.fromEntries([...lessonCache].map(([id, entry]) => [id, entry.lesson])) },
    active_node_id: activeLessonId, view: viewMode, graph_source: graphSource,
    study_mode: ui.studyMode.value };
  return validateStudyState(value, graph);
}

function uuid() {
  return typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === "x" ? r : (r & 3 | 8)).toString(16); });
}

function validateChatTurn(value, ids = new Set(graph?.nodes.map(node => node.id) || [])) {
  const candidate = value && value.answer_status === undefined ? { ...value, answer_status: "answered" } : value;
  requireExactFields(candidate, ["id", "node_id", "question", "response", "source", "review_required", "created_at", "answer_status"]);
  value = candidate;
  if (typeof value.id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.id) ||
    (value.node_id !== null && !ids.has(value.node_id)) ||
    typeof value.question !== "string" || !value.question.trim() || value.question.length > 6000 ||
    typeof value.response !== "string" || !value.response.trim() || value.response.length > 6000 ||
    !["local_reference", "model_candidate"].includes(value.source) || value.review_required !== true || !["answered", "uncertain", "unanswered"].includes(value.answer_status) ||
    typeof value.created_at !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value.created_at) || !Number.isFinite(Date.parse(value.created_at))) throw new Error("invalid-workspace");
  return { id: value.id, node_id: value.node_id, question: value.question, response: value.response,
    source: value.source, review_required: true, answer_status: value.answer_status, created_at: value.created_at };
}

function chatViewport() {
  return { width: Math.max(160, Number(window.innerWidth) || ui.viewport.clientWidth || 900),
    height: Math.max(120, Number(window.innerHeight) || ui.viewport.clientHeight || 700) };
}

function clampChatRect(candidate) {
  const viewport = chatViewport(); const margin = 8;
  const maxWidth = viewport.width - margin * 2; const maxHeight = viewport.height - margin * 2;
  const width = Math.min(maxWidth, Math.max(Math.min(320, maxWidth), Number(candidate.width) || 420));
  const height = Math.min(maxHeight, Math.max(Math.min(350, maxHeight), Number(candidate.height) || 550));
  const actualHeight = chatCollapsed ? 64 : height;
  return { width, height, x: Math.min(Math.max(margin, viewport.width - width - margin), Math.max(margin, Number(candidate.x) || margin)),
    y: Math.min(Math.max(margin, viewport.height - actualHeight - margin), Math.max(margin, Number(candidate.y) || margin)) };
}

function positionChatWindow(reset = false) {
  const viewport = chatViewport();
  if (!chatRect || reset) chatRect = { width: Math.min(440, viewport.width - 32), height: Math.min(560, viewport.height - 48),
    x: Math.max(8, viewport.width - 464), y: Math.max(8, viewport.height - 584) };
  chatRect = clampChatRect(chatRect);
  ui.chatWindow.style.left = `${chatRect.x}px`; ui.chatWindow.style.top = `${chatRect.y}px`;
  ui.chatWindow.style.width = `${chatRect.width}px`; ui.chatWindow.style.height = `${chatCollapsed ? 64 : chatRect.height}px`;
  ui.chatWindow.classList.toggle("collapsed", chatCollapsed);
  ui.chatBody.hidden = chatCollapsed;
  ui.chatResizeGrip.hidden = chatCollapsed;
  ui.chatCollapse.textContent = chatCollapsed ? "+" : "−";
  ui.chatCollapse.setAttribute("aria-expanded", String(!chatCollapsed));
  ui.chatCollapse.setAttribute("aria-label", chatCollapsed ? "展开提问窗口" : "折叠提问窗口");
}

function chatIsSuspended() {
  return !ui.modelSettingsOverlay.hidden || !ui.libraryOverlay.hidden || Boolean(activeLessonId && narrowScreen.matches && !ui.lessonPanel.hidden);
}

function syncChatVisibility() {
  const suspended = chatIsSuspended();
  if (suspended) finishChatPointer();
  ui.chatWindow.hidden = !chatOpened || suspended;
  ui.chatWindow.inert = suspended;
  ui.chatLauncher.hidden = chatOpened || suspended;
  ui.chatLauncher.inert = suspended;
  ui.chatLauncher.setAttribute("aria-expanded", String(chatOpened));
  if (chatOpened && !suspended) positionChatWindow();
}

function chatTurns() { return currentHistory ? studyState.chat_turns : chatEphemeralTurns; }

function chatRecentTurns(turns = chatTurns()) {
  const recent = []; let size = 0;
  for (const turn of [...turns].reverse()) {
    const length = turn.question.length + turn.response.length;
    if (recent.length >= 10 || size + length > 60000) break;
    recent.unshift(turn); size += length;
  }
  return recent;
}

function renderChatContext() {
  const previous = ui.chatContext.value;
  ui.chatContext.replaceChildren();
  const goal = document.createElement("option"); goal.value = ""; goal.textContent = graph ? "当前学习目标" : "自由提问（未关联学习图）"; ui.chatContext.append(goal);
  if (graph) for (const node of graph.nodes) { const option = document.createElement("option"); option.value = node.id; option.textContent = numberedNodeLabel(node.id); ui.chatContext.append(option); }
  ui.chatContext.value = nodeById.has(previous) ? previous : "";
  const label = ui.chatContext.value ? numberedNodeLabel(ui.chatContext.value) : graph ? nodeById.get(graph.target_id).label : "还没有学习图，可以先作临时提问。";
  ui.chatContextNote.textContent = `${label}${currentHistory ? ` · 当前历史：${currentHistory.title}` : " · 当前对话只在本页暂存，不写入历史。"}`;
}

function renderChatMode() {
  ui.chatModeNote.textContent = ui.chatUseModel.checked
    ? "发送后使用当前模型，消耗相应额度。发送问题、当前图、所选已载入卡片，以及最多最近 10 轮对话；较长对话会减少上下文。不会发送其他项目。"
    : "本地参考模式：只对照当前已有内容，不生成针对新问题的模型回答；不会调用模型。";
}

function renderChatMessages() {
  ui.chatMessages.replaceChildren();
  const turns = chatTurns();
  if (!turns.length && !chatPendingQuestion) {
    const empty = document.createElement("div"); empty.className = "chat-empty";
    const heading = document.createElement("strong"); heading.textContent = "问题可以从一句困惑开始";
    const p = document.createElement("p"); p.textContent = "写下不懂的符号、缺少理由的一步，或请我用更简单的例子解释。也可以切到本地参考模式。";
    empty.append(heading, p); ui.chatMessages.append(empty);
  }
  for (const turn of turns) {
    const item = document.createElement("article"); item.className = "chat-turn"; item.setAttribute("data-chat-turn-id", turn.id);
    const context = document.createElement("p"); context.className = "chat-turn-context";
    context.textContent = `${turn.node_id ? `知识点 ${nodeNumber(turn.node_id)}` : "学习目标 / 自由提问"} · ${new Date(turn.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
    const question = document.createElement("p"); question.className = "chat-question-bubble"; mathText(question, turn.question);
    const response = document.createElement("div"); response.className = "chat-response-bubble";
    const badge = document.createElement("p"); badge.className = "chat-response-source"; badge.textContent = turn.source === "model_candidate" ? "模型回答 · 数学内容请核对" : "本地已有参考 · 不代表新问题已解答";
    if (turn.answer_status !== "answered") badge.textContent += turn.answer_status === "uncertain" ? " · 回答仍不确定" : " · 尚未答出";
    const text = document.createElement("p"); text.className = "chat-response-text"; mathText(text, turn.response);
    const keep = document.createElement("button"); keep.type = "button"; keep.className = "text-button chat-record-problem"; keep.textContent = "仍未解决，记下来";
    const snapshot = problemSnapshot(turn.question, turn.response, turn.node_id);
    keep.addEventListener("click", () => keepProblem(snapshot, keep));
    response.append(badge, text, keep); item.append(context, question, response); ui.chatMessages.append(item);
  }
  if (chatPendingQuestion) {
    const pending = document.createElement("article"); pending.className = "chat-turn chat-turn-pending";
    const question = document.createElement("p"); question.className = "chat-question-bubble"; mathText(question, chatPendingQuestion.question);
    const waiting = document.createElement("p"); waiting.className = "chat-waiting"; waiting.textContent = "正在等待回复…";
    pending.append(question, waiting); ui.chatMessages.append(pending);
  }
  ui.chatMessages.scrollTop = ui.chatMessages.scrollHeight || 0;
}

function renderChatControls() {
  const limit = chatTurns().length >= 100;
  ui.chatSend.disabled = chatSending || historySwitching || limit;
  ui.chatSend.textContent = chatSending ? "等待回复…" : "发送问题";
  ui.chatCancel.hidden = !chatSending;
  ui.chatContext.disabled = chatSending;
  ui.chatUseModel.disabled = chatSending;
  ui.chatWindow.setAttribute("aria-busy", String(chatSending));
  if (limit && !chatSending) ui.chatStatus.textContent = "本条记录已有 100 轮问答。既有对话保留；请先导出备份，再新建学习记录继续提问。";
}

function openChat() {
  if (chatIsSuspended()) return;
  if (!chatContextChosen && !ui.chatQuestion.value.trim() && nodeById.has(activeLessonId)) ui.chatContext.value = activeLessonId;
  chatOpened = true; chatCollapsed = false;
  renderChatContext(); renderChatMode(); renderChatMessages(); renderChatControls(); syncChatVisibility();
  ui.chatQuestion.focus({ preventScroll: true });
}

function closeChat() {
  chatOpened = false; finishChatPointer(); syncChatVisibility();
  if (!chatIsSuspended()) ui.chatLauncher.focus({ preventScroll: true });
}

function cancelChatQuestion(message = "已停止等待。问题保留，可明确选择后重新发送；已发出的模型请求可能仍消耗额度。") {
  ++chatRequestVersion; chatController?.abort(); chatController = null; chatSending = false; chatPendingQuestion = null;
  ui.chatStatus.textContent = message; renderChatControls(); renderChatMessages();
}

function resetChatForHistory() {
  cancelChatQuestion("已切换学习记录，没有自动发送问题。");
  ui.chatQuestion.value = ""; ui.chatContext.value = ""; chatContextChosen = false; chatEphemeralTurns = []; chatUnresolvedCandidate = null; ui.chatKeepProblem.hidden = true;
  clearChatScope();
  renderChatContext(); renderChatMessages(); renderChatControls();
}

function beginChatPointer(event, mode) {
  if (event.button !== undefined && event.button !== 0 || event.isPrimary === false || chatPointer) return;
  if (mode === "move" && (event.target.closest("button") || event.target.closest("select") || event.target.closest("textarea"))) return;
  positionChatWindow(); event.preventDefault();
  const owner = mode === "move" ? ui.chatTitlebar : ui.chatResizeGrip;
  chatPointer = { id: event.pointerId, mode, owner, x: Number(event.clientX) || 0, y: Number(event.clientY) || 0, rect: { ...chatRect } };
  try { owner.setPointerCapture(event.pointerId); } catch { /* Synthetic checks and old hosts may have no active pointer. */ }
  ui.chatWindow.classList.add("chat-manipulating");
}

function moveChatPointer(event) {
  if (!chatPointer || event.pointerId !== chatPointer.id) return;
  event.preventDefault();
  const dx = (Number(event.clientX) || 0) - chatPointer.x; const dy = (Number(event.clientY) || 0) - chatPointer.y;
  const initial = chatPointer.rect;
  chatRect = chatPointer.mode === "move" ? { ...initial, x: initial.x + dx, y: initial.y + dy }
    : { ...initial, width: initial.width + dx, height: initial.height + dy };
  positionChatWindow();
}

function finishChatPointer(event = null) {
  if (!chatPointer || event && event.pointerId !== chatPointer.id) return;
  const previous = chatPointer; chatPointer = null;
  try { if (!previous.owner.hasPointerCapture || previous.owner.hasPointerCapture(previous.id)) previous.owner.releasePointerCapture(previous.id); } catch { /* Capture may already have been released. */ }
  ui.chatWindow.classList.remove("chat-manipulating"); positionChatWindow();
}

function keyboardChatGeometry(event, mode) {
  if (mode === "move" && event.target !== ui.chatTitlebar) return;
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
  event.preventDefault(); positionChatWindow(); const step = event.shiftKey ? 40 : 10;
  const dx = event.key === "ArrowRight" ? step : event.key === "ArrowLeft" ? -step : 0;
  const dy = event.key === "ArrowDown" ? step : event.key === "ArrowUp" ? -step : 0;
  chatRect = mode === "move" ? { ...chatRect, x: chatRect.x + dx, y: chatRect.y + dy }
    : { ...chatRect, width: chatRect.width + dx, height: chatRect.height + dy };
  positionChatWindow();
}

function clearChatScope() { chatScopeApproved = null; ui.chatScopePanel.hidden = true; ui.chatScopeOptions.replaceChildren(); }

function renderChatScope(value) {
  clearChatScope(); ui.chatScopePanel.hidden = false; ui.chatScopeReason.textContent = value.reason; 
  for (const option of value.options) { const button = document.createElement("button"); button.type = "button"; button.className = "chat-scope-choice"; const title = document.createElement("strong"); title.textContent = option.title; const detail = document.createElement("span"); detail.textContent = option.description; button.append(title, detail); button.addEventListener("click", () => { clearChatScope(); ui.chatQuestion.value = option.goal; chatScopeApproved = option.goal; ui.chatStatus.textContent = "已填入这个具体问题。确认上方知识点后，点击发送才请求回答。"; ui.chatQuestion.focus(); }); ui.chatScopeOptions.append(button); }
  ui.chatStatus.textContent = "问题范围较大，请先选方向或修改问题。还没有请求模型回答。";
}

async function sendChatQuestion() {
  if (chatSending || historySwitching) return;
  const question = ui.chatQuestion.value.trim();
  if (!question || question.length > 6000) { ui.chatStatus.textContent = "请写下 1 至 6000 字符的问题。"; ui.chatQuestion.focus(); return; }
  if (chatTurns().length >= 100) { renderChatControls(); return; }
  const nodeId = graph && nodeById.has(ui.chatContext.value) ? ui.chatContext.value : null;
  const submittedGraph = graph; const recordId = currentHistory?.id || null; const epoch = historyEpoch;
  const version = ++chatRequestVersion; const useModel = ui.chatUseModel.checked;
  const turns = chatRecentTurns().map(turn => ({ ...turn }));
  const cachedLesson = nodeId ? lessonCache.get(nodeId)?.lesson || studyState.lessons[nodeId] || null : null;
  const controller = new AbortController(); chatController = controller; let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, useModel ? 150000 : 20000);
  const current = () => version === chatRequestVersion && epoch === historyEpoch && submittedGraph === graph && recordId === (currentHistory?.id || null);
  const unresolvedSnapshot = problemSnapshot(question, "", nodeId);
  chatUnresolvedCandidate = null; ui.chatKeepProblem.hidden = true;
  chatSending = true; chatPendingQuestion = { question, node_id: nodeId }; renderChatControls(); renderChatMessages();
  ui.chatStatus.textContent = useModel ? "正在请求当前模型。关闭或折叠窗口不会自动重试。" : "正在读取本地已有参考…";
  let scopePhase = false;
  try {
    if (question.length <= 5000 && question !== chatScopeApproved) {
      scopePhase = true; ui.chatStatus.textContent = "先检查问题范围，这一步不调用模型。";
      const scoped = await fetch("/study/scope", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal, body: JSON.stringify({ text: question, mode: studyModeForModel() }) });
      if (!scoped.ok) throw new Error("scope-unavailable"); const choices = validateScope(await scoped.json(), question);
      if (!current()) return;
      if (ui.chatQuestion.value.trim() !== question) { ui.chatStatus.textContent = "草稿已经修改，旧问题的范围检查已取消。请重新发送当前问题；没有调用模型。"; return; }
      if (choices.needs_selection) { chatPendingQuestion = null; renderChatScope(choices); return; }
      scopePhase = false;
    }
    clearChatScope(); ui.chatStatus.textContent = useModel ? "正在请求当前模型。关闭或折叠窗口不会自动重试。" : "正在读取本地已有参考…";
    const response = await fetch("/study/chat", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ graph: submittedGraph, history_id: recordId, node_id: nodeId, question, lesson: cachedLesson, turns, use_model: useModel }) });
    if (!response.ok) {
      const error = new Error("chat-unavailable");
      try { const payload = await response.json(); if (typeof payload.problem_id === "string" && isLibraryId(payload.problem_id)) error.problemSaved = true; error.problemSaveFailed = payload.problem_save_failed === true; } catch { /* Network/old-host failures can still be manually recorded. */ }
      throw error;
    }
    const result = await response.json();
    if (!current()) return;
    requireExactFields(result, ["response", "source", "review_required", "answer_status", "problem_id", "problem_save_failed"]);
    if ((result.problem_id !== null && !isLibraryId(result.problem_id)) || typeof result.problem_save_failed !== "boolean") throw new Error("invalid-chat");
    const turn = validateChatTurn({ response: result.response, source: result.source, review_required: result.review_required, answer_status: result.answer_status, id: uuid(), node_id: nodeId, question, created_at: new Date().toISOString() }, new Set(submittedGraph?.nodes.map(node => node.id) || []));
    const queueNotice = result.problem_id ? " 问题已记入“未解决问题”，需你手动确认解决。" : result.answer_status !== "answered" || result.problem_save_failed ? " 问题未能自动记入未解决列表，可点下方按钮保存。" : "";
    if (!result.problem_id && (result.answer_status !== "answered" || result.problem_save_failed)) { chatUnresolvedCandidate = { ...unresolvedSnapshot, response: turn.response }; ui.chatKeepProblem.hidden = false; }
    chatTurns().push(turn); chatPendingQuestion = null;
    if (ui.chatQuestion.value.trim() === question) ui.chatQuestion.value = "";
    renderChatMessages();
    if (recordId) {
      saveWorkspace(); ui.chatStatus.textContent = "回复已收到，正在保存到本条学习历史…";
      try { const saved = await flushHistory(); if (current()) ui.chatStatus.textContent = saved
        ? "问答已保存到本条历史。模型回复或本地参考仍需数学核对。" + queueNotice
        : "回复留在当前页面，但保存没有完成。请处理页面顶部的保存提示；暂时不要切换记录。" + queueNotice; }
      catch { if (current()) ui.chatStatus.textContent = "回复留在当前页面，但本机保存未完成。请处理页面顶部的保存提示；暂时不要切换记录。" + queueNotice; }
    } else ui.chatStatus.textContent = "当前问答只在本页暂存，没有关联历史；关闭软件后不会恢复。" + queueNotice;
  } catch (error) {
    if (current()) {
      if (scopePhase) { ui.chatStatus.textContent = "问题范围检查未完成。草稿保留，尚未向模型发送问题；请明确重试。"; return; }
      const message = timedOut ? "回复等待超时。问题保留，可明确重试；模型请求可能已经消耗额度。" : "暂时没有收到有效回复。问题保留，请检查连接或模型配置后明确重试；不会自动重复请求。";
      ui.chatStatus.textContent = message + (error.problemSaved ? " 问题已记入“未解决问题”。" : " 尚未确认存入未解决列表，可手动保存问题。");
      if (!error.problemSaved) { chatUnresolvedCandidate = unresolvedSnapshot; ui.chatKeepProblem.hidden = false; }
    }
  } finally {
    clearTimeout(timer);
    if (current()) { chatController = null; chatSending = false; chatPendingQuestion = null; renderChatControls(); renderChatMessages(); }
  }
}

async function libraryRequest(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { cache: "no-store", ...options, signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    if (!response.ok) {
      const error = new Error(response.status === 409 ? "history-conflict" : response.status === 404 ? "history-deleted" : "library-unavailable");
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : await response.json();
  } finally { clearTimeout(timer); }
}

function validateHistoryRecord(value) {
  if (!value || typeof value.id !== "string" || typeof value.title !== "string" || typeof value.goal !== "string" ||
    !Number.isInteger(value.revision) || value.revision < 1 || (value.project_id !== null && typeof value.project_id !== "string")) throw new Error("invalid-workspace");
  const checkedGraph = validateGraph(value.graph);
  return { ...value, graph: checkedGraph, state: validateStudyState(value.state, checkedGraph) };
}

function isLibraryId(value) { return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value); }

function problemSnapshot(question, response, nodeId) {
  return { history_id: currentHistory?.id || null, node_id: nodeId, goal: (currentHistory?.goal || graph?.study_plan?.objective || nodeById.get(graph?.target_id)?.label || "自由提问").slice(0, 5000),
    node_label: (nodeById.get(nodeId)?.label || "").slice(0, 300), question, response, reason: "user_marked" };
}

function validateProblem(value) {
  requireExactFields(value, ["id", "history_id", "node_id", "goal", "node_label", "question", "response", "reason", "status", "created_at", "updated_at"]);
  if (!isLibraryId(value.id) || value.history_id !== null && !isLibraryId(value.history_id) || value.node_id !== null && (typeof value.node_id !== "string" || !/^[a-z][a-z0-9_]*$/.test(value.node_id)) ||
    typeof value.goal !== "string" || value.goal.length > 5000 || typeof value.node_label !== "string" || value.node_label.length > 300 || typeof value.question !== "string" || !value.question.trim() || value.question.length > 6000 || typeof value.response !== "string" || value.response.length > 6000 ||
    !["model_failure", "uncertain", "user_marked"].includes(value.reason) || !["open", "resolved"].includes(value.status) ||
    [value.created_at, value.updated_at].some(date => typeof date !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/.test(date) || !Number.isFinite(Date.parse(date)))) throw new Error("invalid-problem");
  return value;
}

async function keepProblem(snapshot, button = ui.chatKeepProblem) {
  if (!snapshot || button.disabled) return;
  const epoch = historyEpoch; const recordId = currentHistory?.id || null; button.disabled = true;
  try {
    validateProblem(await libraryRequest("/library/problems", { method: "POST", body: JSON.stringify(snapshot) }));
    button.textContent = "已记入未解决问题";
    if (epoch === historyEpoch && recordId === (currentHistory?.id || null)) { ui.chatStatus.textContent = "问题已保存在本机“未解决问题”。新回复不会自动关闭旧问题，请在列表中确认解决。"; if (button === ui.chatKeepProblem) chatUnresolvedCandidate = null; }
    if (!ui.libraryOverlay.hidden && libraryTab === "problems") loadProblems();
  } catch {
    button.disabled = false;
    if (epoch === historyEpoch && recordId === (currentHistory?.id || null)) ui.chatStatus.textContent = "未解决问题尚未保存。问题仍保留，可重试；不会调用模型。";
  }
}

function setLibraryTab(tab) {
  libraryTab = tab === "problems" ? "problems" : "histories";
  ui.historyLibraryContent.hidden = libraryTab !== "histories"; ui.problemLibraryContent.hidden = libraryTab !== "problems";
  ui.libraryHistoryTab.setAttribute("aria-pressed", String(libraryTab === "histories")); ui.libraryProblemsTab.setAttribute("aria-pressed", String(libraryTab === "problems"));
  ui.libraryConfirmation.hidden = true; libraryConfirmationAction = null;
  if (libraryTab === "problems") { ui.problemSearch.focus({ preventScroll: true }); loadProblems(); }
  else { ui.historySearch.focus({ preventScroll: true }); loadLibrary(); }
}

function renderProblems() {
  ui.problemList.replaceChildren();
  for (const record of problemRecords) {
    const article = document.createElement("article"); article.className = "problem-record";
    const selection = document.createElement("label"); selection.className = "problem-selection"; const check = document.createElement("input"); check.type = "checkbox"; check.checked = selectedProblems.has(record.id); check.setAttribute("aria-label", `选择问题：${record.question}`); const selectText = document.createElement("span"); selectText.textContent = "选择这条问题"; selection.append(check, selectText); check.addEventListener("change", () => { check.checked ? selectedProblems.add(record.id) : selectedProblems.delete(record.id); renderProblemSelection(); });
    const title = document.createElement("h3"); mathText(title, record.question);
    const context = document.createElement("p"); context.className = "study-note"; context.textContent = `${record.status === "resolved" ? "已解决" : "未解决"} · ${record.reason === "model_failure" ? "请求未完成" : record.reason === "uncertain" ? "回答不确定或未答出" : "自己标记"} · ${new Date(record.created_at).toLocaleString("zh-CN")}`;
    const detail = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "查看问题、当时的目标与回复";
    const goal = document.createElement("p"); mathText(goal, `学习目标：${record.goal || "自由提问"}`);
    const node = document.createElement("p"); node.textContent = `知识点：${record.node_label || "未指定"}`;
    const answer = document.createElement("p"); mathText(answer, record.response || "当时未收到有效回复。可以从教材、老师或其他资料继续核查。" ); detail.append(summary, goal, node, answer);
    const actions = document.createElement("div"); actions.className = "problem-actions";
    const status = document.createElement("button"); status.type = "button"; status.className = "secondary-button"; status.textContent = record.status === "resolved" ? "重新打开" : "我已解决";
    status.addEventListener("click", () => mutateProblem(async () => { validateProblem(await libraryRequest(`/library/problems/${encodeURIComponent(record.id)}`, { method: "PATCH", body: JSON.stringify({ status: record.status === "resolved" ? "open" : "resolved" }) })); }, "问题状态已更新；没有调用模型。"));
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "text-button"; remove.textContent = "删除问题";
    remove.addEventListener("click", () => askLibraryDeletion("确定永久删除这条未解决问题及其上下文快照？学习历史和问答不受影响。", () => mutateProblem(() => libraryRequest("/library/problems/delete", { method: "POST", body: JSON.stringify({ ids: [record.id] }) }), "问题已删除。")));
    actions.append(status, remove);
    if (record.history_id) { const open = document.createElement("button"); open.type = "button"; open.className = "text-button"; open.textContent = "打开关联历史"; open.addEventListener("click", async () => { await openHistory(record.history_id); if (!ui.libraryOverlay.hidden) ui.problemMessage.textContent = "关联历史未能打开；可能已经删除，或当前改动尚未保存。问题快照仍保留。"; }); actions.append(open); }
    article.append(selection, title, context, detail, actions); ui.problemList.append(article);
  }
  if (!problemRecords.length) { const p = document.createElement("p"); p.className = "library-empty"; p.textContent = "当前范围没有问题。未答出的问题会保存在此；你也可以在回复下手动记下卡点。"; ui.problemList.append(p); }
  renderProblemSelection();
}

function renderProblemSelection() {
  ui.problemSelectedCount.textContent = `已选 ${selectedProblems.size} 条`;
  ui.selectAllProblems.checked = problemRecords.length > 0 && problemRecords.every(item => selectedProblems.has(item.id));
  ui.selectAllProblems.indeterminate = selectedProblems.size > 0 && !ui.selectAllProblems.checked;
  ui.selectAllProblems.disabled = problemBusy; ui.deleteProblems.disabled = problemBusy || !selectedProblems.size;
}

function deleteSelectedProblems() {
  if (problemBusy || !selectedProblems.size) return; const ids = [...selectedProblems];
  askLibraryDeletion(`确定永久删除所选 ${ids.length} 条问题及其上下文快照？未选择的问题、学习历史和问答保留。`, () => mutateProblem(async () => { await libraryRequest("/library/problems/delete", { method: "POST", body: JSON.stringify({ ids }) }); selectedProblems.clear(); }, `已删除 ${ids.length} 条所选问题。`));
}

async function loadProblems(more = false) {
  const version = ++problemLoadVersion; ui.problemMessage.textContent = "正在读取问题记录…";
  try {
    const params = new URLSearchParams({ status: ui.problemFilter.value || "open", query: ui.problemSearch.value.trim(), offset: String(more ? problemRecords.length : 0), limit: "50" });
    const result = await libraryRequest(`/library/problems?${params}`);
    if (version !== problemLoadVersion) return;
    if (!Array.isArray(result)) throw new Error("invalid-problems"); const checked = result.map(validateProblem);
    problemRecords = more ? [...problemRecords, ...checked] : checked; selectedProblems = new Set([...selectedProblems].filter(id => problemRecords.some(item => item.id === id))); ui.problemLoadMore.hidden = result.length < 50; renderProblems(); ui.problemMessage.textContent = `${problemRecords.length} 条问题记录。状态由你手动确认。`;
  } catch { if (version === problemLoadVersion) ui.problemMessage.textContent = "问题列表未能读取。请刷新重试，已有记录不会因此删除。"; }
}

async function mutateProblem(action, message) {
  if (problemBusy) return; problemBusy = true; renderProblemSelection();
  for (const button of ui.problemList.querySelectorAll("button")) button.disabled = true;
  try { await action(); await loadProblems(); ui.problemMessage.textContent = message; }
  catch { ui.problemMessage.textContent = "操作未完成，请刷新后重试。问题记录仍保留。"; }
  finally { problemBusy = false; renderProblemSelection(); for (const button of ui.problemList.querySelectorAll("button")) button.disabled = false; }
}

function validateBooks(value) {
  requireExactFields(value, ["books", "message"]);
  if (!Array.isArray(value.books) || value.books.length > 5 || typeof value.message !== "string" || value.message.length > 2000) throw new Error("invalid-books");
  const ids = new Set();
  for (const book of value.books) {
    requireExactFields(book, ["id", "title", "author", "url", "section", "why"]);
    if (Object.values(book).some(text => typeof text !== "string" || !text.trim() || text.length > 3000) || ids.has(book.id) || !/^https:\/\/[a-z0-9.-]+(?::\d+)?(?:[/?#][^\s]*)?$/i.test(book.url) || /[@\x00-\x20]/.test(book.url)) throw new Error("invalid-books"); ids.add(book.id);
  }
  return value;
}

async function loadReferenceBooks(container, nodeId) {
  const version = nodeId ? ++bookLessonVersion : ++bookGoalVersion; const submittedGraph = graph; const epoch = historyEpoch;
  container.textContent = "正在查找已核实的参考教材…";
  try {
    const key = nodeId || "goal";
    let result = bookCache.get(key);
    if (!result) { result = validateBooks(await libraryRequest("/study/references", { method: "POST", body: JSON.stringify({ graph: submittedGraph, node_id: nodeId, text: currentHistory?.goal || ui.input.value }) })); }
    if (submittedGraph !== graph || epoch !== historyEpoch || version !== (nodeId ? bookLessonVersion : bookGoalVersion) || nodeId && activeLessonId !== nodeId) return;
    bookCache.set(key, result); container.replaceChildren();
    const note = document.createElement("p"); note.className = "study-note"; note.textContent = result.message; container.append(note);
    for (const book of result.books) { const article = document.createElement("article"); article.className = "reference-book"; const link = document.createElement("a"); link.textContent = book.title; link.href = book.url; link.target = "_blank"; link.rel = "noopener noreferrer"; const author = document.createElement("p"); author.textContent = `${book.author} · ${book.section}`; const why = document.createElement("p"); why.textContent = book.why; article.append(link, author, why); container.append(article); }
  } catch { if (submittedGraph === graph && epoch === historyEpoch && version === (nodeId ? bookLessonVersion : bookGoalVersion)) container.textContent = "暂时未能读取教材目录。可稍后重新打开学习卡；不会自动生成未经核实的书目。"; }
}

function renderBookGuidance() {
  const proof = ui.studyMode.value === "proof";
  ui.goalBooks.hidden = !graph || !proof;
  if (!ui.goalBooks.hidden) loadReferenceBooks(ui.goalBooksContent, null); else ++bookGoalVersion;
  const complete = activeLessonId && MASTERY_DIMENSIONS.every(key => mastery.get(activeLessonId)?.[key]);
  ui.lessonBooks.hidden = !graph || !activeLessonId || !proof && !complete;
  if (!ui.lessonBooks.hidden) loadReferenceBooks(ui.lessonBooksContent, activeLessonId); else ++bookLessonVersion;
}

function renderHistoryIdentity() {
  ui.historyTitle.textContent = currentHistory?.title || (graph ? "未关联历史的学习图" : "准备学习");
  ui.historyProject.textContent = libraryProjects.find(item => item.id === currentHistory?.project_id)?.title || "未分类";
}

function markHistoryDirty() {
  if (!graph || !currentHistory || historySwitching || !saveEnabled) return;
  ++historyDirty;
  ui.historySaveStatus.textContent = historyConflict ? "保存发生冲突，当前改动仍在页面中。可先导出进度。" : "有新改动，正在准备保存…";
  clearTimeout(historySaveTimer);
  if (!historyConflict && !libraryActionBusy) historySaveTimer = setTimeout(() => flushHistory().catch(() => {}), 500);
}

async function flushHistory() {
  clearTimeout(historySaveTimer);
  if (historySavePromise) return historySavePromise;
  if (!currentHistory || historyDirty === historySaved) return true;
  if (historyConflict) throw new Error("history-conflict");
  historySavePromise = (async () => {
    while (currentHistory && historyDirty !== historySaved) {
      const record = currentHistory;
      const epoch = historyEpoch;
      const dirty = historyDirty;
      const state = collectStudyState();
      ui.historySaveStatus.textContent = "正在保存学习记录…";
      try {
        const result = validateHistoryRecord(await libraryRequest(`/library/histories/${encodeURIComponent(record.id)}`, {
          method: "PATCH", body: JSON.stringify({ expected_revision: record.revision, graph, state }),
        }));
        if (epoch !== historyEpoch || currentHistory?.id !== record.id) return false;
        currentHistory = result;
        historySaved = dirty;
        ui.historySaveRetry.hidden = true;
        ui.historySaveStatus.textContent = "已保存到本机学习库";
      } catch (error) {
        if (epoch !== historyEpoch || currentHistory?.id !== record.id) return false;
        historyConflict = error.status === 409 || error.status === 404;
        ui.historySaveStatus.textContent = historyConflict
          ? "记录已在另一个窗口改动或删除。当前页面保留你的改动；导出后可重新载入已存版本。"
          : "尚未保存，当前改动仍在页面中。请重试保存；暂时不能切换记录。";
        ui.historySaveRetry.hidden = false;
        ui.historySaveRetry.textContent = historyConflict ? "导出改动并载入已存版本" : "重试保存";
        throw error;
      }
    }
    return true;
  })();
  try { return await historySavePromise; } finally { historySavePromise = null; }
}

function invalidateHistoryWork() {
  if (chatSending) cancelChatQuestion("正在切换学习内容。问题保留；已发出的模型请求可能仍消耗额度。");
  ++historyEpoch;
  ++studyTaskVersion;
  ++learningFeedbackVersion;
  cancelScopeSelection(); ++bookGoalVersion; ++bookLessonVersion;
  ++graphRequestVersion;
  graphController?.abort();
  graphController = null;
  graphLoading = false;
  taskViews.clear();
  ui.mixedPracticeTasks.replaceChildren();
  ui.mixedPracticeTasks.hidden = true;
  renderGenerationControls();
}

function installHistory(record, restored = true) {
  historySwitching = true;
  try {
    invalidateHistoryWork();
    currentHistory = record;
    studyState = record.state;
    historyDirty = historySaved = 0;
    historyConflict = false;
    ui.input.value = record.goal;
    ui.studyMode.value = studyState.study_mode;
    installGraph(record.graph, new Map(Object.entries(studyState.mastery)), studyState.graph_source, restored);
    for (const [id, lesson] of Object.entries(studyState.lessons)) lessonCache.set(id, { lesson, choice: null, answer: null });
    setView(studyState.view, true);
    renderStudyGoal();
    renderReviews();
    renderHistoryIdentity();
    ui.historySaveRetry.hidden = true;
    ui.historySaveStatus.textContent = "已从本机历史恢复；没有调用模型";
    try { localStorage.setItem(CURRENT_HISTORY_KEY, record.id); } catch { /* DB record still persists. */ }
  } finally { historySwitching = false; }
}

async function openHistory(id, bypassConflict = false) {
  if (historySwitching || libraryActionBusy) return;
  if (chatSending) cancelChatQuestion("正在切换学习记录。问题保留；没有自动重发。");
  historySwitching = true;
  try {
    if (!bypassConflict) await flushHistory();
    const record = validateHistoryRecord(await libraryRequest(`/library/histories/${encodeURIComponent(id)}`));
    installHistory(record);
    closeLibrary();
    ui.generationMessage.textContent = "已恢复历史图、学习卡、笔记和作答，没有调用模型。";
  } catch (error) {
    ui.libraryMessage.textContent = error.status === 404 ? "这条记录已经删除。当前页面保留原内容，请导出需要的改动。" : "未能打开记录。请先解决当前保存问题后重试。";
  } finally { historySwitching = false; }
}

async function createHistoryForGraph(value, states, source, goal, restoredState = null, migrationKey = null) {
  await flushHistory();
  const checkedGraph = validateGraph(value);
  const state = restoredState || { ...emptyStudyState(), mastery: Object.fromEntries(states), graph_source: source, study_mode: ui.studyMode.value };
  const payload = { title: (goal.trim() || checkedGraph.nodes.find(node => node.id === checkedGraph.target_id).label).slice(0, 100),
    goal: goal.slice(0, 5000), graph: checkedGraph, state: validateStudyState(state, checkedGraph), project_id: projectFilter === "all" || projectFilter === "unclassified" ? null : projectFilter };
  if (migrationKey) payload.migration_key = migrationKey;
  if (chatSending) cancelChatQuestion("正在创建学习记录。问题保留；没有自动重发。");
  historySwitching = true;
  const previousInert = ui.workspace.inert;
  ui.workspace.inert = true;
  try {
    const record = validateHistoryRecord(await libraryRequest("/library/histories", { method: "POST", body: JSON.stringify(payload) }));
    installHistory(record, !!migrationKey);
    return record;
  } finally { historySwitching = false; ui.workspace.inert = previousInert; }
}

async function initializeLibrary() {
  try {
    libraryProjects = await libraryRequest("/library/projects");
    if (!Array.isArray(libraryProjects)) throw new Error("invalid-library");
    libraryAvailable = true;
    let migrated = false;
    const legacy = localStorage.getItem(STORAGE_KEY);
    let migration = localStorage.getItem(MIGRATION_KEY);
    if (legacy && (!migration || !migration.startsWith("done:"))) {
      const saved = JSON.parse(legacy);
      if (![1, 2].includes(saved.version) || typeof saved.draft !== "string" || !["example", "generated"].includes(saved.source)) throw new Error("invalid-legacy");
      const checkedGraph = validateGraph(saved.graph);
      const restored = saved.version === 1 ? new Map([...validateKnown(saved.known_ids, checkedGraph)].map(id => [id, { definition: true, intuition: true, application: true }])) : validateMastery(saved.mastery, checkedGraph);
      if (!migration) { migration = `legacy-workspace-v1:${uuid()}`; localStorage.setItem(MIGRATION_KEY, migration); }
      await createHistoryForGraph(checkedGraph, restored, saved.source, saved.draft, null, migration);
      localStorage.setItem(MIGRATION_KEY, `done:${currentHistory.id}`);
      migrated = true;
    }
    if (!migrated) {
      const records = await libraryRequest("/library/histories?limit=50&offset=0");
      let remembered = localStorage.getItem(CURRENT_HISTORY_KEY);
      if (!records.some(record => record.id === remembered)) remembered = records[0]?.id;
      if (remembered) installHistory(validateHistoryRecord(await libraryRequest(`/library/histories/${encodeURIComponent(remembered)}`)));
      else await loadRequestedGraph("example");
    }
    libraryInitialized = true;
    ui.storageMessage.textContent = "历史、笔记与作答保存在本机学习库；账号和密钥不进入学习记录或导出文件。";
  } catch (error) {
    libraryInitialized = true;
    ui.historySaveStatus.textContent = "学习库暂时不可用。保留原浏览器进度，请先导出备份；本次不自动覆盖旧记录。";
    // Legacy browser data is read for recovery, never erased on a library failure.
    try { await restoreWorkspace(); } catch { /* Existing data remains untouched. */ }
    ui.storageMessage.textContent = "本机学习库未连接，当前记录不能保存。可导出后重试打开软件。";
    ui.historySaveRetry.hidden = false;
    ui.historySaveRetry.textContent = "重新连接学习库";
  }
}

function closeLibrary() {
  backupPreviewVersion += 1;
  ui.fullBackup.disabled = false; ui.restoreBackup.disabled = false;
  ui.libraryOverlay.hidden = true;
  ui.libraryPanel.hidden = true;
  ui.libraryConfirmation.hidden = true;
  libraryConfirmationAction = null;
  document.body.classList.remove("library-open");
  for (const [element, previous] of libraryInert) element.inert = previous;
  libraryInert.clear();
  syncChatVisibility();
  const opener = libraryOpener?.isConnected && !libraryOpener.closest("[hidden]") && !libraryOpener.closest("[inert]") ? libraryOpener : ui.libraryButton;
  opener.focus({ preventScroll: true });
}

function openLibrary(opener = document.activeElement, tab = "histories") {
  if (!ui.modelSettingsOverlay.hidden) closeModelSettings();
  closeLesson(false);
  libraryOpener = opener;
  ui.libraryOverlay.hidden = false;
  ui.libraryPanel.hidden = false;
  document.body.classList.add("library-open");
  for (const element of [document.querySelector(".page"), ui.modelSettingsOverlay]) {
    if (!element) continue;
    libraryInert.set(element, element.inert);
    element.inert = true;
  }
  syncChatVisibility();
  setLibraryTab(tab);
}

function libraryFocusable() {
  return [...ui.libraryPanel.querySelectorAll("button,input,textarea,select,[tabindex]")].filter(element => !element.disabled && !element.hidden && !element.closest("[hidden]"));
}

function renderLibrarySelection() {
  ui.historySelectedCount.textContent = `已选 ${selectedHistories.size} 条`;
  ui.projectSelectedCount.textContent = `已选 ${selectedProjects.size} 个`;
  ui.selectAllHistories.checked = libraryHistories.length > 0 && libraryHistories.every(item => selectedHistories.has(item.id));
  ui.selectAllHistories.indeterminate = selectedHistories.size > 0 && !ui.selectAllHistories.checked;
  ui.selectAllProjects.checked = libraryProjects.length > 0 && libraryProjects.every(item => selectedProjects.has(item.id));
  ui.selectAllProjects.indeterminate = selectedProjects.size > 0 && !ui.selectAllProjects.checked;
  ui.moveHistories.disabled = ui.deleteHistories.disabled = !selectedHistories.size || libraryActionBusy;
  ui.deleteProjects.disabled = !selectedProjects.size || libraryActionBusy;
}

function renderLibrary() {
  ui.projectNavigation.replaceChildren();
  for (const item of [{ id: "all", title: "全部历史" }, { id: "unclassified", title: "未分类" }, ...libraryProjects]) {
    const button = document.createElement("button");
    button.className = "project-filter";
    button.type = "button";
    button.textContent = item.title;
    button.setAttribute("aria-pressed", String(projectFilter === item.id));
    button.addEventListener("click", () => { projectFilter = item.id; selectedHistories.clear(); loadLibrary(); });
    ui.projectNavigation.append(button);
  }
  const selectedMove = ui.moveHistoryProject.value;
  ui.moveHistoryProject.replaceChildren();
  for (const project of [{ id: "", title: "未分类" }, ...libraryProjects]) {
    const option = document.createElement("option"); option.value = project.id; option.textContent = project.title;
    ui.moveHistoryProject.append(option);
  }
  ui.moveHistoryProject.value = libraryProjects.some(item => item.id === selectedMove) ? selectedMove : "";
  ui.projectManageList.replaceChildren();
  for (const project of libraryProjects) {
    const row = document.createElement("div"); row.className = "project-manage-row";
    const checkLabel = document.createElement("label"); checkLabel.className = "selection-target";
    const check = document.createElement("input"); check.type = "checkbox"; check.checked = selectedProjects.has(project.id);
    const span = document.createElement("span"); span.textContent = project.title;
    checkLabel.append(check, span);
    check.addEventListener("change", () => { check.checked ? selectedProjects.add(project.id) : selectedProjects.delete(project.id); renderLibrarySelection(); });
    const rename = document.createElement("input"); rename.value = project.title; rename.maxLength = 100; rename.setAttribute("aria-label", `重命名 ${project.title}`);
    const save = document.createElement("button"); save.type = "button"; save.className = "tool-button"; save.textContent = "改名";
    save.addEventListener("click", () => libraryMutation(async () => {
      const title = rename.value.trim(); if (!title) throw new Error("empty-title");
      await libraryRequest(`/library/projects/${encodeURIComponent(project.id)}`, { method: "PATCH", body: JSON.stringify({ title }) });
    }, "项目已改名。"));
    row.append(checkLabel, rename, save); ui.projectManageList.append(row);
  }
  ui.historyList.replaceChildren();
  for (const record of libraryHistories) {
    const row = document.createElement("article"); row.className = "history-row";
    const checkLabel = document.createElement("label"); checkLabel.className = "selection-target history-selection";
    const check = document.createElement("input"); check.type = "checkbox"; check.checked = selectedHistories.has(record.id);
    check.setAttribute("aria-label", `选择 ${record.title}`); checkLabel.append(check);
    check.addEventListener("change", () => { check.checked ? selectedHistories.add(record.id) : selectedHistories.delete(record.id); renderLibrarySelection(); });
    const body = document.createElement("div"); body.className = "history-row-body";
    const button = document.createElement("button"); button.className = "history-open"; button.type = "button";
    button.textContent = `${record.id === currentHistory?.id ? "正在学习 · " : ""}${record.title}`;
    button.addEventListener("click", () => openHistory(record.id));
    const metadata = document.createElement("p");
    const date = new Date(record.updated_at);
    metadata.textContent = `${libraryProjects.find(item => item.id === record.project_id)?.title || "未分类"} · ${Number.isNaN(date.valueOf()) ? "" : date.toLocaleString("zh-CN")}`;
    const renameRow = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "修改标题";
    const rename = document.createElement("input"); rename.value = record.title; rename.maxLength = 100; rename.setAttribute("aria-label", `历史标题 ${record.title}`);
    const save = document.createElement("button"); save.type = "button"; save.className = "tool-button"; save.textContent = "保存标题";
    save.addEventListener("click", () => libraryMutation(async () => {
      await flushHistory();
      const latest = record.id === currentHistory?.id ? currentHistory : validateHistoryRecord(await libraryRequest(`/library/histories/${encodeURIComponent(record.id)}`));
      const title = rename.value.trim(); if (!title) throw new Error("empty-title");
      const changed = await libraryRequest(`/library/histories/${encodeURIComponent(record.id)}`, { method: "PATCH", body: JSON.stringify({ title, expected_revision: latest.revision }) });
      if (currentHistory?.id === record.id) { currentHistory = validateHistoryRecord(changed); renderHistoryIdentity(); }
    }, "历史标题已保存。"));
    renameRow.append(summary, rename, save); body.append(button, metadata, renameRow); row.append(checkLabel, body);
    ui.historyList.append(row);
  }
  if (!libraryHistories.length) { const p = document.createElement("p"); p.className = "library-empty"; p.textContent = "这个范围还没有历史记录。载入样例或成功生成学习图后会自动保存。"; ui.historyList.append(p); }
  renderLibrarySelection();
  renderHistoryIdentity();
}

async function loadLibrary(more = false) {
  const version = ++libraryLoadVersion;
  libraryLoading = true;
  ui.libraryMessage.textContent = "正在读取本机记录…";
  try {
    const params = new URLSearchParams({ query: ui.historySearch.value.trim(), offset: String(more ? libraryHistories.length : 0), limit: "50" });
    if (projectFilter !== "all") params.set("project_id", projectFilter === "unclassified" ? "uncategorized" : projectFilter);
    const [projects, histories] = await Promise.all([libraryRequest("/library/projects"), libraryRequest(`/library/histories?${params}`)]);
    if (version !== libraryLoadVersion) return;
    if (!Array.isArray(projects) || !Array.isArray(histories)) throw new Error("invalid-library");
    libraryProjects = projects; libraryHistories = more ? [...libraryHistories, ...histories] : histories;
    selectedHistories = new Set([...selectedHistories].filter(id => libraryHistories.some(item => item.id === id)));
    selectedProjects = new Set([...selectedProjects].filter(id => libraryProjects.some(item => item.id === id)));
    ui.historyLoadMore.hidden = histories.length < 50;
    ui.libraryMessage.textContent = `${libraryHistories.length} 条记录${histories.length === 50 ? "，可载入更多" : ""}。删除项目会保留其中的历史。`;
    renderLibrary();
  } catch { if (version === libraryLoadVersion) ui.libraryMessage.textContent = "暂时无法读取学习库，请确认软件正在运行后重试。"; }
  finally { if (version === libraryLoadVersion) libraryLoading = false; }
}

async function libraryMutation(action, success) {
  if (libraryActionBusy) return;
  libraryActionBusy = true; clearTimeout(historySaveTimer); renderLibrarySelection();
  try { await action(); await loadLibrary(); ui.libraryMessage.textContent = success; }
  catch (error) { ui.libraryMessage.textContent = error.message === "empty-title" ? "请填写名称。" : "操作未完成，记录仍保留。请先处理保存或连接问题，再重试。"; }
  finally { libraryActionBusy = false; renderLibrarySelection(); if (currentHistory && historyDirty !== historySaved && !historyConflict) historySaveTimer = setTimeout(() => flushHistory().catch(() => {}), 500); }
}

async function refreshHistoryAfterBatch(previousRecord) {
  if (!currentHistory || currentHistory.id !== previousRecord.id) return;
  const latest = validateHistoryRecord(await libraryRequest(`/library/histories/${encodeURIComponent(previousRecord.id)}`));
  const unchangedContent = latest.title === previousRecord.title && latest.goal === previousRecord.goal &&
    JSON.stringify(latest.graph) === JSON.stringify(previousRecord.graph) && JSON.stringify(latest.state) === JSON.stringify(previousRecord.state);
  if (!unchangedContent) {
    historyConflict = true;
    ui.historySaveStatus.textContent = "项目操作完成，但这条学习记录同时在别的窗口发生内容变动。当前改动保留，请导出后载入已存版本。";
    ui.historySaveRetry.hidden = false; ui.historySaveRetry.textContent = "导出改动并载入已存版本";
    return;
  }
  currentHistory = latest; renderHistoryIdentity();
}

function askLibraryDeletion(description, action, kind = "delete") {
  if (libraryActionBusy) return;
  document.getElementById("library-confirm-title").textContent = kind === "restore" ? "确认恢复备份" : "确认删除";
  ui.libraryConfirmYes.textContent = kind === "restore" ? "确认添加备份中的记录" : "确认删除";
  ui.libraryConfirmDescription.textContent = description;
  libraryConfirmationAction = action;
  ui.libraryConfirmation.hidden = false;
  ui.libraryConfirmNo.focus({ preventScroll: true });
}

function validateBackupPreview(value) {
  requireExactFields(value, ["projects", "histories", "problems", "already_restored"]);
  if (![value.projects, value.histories, value.problems].every(count => Number.isSafeInteger(count) && count >= 0) ||
      typeof value.already_restored !== "boolean") throw new Error("invalid-backup-preview");
  return value;
}

async function exportFullBackup() {
  if (libraryActionBusy || historySwitching) return;
  ui.fullBackup.disabled = true; ui.restoreBackup.disabled = true;
  ui.backupMessage.textContent = "正在保存当前改动并准备完整备份…";
  try {
    if (!await flushHistory()) throw new Error("unsaved-history");
    const value = await libraryRequest("/library/backup");
    requireExactFields(value, ["format", "version", "created_at", "projects", "histories", "problems"]);
    if (value.format !== "mathpath_library_backup" || value.version !== 1 ||
        ![value.projects, value.histories, value.problems].every(Array.isArray)) throw new Error("invalid-backup");
    const text = JSON.stringify(value, null, 2); const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    if (blob.size > MAX_BACKUP_BYTES) throw new Error("backup-too-large");
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `MathPath-full-backup-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    ui.backupMessage.textContent = `已准备完整备份：${value.projects.length} 个项目、${value.histories.length} 条历史、${value.problems.length} 个问题。请妥善保管其中的个人学习内容。`;
  } catch { ui.backupMessage.textContent = "完整备份未完成。请检查当前记录的保存提示后重试；已有学习记录保留。"; }
  finally { ui.fullBackup.disabled = false; ui.restoreBackup.disabled = false; }
}

async function previewFullBackup(file) {
  if (!file || libraryActionBusy || historySwitching) return;
  const version = ++backupPreviewVersion;
  ui.restoreBackupFile.value = "";
  if (file.size > MAX_BACKUP_BYTES) { ui.backupMessage.textContent = "完整备份最大为 50 MiB，请选择较小的备份文件。"; return; }
  ui.fullBackup.disabled = true; ui.restoreBackup.disabled = true;
  ui.backupMessage.textContent = "正在检查备份内容，尚未添加记录…";
  try {
    const payload = JSON.parse((await file.text()).replace(/^\uFEFF/, ""));
    if (version !== backupPreviewVersion || ui.libraryOverlay.hidden) return;
    const preview = validateBackupPreview(await libraryRequest("/library/backup/preview", { method: "POST", body: JSON.stringify(payload) }));
    if (version !== backupPreviewVersion || ui.libraryOverlay.hidden) return;
    const repeated = preview.already_restored;
    const notice = repeated ? "这份备份已经恢复过。再次添加可找回后来删除的记录，也可能产生重复记录。" : "";
    askLibraryDeletion(`${notice}备份包含 ${preview.projects} 个项目、${preview.histories} 条历史、${preview.problems} 个问题。确认后会作为新记录添加，现有记录继续保留。`, async () => {
      if (libraryActionBusy || historySwitching) return;
      libraryActionBusy = true; ui.fullBackup.disabled = true; ui.restoreBackup.disabled = true;
      try {
        if (!await flushHistory()) throw new Error("unsaved-history");
        const restored = validateBackupPreview(await libraryRequest(`/library/backup/restore${repeated ? "?repeat=true" : ""}`, { method: "POST", body: JSON.stringify(payload) }));
        selectedHistories.clear(); selectedProjects.clear(); selectedProblems.clear();
        projectFilter = "all"; await loadLibrary(); if (libraryTab === "problems") await loadProblems();
        ui.backupMessage.textContent = restored.already_restored ? "这个备份已恢复，未重复添加记录。"
          : `恢复完成：添加 ${restored.projects} 个项目、${restored.histories} 条历史、${restored.problems} 个问题。当前学习内容仍可继续。`;
      } catch { ui.backupMessage.textContent = "恢复未完成。已有记录保留，请检查备份格式或本机存储后重试。"; }
      finally { libraryActionBusy = false; ui.fullBackup.disabled = false; ui.restoreBackup.disabled = false; }
    }, "restore");
    ui.backupMessage.textContent = "备份已检查。确认后才会添加记录，也可以取消。";
  } catch { if (version === backupPreviewVersion && !ui.libraryOverlay.hidden) ui.backupMessage.textContent = "无法读取这个完整备份。请确认选择的是学习库备份；尚未添加记录。"; }
  finally { if (version === backupPreviewVersion || ui.libraryOverlay.hidden) { ui.fullBackup.disabled = false; ui.restoreBackup.disabled = false; } }
}

async function deleteSelectedHistories() {
  const ids = [...selectedHistories];
  askLibraryDeletion(`确定永久删除这 ${ids.length} 条历史记录？对应笔记、作答和学习卡一起删除。项目不会删除。可以先导出需要保留的学习进度。`, () => libraryMutation(async () => {
    await flushHistory();
    await libraryRequest("/library/histories/delete", { method: "POST", body: JSON.stringify({ ids }) });
    if (currentHistory && ids.includes(currentHistory.id)) {
      invalidateHistoryWork(); currentHistory = null; historyDirty = historySaved = 0; historyConflict = false;
      resetChatForHistory();
      clearTimeout(historySaveTimer);
      try { localStorage.removeItem(CURRENT_HISTORY_KEY); } catch { /* no resurrection */ }
      ui.historySaveStatus.textContent = "当前历史已删除。图仍可查看或导出；它不会再次自动保存。新建学习图会创建新记录。";
      ui.historySaveRetry.hidden = true; renderHistoryIdentity();
    }
    selectedHistories.clear();
  }, `已删除 ${ids.length} 条历史。`));
}

async function deleteSelectedProjects() {
  const ids = [...selectedProjects];
  askLibraryDeletion(`确定删除这 ${ids.length} 个项目？项目内全部历史都会保留，并移到“未分类”。`, () => libraryMutation(async () => {
    await flushHistory();
    const previousRecord = currentHistory;
    await libraryRequest("/library/projects/delete", { method: "POST", body: JSON.stringify({ ids }) });
    if (previousRecord && ids.includes(previousRecord.project_id)) await refreshHistoryAfterBatch(previousRecord);
    if (ids.includes(projectFilter)) projectFilter = "unclassified";
    selectedProjects.clear();
  }, "项目已删除，历史保留在未分类。"));
}

function validateTask(value, ids = new Set(graph?.nodes.map(node => node.id) || [])) {
  const kinds = ["diagnostic", "guided", "independent", "retrieval", "mixed", "final", "exercise", "followup"];
  if (!value || typeof value.id !== "string" || value.id.length > 120 || !ids.has(value.node_id) ||
    !kinds.includes(value.kind) || !["choice", "open"].includes(value.format) ||
    typeof value.question !== "string" || value.question.length > 6000 ||
    !Array.isArray(value.options) || value.options.length > 6 || value.options.some(item => typeof item !== "string" || item.length > 1000) ||
    (value.correct_index !== null && (!Number.isInteger(value.correct_index) || value.correct_index < 0 || value.correct_index >= value.options.length)) ||
    !Array.isArray(value.hints) || value.hints.length > 3 || value.hints.some(item => typeof item !== "string" || item.length > 3000) ||
    typeof value.reference_answer !== "string" || value.reference_answer.length > 6000 ||
    !Array.isArray(value.rubric) || value.rubric.length > 12 || value.rubric.some(item => typeof item.id !== "string" || typeof item.description !== "string") ||
    !MASTERY_DIMENSIONS.includes(value.dimension) || !["curated_example", "generated", "local_adaptation"].includes(value.source)) throw new Error("invalid-task");
  return { id: value.id, node_id: value.node_id, kind: value.kind, format: value.format, question: value.question,
    options: [...value.options], correct_index: value.correct_index, hints: [...value.hints], reference_answer: value.reference_answer,
    rubric: value.rubric.map(item => ({ id: item.id, description: item.description })), dimension: value.dimension, source: value.source };
}

function validateStudyPlan(value, ids) {
  if (!value || !["intuition", "application", "proof"].includes(value.mode) || typeof value.objective !== "string" || value.objective.length > 6000 ||
    typeof value.math_context !== "string" || value.math_context.length > 6000 || !Array.isArray(value.criteria) || value.criteria.length > 12 ||
    value.criteria.some(item => typeof item !== "string" || item.length > 1000) || !Array.isArray(value.diagnostics) || !Array.isArray(value.final_tasks) ||
    value.diagnostics.length > 8 || value.final_tasks.length > 8 || !Array.isArray(value.source_notes) || value.source_notes.length > 12) throw graphDataError();
  return { mode: value.mode, objective: value.objective, criteria: [...value.criteria], math_context: value.math_context,
    diagnostics: value.diagnostics.map(task => validateTask(task, ids)), final_tasks: value.final_tasks.map(task => validateTask(task, ids)),
    source_notes: value.source_notes.map(item => {
      if (!item || typeof item.title !== "string" || typeof item.url !== "string" || typeof item.locator !== "string" || !["curated", "unverified"].includes(item.review_status)) throw graphDataError();
      return { title: item.title.slice(0, 300), url: item.url.slice(0, 2048), locator: item.locator.slice(0, 500), review_status: item.review_status };
    }) };
}

function validateFeedback(value) {
  if (!value || typeof value.node_id !== "string" || typeof value.task_id !== "string" ||
    !["correct", "partial", "incorrect", "needs_review"].includes(value.outcome) || typeof value.summary !== "string" || value.summary.length > 6000 ||
    !Array.isArray(value.steps) || value.steps.length > 12 || value.steps.some(item => typeof item.criterion_id !== "string" || !["satisfied", "missing", "uncertain"].includes(item.status) || typeof item.comment !== "string") ||
    (value.next_hint !== null && typeof value.next_hint !== "string") || typeof value.reference_answer !== "string" || typeof value.review_required !== "boolean" ||
    !["continue", "review_prerequisite", "try_again", "compare_reference", "independent_check"].includes(value.next_action) ||
    !["local_check", "local_reference", "model_candidate"].includes(value.source)) throw new Error("invalid-feedback");
  return { node_id: value.node_id, task_id: value.task_id, outcome: value.outcome, summary: value.summary,
    steps: value.steps.map(item => ({ criterion_id: item.criterion_id, status: item.status, comment: item.comment })),
    next_hint: value.next_hint, next_action: value.next_action, source: value.source,
    review_required: value.review_required, reference_answer: value.reference_answer };
}

function mathText(element, value) {
  element.textContent = plainText(value, 12000);
  if (!window.katex || typeof window.katex.render !== "function") return;
  const source = element.textContent;
  const expression = /\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)|\$\$([\s\S]*?)\$\$|\$([^\n$]+)\$/g;
  const pieces = [];
  let previous = 0;
  let count = 0;
  for (const match of source.matchAll(expression)) {
    if (++count > 30) break;
    if (match.index > previous) { const span = document.createElement("span"); span.textContent = source.slice(previous, match.index); pieces.push(span); }
    const span = document.createElement("span");
    try { window.katex.render(match[1] || match[2] || match[3] || match[4], span,
      { displayMode: match[1] !== undefined || match[3] !== undefined, throwOnError: false, trust: false, strict: "warn", maxExpand: 100, maxSize: 10 }); }
    catch { span.textContent = match[0]; }
    pieces.push(span); previous = match.index + match[0].length;
  }
  if (!pieces.length) return;
  const ending = document.createElement("span"); ending.textContent = source.slice(previous); pieces.push(ending);
  element.replaceChildren(...pieces);
}

function renderStudyGoal() {
  if (!graph) return;
  const study = graph.study_plan;
  ui.studyGoalPanel.hidden = false;
  mathText(ui.studyObjective, study?.objective || nodeById.get(graph.target_id).label);
  ui.studyCriteria.replaceChildren();
  for (const criterion of study?.criteria || ["能用自己的话解释核心概念，并完成一个新例子。", "能说明关键条件以及它们为何需要。"] ) {
    const li = document.createElement("li"); mathText(li, criterion); ui.studyCriteria.append(li);
  }
  mathText(ui.mathContext, study?.math_context || "当前图没有声明统一数学约定。学习时请确认对象、系数和符号；旧图仍可使用。" );
  ui.studySources.replaceChildren();
  for (const source of study?.source_notes || []) {
    const li = document.createElement("li");
    const title = document.createElement(/^https:\/\//i.test(source.url) ? "a" : "span");
    title.textContent = source.title;
    if (title.tagName === "A") { title.href = source.url; title.target = "_blank"; title.rel = "noopener noreferrer"; }
    const note = document.createElement("span"); note.textContent = ` · ${source.locator} · ${source.review_status === "curated" ? "固定样例已审阅" : "引用及内容待核对"}`;
    li.append(title, note); ui.studySources.append(li);
  }
  if (!ui.studySources.children.length) { const li = document.createElement("li"); li.textContent = "本图没有提供可核实的出处，请结合教材审阅。"; ui.studySources.append(li); }
  ui.finalCheckSection.hidden = true;
  if (study?.diagnostics.length) renderTasks(ui.diagnosticTasks, study.diagnostics);
  else loadStudyTasks(ui.diagnosticTasks, "diagnostic");
  renderBookGuidance();
}

function taskContextIsCurrent(view) {
  return view.epoch === historyEpoch && view.graph === graph && view.recordId === currentHistory?.id && view.container.contains(view.element);
}

function recordAttempt(task, answer, hintLevel, feedback = null, outcome = null) {
  if (studyState.attempts.length >= 500) {
    ui.historySaveStatus.textContent = "本条学习记录已达到 500 次作答上限。既有记录全部保留；本次新增作答未保存。请先导出备份，再载入样例或生成新的学习图开始新记录。";
    return null;
  }
  const finalOutcome = outcome || (feedback?.outcome === "correct" && !feedback.review_required ? (hintLevel ? "hinted" : "independent") : feedback?.outcome === "incorrect" ? "incorrect" : "ungraded");
  const attempt = { id: uuid(), node_id: task.node_id, task_id: task.id, answer: answer.slice(0, 6000),
    task: validateTask(task), feedback, hint_level: Math.min(3, hintLevel), attempt_type: task.kind, outcome: finalOutcome, created_at: new Date().toISOString() };
  studyState.attempts.push(attempt);
  if (task.kind === "diagnostic") studyState.diagnostic_answers[task.id] = attempt.answer;
  if (task.kind === "final") studyState.final_answers[task.id] = attempt.answer;
  if (finalOutcome !== "viewed") {
    const prior = studyState.reviews[task.node_id];
    const independent = finalOutcome === "independent";
    const streak = independent ? Math.min(100, (prior?.streak || 0) + 1) : 0;
    const interval = independent ? [1, 3, 7, 14, 30, 60][Math.min(streak - 1, 5)] : finalOutcome === "incorrect" ? 0 : 1;
    studyState.reviews[task.node_id] = { due_at: new Date(Date.now() + (finalOutcome === "incorrect" ? 600000 : interval * 86400000)).toISOString(), interval_days: interval,
      last_attempt_at: attempt.created_at, streak };
  }
  saveWorkspace(); renderEvidence(); renderReviews();
  return attempt;
}

function renderEvidence() {
  if (!activeLessonId) return;
  const attempts = studyState.attempts.filter(item => item.node_id === activeLessonId);
  const independent = attempts.filter(item => item.outcome === "independent").length;
  const hinted = attempts.filter(item => item.outcome === "hinted").length;
  const unresolved = attempts.filter(item => ["incorrect", "ungraded"].includes(item.outcome)).length;
  ui.learningEvidence.textContent = attempts.length ? `保存 ${attempts.length} 次记录：独立完成 ${independent} 次；借助提示 ${hinted} 次；尚需自检或继续练习 ${unresolved} 次。` : "还没有保存的作答记录。";
  ui.attemptHistory.replaceChildren();
  for (const attempt of [...attempts].reverse()) {
    const details = document.createElement("details"); details.className = "attempt-history-item";
    const summary = document.createElement("summary");
    const outcomes = { independent: "独立完成", hinted: "借助提示", incorrect: "需再练习", viewed: "查看帮助", ungraded: "待核对" };
    summary.textContent = `${new Date(attempt.created_at).toLocaleString("zh-CN")} · ${outcomes[attempt.outcome]}${attempt.feedback ? "" : " · 自评 / 学习操作"}`;
    const question = document.createElement("p"); mathText(question, `当时的题目：${attempt.task?.question || "旧记录未保存题干快照"}`);
    const answer = document.createElement("p"); const optionIndex = Number(attempt.answer);
    const answerText = attempt.task?.format === "choice" && Number.isInteger(optionIndex) && attempt.answer !== "" ? attempt.task.options[optionIndex] || attempt.answer : attempt.answer;
    mathText(answer, `我的回答：${answerText || "尚未作答"}`);
    const help = document.createElement("p"); help.className = "study-note"; help.textContent = `提示层级 ${attempt.hint_level}/3。${attempt.feedback?.source === "model_candidate" ? "模型反馈尚需核对。" : attempt.feedback?.source === "local_reference" ? "本地参考未自动判定开放题。" : ""}`;
    details.append(summary, question, answer, help);
    if (attempt.feedback) { const feedbackElement = document.createElement("div"); renderFeedbackText(feedbackElement, attempt.feedback); details.append(feedbackElement); }
    if (attempt.task) { const reference = document.createElement("details"); const refSummary = document.createElement("summary"); refSummary.textContent = "当时的提示与参考";
      const text = document.createElement("p"); mathText(text, `${attempt.task.hints.join("\n")}\n参考：${attempt.task.reference_answer}`); reference.append(refSummary, text); details.append(reference); }
    ui.attemptHistory.append(details);
  }
}

function renderReviews() {
  ui.reviewList.replaceChildren();
  if (!graph) return;
  const reviews = Object.entries(studyState.reviews).filter(([id]) => nodeById.has(id)).sort((a, b) => Date.parse(a[1].due_at) - Date.parse(b[1].due_at));
  const due = reviews.filter(([, value]) => Date.parse(value.due_at) <= Date.now()).length;
  ui.reviewSummary.textContent = reviews.length ? `待复习 ${due} 个知识点；另有 ${reviews.length - due} 个已安排。日期采用简单可调整的规则，并非最优间隔测量。` : "作答后会安排建议复习时间。独立完成后拉开间隔；需要提示的内容较早复习。";
  for (const [id, review] of reviews.slice(0, 12)) {
    const button = document.createElement("button"); button.className = "review-item"; button.type = "button";
    button.textContent = `${Date.parse(review.due_at) <= Date.now() ? "今天复习" : new Date(review.due_at).toLocaleDateString("zh-CN")} · 知识点 ${nodeNumber(id)}`;
    button.setAttribute("aria-label", `复习 ${numberedNodeLabel(id)}`);
    button.addEventListener("click", () => { openLesson(id, button); loadStudyTasks(ui.adaptivePracticeTasks, "review", id); });
    ui.reviewList.append(button);
  }
  ui.mixedPracticeButton.disabled = !graph;
}

function renderFeedbackText(element, feedback) {
  element.replaceChildren();
  const summary = document.createElement("p"); mathText(summary, feedback.summary); element.append(summary);
  for (const step of feedback.steps) {
    const p = document.createElement("p"); p.className = `feedback-step ${step.status}`;
    mathText(p, `${step.status === "satisfied" ? "✓" : step.status === "missing" ? "待补" : "需核对"} ${step.comment}`); element.append(p);
  }
  if (feedback.next_hint) { const p = document.createElement("p"); mathText(p, `下一步：${feedback.next_hint}`); element.append(p); }
  const source = document.createElement("p"); source.className = "study-note";
  source.textContent = feedback.source === "model_candidate" ? "模型建议，需自行核对；不会自动标记掌握。" : feedback.source === "local_reference" ? "本地参考对照；开放答案未被自动判定。" : "本地答案检查；只代表这道题的表现。";
  element.append(source);
}

function renderTasks(container, tasks) {
  container.replaceChildren();
  container.hidden = false;
  if (!tasks.length) { const p = document.createElement("p"); p.textContent = "当前内容还没有此类练习。可先完成卡片中的自测。"; container.append(p); return; }
  for (const [index, raw] of tasks.entries()) {
    const task = validateTask(raw);
    const card = document.createElement("article"); card.className = "study-task"; card.setAttribute("data-task-id", task.id);
    const heading = document.createElement("h4");
    const kinds = { diagnostic: "诊断", guided: "补步骤", independent: "独立练习", retrieval: "回忆", mixed: "混合练习", final: "独立检验", exercise: "自测", followup: "后续练习" };
    heading.textContent = `${index + 1}. ${kinds[task.kind]} · 知识点 ${nodeNumber(task.node_id)}`;
    const question = document.createElement("p"); mathText(question, task.question);
    card.append(heading, question);
    const fingerprint = JSON.stringify(task);
    const previous = [...studyState.attempts].reverse().find(item => item.task_id === task.id && item.node_id === task.node_id && item.task && JSON.stringify(item.task) === fingerprint);
    const form = document.createElement("form");
    const input = document.createElement("textarea"); input.rows = 3; input.maxLength = 6000;
    input.setAttribute("aria-label", `第 ${index + 1} 题的回答`); input.placeholder = "先写下自己的推理。不会时可以写“不确定”。";
    input.value = previous?.answer || "";
    let selectedChoice = null;
    if (task.format === "choice") {
      const options = document.createElement("div"); options.className = "exercise-options";
      for (const [choice, option] of task.options.entries()) {
        const label = document.createElement("label"); const radio = document.createElement("input"); radio.type = "radio"; radio.name = `study-${task.id}`; radio.value = String(choice);
        radio.checked = previous?.answer === String(choice);
        if (radio.checked) selectedChoice = choice;
        radio.addEventListener("change", () => { selectedChoice = choice; });
        const span = document.createElement("span"); mathText(span, `${String.fromCharCode(65 + choice)}. ${option}`);
        label.append(radio, span); options.append(label);
      }
      form.append(options);
    } else form.append(input);
    const actions = document.createElement("div"); actions.className = "study-task-actions";
    const submit = document.createElement("button"); submit.type = "submit"; submit.className = "secondary-button"; submit.textContent = task.format === "choice" ? "检查并记录" : "保存答案并对照参考";
    const useModelLabel = document.createElement("label"); useModelLabel.className = "model-feedback-choice";
    const useModel = document.createElement("input"); useModel.type = "checkbox";
    const useModelText = document.createElement("span"); useModelText.textContent = "请模型检查（发送回答，可能计费）";
    useModelLabel.append(useModel, useModelText); useModelLabel.hidden = task.format === "choice";
    actions.append(submit, useModelLabel); form.append(actions); card.append(form);
    const hints = document.createElement("div"); hints.className = "task-hints";
    const hintButton = document.createElement("button"); hintButton.type = "button"; hintButton.className = "tool-button"; hintButton.textContent = "提示 1";
    hintButton.hidden = !task.hints.length;
    const hintContent = document.createElement("div"); hints.append(hintButton, hintContent);
    const view = { task, graph, recordId: currentHistory?.id, epoch: historyEpoch, container, element: card, hintLevel: previous?.hint_level || 0, busy: false, answer: input, referenceSeen: false };
    taskViews.set(`${task.id}:${container.id}`, view);
    hintButton.addEventListener("click", () => {
      if (!taskContextIsCurrent(view)) return;
      const shown = hintContent.children.length;
      if (shown >= task.hints.length) return;
      view.hintLevel = Math.max(view.hintLevel, Math.min(3, shown + 1));
      const p = document.createElement("p"); mathText(p, `${shown + 1}. ${task.hints[shown]}`); hintContent.append(p);
      hintButton.textContent = shown + 1 >= task.hints.length ? "已显示全部提示" : `提示 ${shown + 2}`;
      hintButton.disabled = shown + 1 >= task.hints.length;
      recordAttempt(task, task.format === "choice" ? String(selectedChoice ?? "") : input.value, view.hintLevel, null, "viewed");
    });
    const reference = document.createElement("details"); reference.className = "task-reference";
    const refTitle = document.createElement("summary"); refTitle.textContent = "查看参考与检查标准";
    const refText = document.createElement("p"); mathText(refText, task.reference_answer);
    const rubric = document.createElement("ul"); for (const criterion of task.rubric) { const li = document.createElement("li"); mathText(li, criterion.description); rubric.append(li); }
    reference.append(refTitle, refText, rubric);
    reference.addEventListener("toggle", () => {
      if (!reference.open || view.referenceSeen || !taskContextIsCurrent(view)) return;
      view.referenceSeen = true; view.hintLevel = 3;
      recordAttempt(task, task.format === "choice" ? String(selectedChoice ?? "") : input.value, 3, null, "viewed");
    });
    const feedbackElement = document.createElement("div"); feedbackElement.className = "task-feedback"; feedbackElement.setAttribute("role", "status"); feedbackElement.setAttribute("aria-live", "polite");
    if (previous?.feedback) renderFeedbackText(feedbackElement, previous.feedback);
    const selfCheck = document.createElement("div"); selfCheck.className = "self-check-actions"; selfCheck.hidden = true;
    let latestFeedback = null;
    const nextAction = document.createElement("button"); nextAction.type = "button"; nextAction.className = "tool-button teaching-next-action"; nextAction.hidden = true;
    nextAction.addEventListener("click", () => {
      if (!latestFeedback || !taskContextIsCurrent(view)) return;
      if (latestFeedback.next_action === "try_again") { input.focus({ preventScroll: true }); input.scrollIntoView({ block: "center", behavior: "smooth" }); }
      else if (latestFeedback.next_action === "compare_reference") {
        reference.open = true;
        if (!view.referenceSeen) { view.referenceSeen = true; view.hintLevel = 3; recordAttempt(task, task.format === "choice" ? String(selectedChoice ?? "") : input.value, 3, null, "viewed"); }
        refTitle.focus({ preventScroll: true }); reference.scrollIntoView({ block: "nearest", behavior: "smooth" });
      } else if (latestFeedback.next_action === "review_prerequisite") {
        if (activeLessonId === task.node_id) { document.getElementById("prerequisite-heading").setAttribute("tabindex", "-1"); document.getElementById("prerequisite-heading").focus(); ui.prerequisiteGroups.scrollIntoView({ block: "start", behavior: "smooth" }); }
        else { const prerequisite = nodeById.get(task.node_id).prerequisite_sets.flat()[0]; setView("list", true); ui.nodeSearch.value = nodeById.get(prerequisite || task.node_id).label; renderNodeBrowser(); ui.nodeSearch.focus(); }
      } else if (latestFeedback.next_action === "independent_check") {
        const independentView = [...taskViews.values()].find(candidate => taskContextIsCurrent(candidate) && candidate.container === container && candidate.task.kind === "independent");
        if (independentView) { independentView.answer.focus({ preventScroll: true }); independentView.element.scrollIntoView({ block: "start", behavior: "smooth" }); }
        else { ui.finalCheckSection.hidden = false; if (graph.study_plan?.final_tasks.length) renderTasks(ui.finalCheckTasks, graph.study_plan.final_tasks); else loadStudyTasks(ui.finalCheckTasks, "final"); ui.finalCheckSection.scrollIntoView({ block: "start", behavior: "smooth" }); }
      } else { closeLesson(false); ui.ready.scrollIntoView({ block: "center", behavior: "smooth" }); const button = ui.ready.querySelector("button"); button?.focus(); }
    });
    for (const [outcome, label] of [["independent", "我独立完成了"], ["hinted", "借助提示完成"], ["incorrect", "还需要再练"]]) {
      const button = document.createElement("button"); button.type = "button"; button.className = "tool-button"; button.textContent = label;
      button.addEventListener("click", () => {
        if (!taskContextIsCurrent(view)) return;
        const adjusted = outcome === "independent" && view.hintLevel > 0 ? "hinted" : outcome;
        recordAttempt(task, input.value, view.hintLevel, null, adjusted);
        feedbackElement.textContent = `已保存你的自评：${adjusted === "independent" ? "独立完成" : adjusted === "hinted" ? "借助提示完成" : "还需再练"}。不会自动更改自报掌握。`;
        selfCheck.hidden = true;
      }); selfCheck.append(button);
    }
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (view.busy || !taskContextIsCurrent(view)) return;
      const answer = task.format === "choice" ? selectedChoice === null ? "" : String(selectedChoice) : input.value.trim();
      if (!answer) { feedbackElement.textContent = "请先写下回答或选择答案，可以写“不确定”。"; return; }
      view.busy = true; submit.disabled = true; feedbackElement.textContent = useModel.checked ? "正在请求模型检查，请稍候…" : "正在保存并获取本地参考…";
      try {
        const response = await fetch("/study/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ graph: view.graph, node_id: task.node_id, task_id: task.id, answer, hint_level: view.hintLevel, lesson: lessonCache.get(task.node_id)?.lesson || null, use_model: useModel.checked }) });
        if (!response.ok) throw new Error("feedback-unavailable");
        const feedback = validateFeedback(await response.json());
        if (!taskContextIsCurrent(view)) return;
        if (feedback.task_id !== task.id || feedback.node_id !== task.node_id) throw new Error("invalid-feedback");
        const stored = recordAttempt(task, answer, view.hintLevel, feedback);
        renderFeedbackText(feedbackElement, feedback);
        latestFeedback = feedback;
        const actionLabels = { continue: "查看当前建议学习内容", review_prerequisite: "查看相关先修内容", try_again: "再试一次", compare_reference: "对照参考与检查标准", independent_check: "做一道独立检验" };
        nextAction.textContent = actionLabels[feedback.next_action]; nextAction.hidden = false;
        if (!stored) { const note = document.createElement("p"); note.className = "study-note"; note.textContent = "作答记录达到上限，本次反馈仅在当前页面显示，尚未保存。请先导出备份，再新建学习记录。"; feedbackElement.append(note); }
        if (feedback.next_hint) view.hintLevel = Math.min(3, Math.max(1, view.hintLevel + 1));
        selfCheck.hidden = task.format === "choice";
      } catch { if (taskContextIsCurrent(view)) { recordAttempt(task, answer, view.hintLevel, null, "ungraded"); feedbackElement.textContent = "反馈未完成，回答已留在学习记录中。可以对照参考，再明确选择重试。"; } }
      finally { view.busy = false; submit.disabled = false; }
    });
    card.append(hints, reference, feedbackElement, nextAction, selfCheck); container.append(card);
  }
}

async function loadStudyTasks(container, kind, id = null) {
  if (!graph) return;
  const epoch = historyEpoch; const submittedGraph = graph;
  const token = uuid(); container.setAttribute("data-task-request", token);
  container.hidden = false; container.textContent = "正在准备本地练习，无需调用模型…";
  try {
    const response = await fetch("/study/tasks", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph: submittedGraph, node_id: id, kind, lesson: id ? lessonCache.get(id)?.lesson || null : null }) });
    if (!response.ok) throw new Error("tasks-unavailable");
    const value = await response.json();
    if (epoch !== historyEpoch || submittedGraph !== graph || token !== container.getAttribute("data-task-request")) return;
    if (!value || !Array.isArray(value.tasks) || value.tasks.length > 24) throw new Error("invalid-task");
    if (value.study_plan && !graph.study_plan) { graph.study_plan = validateStudyPlan(value.study_plan, new Set(graph.nodes.map(node => node.id))); saveWorkspace(); }
    const tasks = kind === "lesson" ? value.tasks.filter(task => task.kind !== "exercise") : value.tasks;
    if (kind === "lesson" && tasks.some(task => task.kind === "followup")) ui.followupSection.hidden = true;
    renderTasks(container, tasks);
  } catch { if (epoch === historyEpoch && submittedGraph === graph && token === container.getAttribute("data-task-request")) container.textContent = "本地练习暂时不可用。已有自测和学习卡仍可使用。"; }
}

function renderTargetedHelp() {
  ui.targetedHelpActions.replaceChildren(); ui.targetedHelpResult.replaceChildren(); ui.targetedHelpInput.value = "";
  const modelLabel = document.createElement("label"); modelLabel.className = "model-feedback-choice";
  const modelCheck = document.createElement("input"); modelCheck.type = "checkbox"; modelCheck.id = "targeted-help-model";
  const modelText = document.createElement("span"); modelText.textContent = "请模型针对问题解释（发送内容，可能计费）";
  modelLabel.append(modelCheck, modelText);
  ui.targetedHelpActions.append(modelLabel);
  const actions = [["symbols", "符号看不懂"], ["proof_step", "这一步为什么成立"], ["simpler_example", "给个简单例子"], ["counterexample", "检查条件与反例"], ["check_proof", "对照我的证明"]];
  for (const [action, label] of actions) {
    const button = document.createElement("button"); button.type = "button"; button.className = "tool-button"; button.textContent = label;
    button.addEventListener("click", async () => {
      const id = activeLessonId; const entry = lessonCache.get(id); if (!entry) return;
      const epoch = historyEpoch; const submittedGraph = graph; const version = ++learningFeedbackVersion;
      const question = ui.targetedHelpInput.value.trim() || label;
      button.disabled = true; ui.targetedHelpResult.textContent = modelCheck.checked ? "正在请求模型解释…" : "正在读取本地相关参考…";
      try {
        const response = await fetch("/study/help", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ graph: submittedGraph, node_id: id, action, question, lesson: entry.lesson, use_model: modelCheck.checked }) });
        if (!response.ok) throw new Error("help-unavailable");
        const value = await response.json();
        if (epoch !== historyEpoch || submittedGraph !== graph || id !== activeLessonId || version !== learningFeedbackVersion) return;
        if (!value || typeof value.response !== "string" || !["local_reference", "model_candidate"].includes(value.source) || typeof value.review_required !== "boolean") throw new Error("invalid-help");
        mathText(ui.targetedHelpResult, `${value.source === "model_candidate" ? "模型解释，请核对" : "当前卡片的本地参考"}：\n${value.response}`);
        studyState.notes[id] = `${studyState.notes[id] || ""}\n[${label}] ${question}\n${value.response}`.trim().slice(0, 6000);
        ui.lessonNotes.value = studyState.notes[id]; saveWorkspace();
      } catch { if (epoch === historyEpoch && id === activeLessonId && version === learningFeedbackVersion) ui.targetedHelpResult.textContent = "解释未完成。问题仍在输入框中，可以明确选择后重试。"; }
      finally { button.disabled = false; }
    }); ui.targetedHelpActions.append(button);
  }
}

function renderInteractiveHomology() {
  if (!["boundary_operator", "boundary_squared_zero", "cycles_and_boundaries", "boundaries_inside_cycles", "cycles_mod_boundaries", "why_homology_quotient"].includes(activeLessonId) || graphSource !== "example") return;
  const section = document.createElement("section"); section.className = "interactive-homology";
  const heading = document.createElement("h4"); heading.textContent = "动手改变：三角形的方向与填充";
  const controls = document.createElement("div"); controls.className = "interactive-controls";
  const fillLabel = document.createElement("label"); const fill = document.createElement("input"); fill.type = "checkbox";
  const fillText = document.createElement("span"); fillText.textContent = "加入填充的 2-单形"; fillLabel.append(fill, fillText);
  const reverse = document.createElement("button"); reverse.type = "button"; reverse.className = "tool-button"; reverse.textContent = "反转循环方向";
  const svg = svgElement("svg", { viewBox: "0 0 480 240", role: "img", "aria-label": "三角形循环；可以改变方向和是否填充" });
  const polygon = svgElement("polygon", { points: "80,195 400,195 240,38", stroke: "#255c42", "stroke-width": "4", fill: "none" });
  svg.append(polygon);
  const arrows = svgElement("g"); svg.append(arrows);
  for (const [x, y, label] of [[60,215,"v₀"],[410,215,"v₁"],[240,24,"v₂"]]) svg.append(svgElement("text", { x, y, "text-anchor": "middle", fill: "#233d31", "font-size": "18" }, label));
  const formula = document.createElement("p"); const note = document.createElement("p"); note.className = "study-note";
  let sign = 1;
  function update() {
    polygon.setAttribute("fill", fill.checked ? "#dbe9d4" : "none");
    arrows.replaceChildren();
    for (const [x,y,rotation] of [[240,195,0],[320,116,-135],[160,116,135]]) {
      const path = svgElement("path", { d:"M -12 -8 L 0 0 L -12 8", fill:"none",stroke:"#255c42","stroke-width":"3",transform:`translate(${x} ${y}) rotate(${rotation + (sign === -1 ? 180 : 0)})` }); arrows.append(path);
    }
    const chain = "[v₀,v₁] + [v₁,v₂] − [v₀,v₂]";
    formula.textContent = `z = ${sign === -1 ? "−(" + chain + ")" : chain}，∂z = 0。${fill.checked ? `令 c = ${sign === -1 ? "−" : ""}[v₀,v₁,v₂]，则 ∂c = z。` : "只有圆周边时，本空间没有 2-单形把 z 填成边界。"}`;
    note.textContent = fill.checked ? "在填满的三角形中，z 是边界，其同调类 [z] = 0；反向循环也仍是边界。" : "在三角形圆周中，[z] 为 H₁≅ℤ 的生成元；反向变成 −[z]，二者不同。方向不能被随意忽略。";
  }
  fill.addEventListener("change", update); reverse.addEventListener("click", () => { sign *= -1; update(); });
  controls.append(fillLabel, reverse); section.append(heading, controls, svg, formula, note);
  ui.illustrationSection.append(section); ui.illustrationSection.hidden = false; update();
}

const measure = document.createElement("canvas").getContext("2d");
measure.font = '16px "Microsoft YaHei", "PingFang SC", system-ui, sans-serif';

function svgElement(tag, attributes = {}, text) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  if (text !== undefined) element.textContent = text;
  return element;
}

// Only this public whitelist is retained in memory; an API key is never returned to the form.
function validateModelSettings(value) {
  if (!value || !["chatgpt", "api"].includes(value.provider) ||
      typeof value.base_url !== "string" || value.base_url.length > 2048 ||
      typeof value.model !== "string" || value.model.length > 200 ||
      !["chat_completions", "responses"].includes(value.api_format) ||
      !["json_schema", "json_object", "prompt_only"].includes(value.output_mode) ||
      typeof value.has_api_key !== "boolean" || typeof value.revision !== "string") {
    throw new Error("invalid-model-settings");
  }
  return Object.fromEntries(Object.keys(DEFAULT_MODEL_SETTINGS).map(key => [key, value[key]]));
}

function modelSettingsLabel(settings = modelSettings) {
  if (!settings) return "使用本机已保存的配置，打开设置可查看。";
  if (settings.provider === "chatgpt") return "ChatGPT 授权";
  const host = settings.base_url.match(/^https?:\/\/([^/]+)/i)?.[1] || settings.base_url;
  return `自定义 API · ${settings.model} · ${host}`;
}

function renderModelProviderStatus() {
  ui.modelProviderStatus.textContent = modelSettingsSaving
    ? "模型配置正在保存。关闭设置不会取消已提交的保存。"
    : modelSettingsNeedsReload
      ? "模型配置的保存结果尚未确认，打开设置可重新读取。"
      : `当前模型：${modelSettingsLabel()}`;
  ui.modelSettingsActive.textContent = modelSettingsLoading
    ? "正在读取本机配置…"
    : modelSettingsNeedsReload ? "保存结果尚未确认，请重新读取本机配置后再使用。"
    : modelSettings ? `已保存并生效：${modelSettingsLabel()}` : "本机配置尚未读取。";
}

function setModelSettingsMessage(message = "", error = "") {
  ui.modelSettingsMessage.textContent = message;
  ui.modelSettingsError.textContent = error;
  ui.modelSettingsError.hidden = !error;
}

function fillModelSettingsForm() {
  const settings = modelSettings || DEFAULT_MODEL_SETTINGS;
  ui.modelProvider.value = settings.provider;
  ui.modelBaseUrl.value = settings.base_url;
  ui.modelModel.value = settings.model;
  ui.modelApiFormat.value = settings.api_format;
  ui.modelOutputMode.value = settings.output_mode;
  ui.modelApiKey.value = "";
  ui.modelApiKey.setAttribute("placeholder", settings.has_api_key
    ? "已保存密钥；留空保持，输入可替换" : "输入你的 API 密钥");
  renderModelSettingsControls();
}

function modelSettingsFormValues() {
  return {
    provider: ui.modelProvider.value, base_url: ui.modelBaseUrl.value.trim(),
    model: ui.modelModel.value.trim(), api_format: ui.modelApiFormat.value,
    output_mode: ui.modelOutputMode.value,
  };
}

function modelSettingsFormIsDirty() {
  if (!modelSettings) return true;
  const fields = modelSettingsFormValues();
  return Boolean(ui.modelApiKey.value) || Object.keys(fields).some(key => fields[key] !== modelSettings[key]);
}

function renderModelSettingsControls() {
  const unavailable = !modelSettings || modelSettingsNeedsReload || modelSettingsLoading || modelSettingsSaving || modelSettingsTesting;
  const api = ui.modelProvider.value === "api";
  ui.modelApiFields.hidden = !api;
  ui.modelProvider.disabled = unavailable;
  for (const element of [ui.modelBaseUrl, ui.modelModel, ui.modelApiKey, ui.modelApiFormat, ui.modelOutputMode]) {
    element.disabled = unavailable || !api;
  }
  ui.modelSettingsSave.disabled = unavailable;
  ui.modelSettingsClear.disabled = unavailable || !modelSettings?.has_api_key;
  ui.modelSettingsTest.disabled = unavailable || modelSettings?.provider !== "api" || !modelSettings?.has_api_key;
  ui.modelSettingsSave.textContent = modelSettingsSaving ? "正在保存…" : "保存并使用";
  ui.modelSettingsTest.textContent = modelSettingsTesting ? "正在测试…" : "测试已保存 API（可能计费）";
  ui.modelSettingsForm.setAttribute("aria-busy", String(modelSettingsLoading || modelSettingsSaving || modelSettingsTesting));
  renderModelProviderStatus();
  renderChatgptLogin();
}

function chatgptSettingsVisible() {
  return !ui.modelSettingsOverlay.hidden && ui.modelProvider.value === "chatgpt";
}

function validateChatgptStatus(value) {
  if (!value || !["idle", "pending", "connected", "error"].includes(value.status) ||
      typeof value.message !== "string" || value.message.length > 300 ||
      !Number.isSafeInteger(value.attempt) || value.attempt < 0) {
    throw new Error("invalid-chatgpt-status");
  }
  // Login state never retains account details or additional server fields.
  return { status: value.status, message: value.message.replace(/[\u0000-\u001f\u007f]/g, " ").trim(), attempt: value.attempt };
}

function renderChatgptLogin() {
  ui.chatgptLoginSection.hidden = ui.modelProvider.value !== "chatgpt";
  ui.chatgptLoginButton.disabled = !chatgptSettingsVisible() || chatgptLoginStarting ||
    chatgptStatusLoading || chatgptConnection?.status === "pending";
  let message = "本次运行尚未发起新的登录。点击上方按钮登录或重新连接。";
  if (chatgptLoginStarting || chatgptConnection?.status === "pending") {
    message = "正在等待 ChatGPT 登录。请在系统浏览器完成官方授权；关闭设置不会取消后台登录。";
    if (chatgptPollCount >= MAX_CHATGPT_STATUS_POLLS) message += " 页面查询已暂停，重新打开设置可继续查看状态。";
  } else if (chatgptStatusLoading) {
    message = "正在读取本次登录进度，不会调用模型…";
  } else if (chatgptConnection?.status === "connected") {
    message = chatgptConnection.message || "本次 ChatGPT 登录已完成。";
    if (modelSettings?.provider === "api") message += " 如需使用 ChatGPT，点击“保存并使用”。";
  } else if (chatgptConnection?.status === "error") {
    message = chatgptConnection.message || "ChatGPT 登录未完成，请点击上方按钮重试。";
  }
  ui.chatgptLoginStatus.textContent = chatgptStatusError || message;
  ui.chatgptLoginStatus.classList.toggle("error", Boolean(chatgptStatusError || chatgptConnection?.status === "error"));
  ui.chatgptLoginStatus.setAttribute("data-state", chatgptStatusError ? "error" : chatgptLoginStarting ? "pending" : chatgptConnection?.status || "idle");
}

function stopChatgptStatusPolling() {
  clearTimeout(chatgptPollTimer);
  chatgptPollTimer = null;
  ++chatgptStatusVersion;
  chatgptStatusController?.abort();
  chatgptStatusController = null;
  chatgptStatusLoading = false;
}

function scheduleChatgptStatusPoll() {
  if (!chatgptSettingsVisible() || chatgptConnection?.status !== "pending" ||
      chatgptStatusError || chatgptPollCount >= MAX_CHATGPT_STATUS_POLLS) return;
  const version = chatgptStatusVersion;
  chatgptPollTimer = setTimeout(() => {
    chatgptPollTimer = null;
    if (version !== chatgptStatusVersion || !chatgptSettingsVisible()) return;
    ++chatgptPollCount;
    readChatgptStatus(false);
  }, 2000);
}

async function readChatgptStatus(resetPolling = true) {
  if (!chatgptSettingsVisible()) return;
  stopChatgptStatusPolling();
  if (resetPolling) chatgptPollCount = 0;
  const version = chatgptStatusVersion;
  const controller = new AbortController();
  chatgptStatusController = controller;
  chatgptStatusLoading = true;
  chatgptStatusError = "";
  renderChatgptLogin();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch("/settings/chatgpt/status", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error("chatgpt-status-request-failed");
    const value = await response.json();
    if (version !== chatgptStatusVersion || !chatgptSettingsVisible()) return;
    chatgptConnection = validateChatgptStatus(value);
  } catch {
    if (version !== chatgptStatusVersion || !chatgptSettingsVisible()) return;
    chatgptStatusError = "暂时无法读取 ChatGPT 登录状态，请关闭设置后重新打开。";
  } finally {
    clearTimeout(timer);
    if (version === chatgptStatusVersion && chatgptSettingsVisible()) {
      chatgptStatusLoading = false;
      chatgptStatusController = null;
      renderChatgptLogin();
      scheduleChatgptStatusPoll();
    }
  }
}

async function startChatgptLogin() {
  if (!chatgptSettingsVisible() || chatgptLoginStarting || chatgptStatusLoading ||
      chatgptConnection?.status === "pending") return;
  stopChatgptStatusPolling();
  chatgptPollCount = 0;
  const version = chatgptStatusVersion;
  chatgptLoginStarting = true;
  chatgptStatusError = "";
  chatgptConnection = { status: "pending", message: "", attempt: chatgptConnection?.attempt || 0 };
  renderChatgptLogin();
  try {
    // The explicit login click is the only action that starts browser authorization.
    // It sends neither the form's provider choice nor an API key.
    const response = await fetch("/settings/chatgpt/login", { method: "POST" });
    if (!response.ok) throw new Error("chatgpt-login-request-failed");
    const value = await response.json();
    if (version !== chatgptStatusVersion || !chatgptSettingsVisible()) return;
    chatgptConnection = validateChatgptStatus(value);
  } catch {
    if (version !== chatgptStatusVersion || !chatgptSettingsVisible()) return;
    chatgptConnection = null;
    chatgptStatusError = "未能开始 ChatGPT 登录，请稍后重试。";
  } finally {
    chatgptLoginStarting = false;
    if (chatgptSettingsVisible()) renderChatgptLogin();
    if (version === chatgptStatusVersion && chatgptSettingsVisible()) {
      scheduleChatgptStatusPoll();
    }
  }
}

async function modelSettingsResponseFailure(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string" && body.detail.trim()) {
      return body.detail.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 300);
    }
  } catch { /* Only the backend's safe public message is shown. */ }
  return "本机配置请求未完成，请检查填写内容或稍后重试。";
}

async function loadModelSettings() {
  const version = ++modelSettingsLoadVersion;
  modelSettingsLoadController?.abort();
  const controller = new AbortController();
  modelSettingsLoadController = controller;
  modelSettingsLoading = true;
  setModelSettingsMessage("正在读取本机配置，不会调用模型。");
  renderModelSettingsControls();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch("/settings/model", { cache: "no-store", signal: controller.signal });
    if (!response.ok) {
      const error = new Error("model-settings-request-failed");
      error.userMessage = await modelSettingsResponseFailure(response);
      throw error;
    }
    const value = await response.json();
    if (version !== modelSettingsLoadVersion || ui.modelSettingsOverlay.hidden) return;
    const next = validateModelSettings(value);
    if (modelSettings && modelSettings.revision !== next.revision) invalidateModelContent();
    modelSettings = next;
    modelSettingsNeedsReload = false;
    fillModelSettingsForm();
    setModelSettingsMessage("配置已读取。保存不会测试连接。");
  } catch (error) {
    if (version !== modelSettingsLoadVersion || ui.modelSettingsOverlay.hidden) return;
    setModelSettingsMessage("", error.userMessage || "暂时无法读取本机配置，请关闭设置后重新打开。");
  } finally {
    clearTimeout(timer);
    if (version === modelSettingsLoadVersion) {
      modelSettingsLoading = false;
      modelSettingsLoadController = null;
      renderModelSettingsControls();
      if (chatgptSettingsVisible()) readChatgptStatus();
    }
  }
}

function openModelSettings(opener = document.activeElement) {
  if (!ui.libraryOverlay.hidden) closeLibrary();
  if (!ui.modelSettingsOverlay.hidden) {
    ui.modelSettingsClose.focus({ preventScroll: true });
    return;
  }
  closeLesson(false);
  modelSettingsOpener = opener;
  ui.modelSettingsOverlay.hidden = false;
  ui.modelSettingsPanel.hidden = false;
  document.body.classList.add("model-settings-open");
  for (const sibling of document.body.children) {
    if (sibling === ui.modelSettingsOverlay) continue;
    modelSettingsInert.set(sibling, Boolean(sibling.inert));
    sibling.inert = true;
  }
  syncChatVisibility();
  fillModelSettingsForm();
  ui.modelSettingsClose.focus({ preventScroll: true });
  if (modelSettingsSaving || modelSettingsTesting) {
    setModelSettingsMessage(modelSettingsSaving
      ? "配置仍在保存中。关闭设置不会取消已提交的保存。"
      : "测试仍在进行中，已经向已保存的平台发送请求，可能计费。");
  } else if (!modelSettings || modelSettingsNeedsReload) loadModelSettings();
  if (modelSettings && !modelSettingsNeedsReload && chatgptSettingsVisible()) readChatgptStatus();
}

function closeModelSettings() {
  if (ui.modelSettingsOverlay.hidden) return;
  // A submitted save continues so that its real outcome can update the active provider.
  ++modelSettingsLoadVersion;
  modelSettingsLoadController?.abort();
  modelSettingsLoadController = null;
  modelSettingsLoading = false;
  stopChatgptStatusPolling();
  ui.modelApiKey.value = "";
  ui.modelSettingsOverlay.hidden = true;
  ui.modelSettingsPanel.hidden = true;
  document.body.classList.remove("model-settings-open");
  for (const [element, previous] of modelSettingsInert) element.inert = previous;
  modelSettingsInert.clear();
  syncChatVisibility();
  const opener = modelSettingsOpener?.isConnected && !modelSettingsOpener.closest("[hidden]") &&
    !modelSettingsOpener.closest("[inert]") ? modelSettingsOpener : ui.modelSettingsButton;
  opener.focus({ preventScroll: true });
  modelSettingsOpener = null;
  renderModelSettingsControls();
}

function modelSettingsFocusableElements() {
  return [...ui.modelSettingsPanel.querySelectorAll('button, input, select, [tabindex]:not([tabindex="-1"])')]
    .filter(element => !element.disabled && !element.closest("[hidden]") && element.getClientRects().length > 0);
}

function handleModelSettingsKeyboard(event) {
  if (ui.modelSettingsOverlay.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeModelSettings();
  } else if (event.key === "Tab") {
    const focusable = modelSettingsFocusableElements();
    const first = focusable[0] || ui.modelSettingsPanel;
    const last = focusable[focusable.length - 1] || first;
    const current = document.activeElement;
    if (!focusable.includes(current) || (event.shiftKey ? current === first : current === last)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus({ preventScroll: true });
    }
  }
}

function invalidateModelContent() {
  closeLesson(false);
  lessonCache.clear();
  ++graphRequestVersion;
  ++importVersion;
  graphController?.abort();
  graphController = null;
  graphLoading = false;
  setGenerationError("");
  renderGenerationControls();
  ui.generationMessage.textContent = "模型配置已更新。当前图与掌握标记保留，之后的生成使用新配置。";
}

async function saveModelSettings(clearKey = false) {
  if (!modelSettings || modelSettingsLoading || modelSettingsSaving || modelSettingsTesting) return;
  const fields = clearKey
    ? Object.fromEntries(["provider", "base_url", "model", "api_format", "output_mode"].map(key => [key, modelSettings[key]]))
    : modelSettingsFormValues();
  if (!clearKey && (fields.base_url.length > 2048 || fields.model.length > 200 || ui.modelApiKey.value.length > 4096)) {
    setModelSettingsMessage("", "基础 API 地址最多 2048 字，模型 ID 最多 200 字，密钥最多 4096 字。");
    return;
  }
  if (!clearKey && fields.provider === "api" && (!fields.base_url || !fields.model || (!ui.modelApiKey.value && !modelSettings.has_api_key))) {
    setModelSettingsMessage("", "使用自定义 API 需要基础 API 地址、确切模型 ID 和 API 密钥。");
    return;
  }
  if (clearKey) fields.clear_api_key = true;
  else if (fields.provider === "api" && ui.modelApiKey.value) fields.api_key = ui.modelApiKey.value;
  modelSettingsSaving = true;
  setModelSettingsMessage("正在保存本机配置，不会调用模型。关闭设置不会取消已提交的保存。");
  renderModelSettingsControls();
  let receivedSuccess = false;
  try {
    const saving = fetch("/settings/model", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields),
    });
    // Clear both transient input and payload immediately after submitting the request.
    ui.modelApiKey.value = "";
    delete fields.api_key;
    const response = await saving;
    if (!response.ok) {
      const error = new Error("model-settings-save-failed");
      error.userMessage = await modelSettingsResponseFailure(response);
      throw error;
    }
    receivedSuccess = true;
    modelSettings = validateModelSettings(await response.json());
    modelSettingsNeedsReload = false;
    invalidateModelContent();
    fillModelSettingsForm();
    setModelSettingsMessage(clearKey
      ? "已清除密钥并切回 ChatGPT 授权。当前图和掌握标记保留。"
      : "配置已保存并生效。没有测试连接或自动生成内容。");
  } catch (error) {
    ui.modelApiKey.value = "";
    if (error.userMessage) setModelSettingsMessage("", error.userMessage);
    else {
      modelSettingsNeedsReload = true;
      if (receivedSuccess) invalidateModelContent();
      setModelSettingsMessage("", "暂时无法确认保存结果，请关闭设置后重新打开，核对本机配置。");
    }
  } finally {
    modelSettingsSaving = false;
    renderModelSettingsControls();
    if (chatgptSettingsVisible()) readChatgptStatus();
  }
}

async function testModelSettings() {
  if (!modelSettings || modelSettingsLoading || modelSettingsSaving || modelSettingsTesting) return;
  if (modelSettingsFormIsDirty()) {
    setModelSettingsMessage("请先保存修改，再点击测试。测试只使用已保存的配置。");
    return;
  }
  if (modelSettings.provider !== "api" || !modelSettings.has_api_key) return;
  modelSettingsTesting = true;
  setModelSettingsMessage("正在向已保存的平台发送一个短测试，可能按平台规则计费。");
  renderModelSettingsControls();
  try {
    const response = await fetch("/settings/model/test", { method: "POST" });
    if (!response.ok) {
      const error = new Error("model-settings-test-failed");
      error.userMessage = await modelSettingsResponseFailure(response);
      throw error;
    }
    const value = await response.json();
    if (!value || value.ok !== true) throw new Error("invalid-model-test");
    setModelSettingsMessage("测试完成：收到有效模型回答。");
  } catch (error) {
    setModelSettingsMessage("", error.userMessage || "连接测试未完成，请稍后重试。");
  } finally {
    modelSettingsTesting = false;
    renderModelSettingsControls();
  }
}

function setPlanError(message) {
  ui.errorText.textContent = message;
  ui.error.hidden = !message;
}

function setGenerationError(message, retrySource = null) {
  ui.generationErrorText.textContent = message;
  ui.generationError.hidden = !message;
  failedSource = retrySource;
  ui.generationRetry.hidden = !retrySource;
  ui.generationRetry.textContent = retrySource === "example" ? "重试载入" : "重试生成";
}

function graphDataError() {
  return new Error("invalid-graph");
}

// 存储和接口中的内容都作为数据校验；只保留后端认识的字段。
function validateGraph(value) {
  if (!value || typeof value !== "object" || !Array.isArray(value.nodes) ||
      value.nodes.length < 1 || value.nodes.length > 12 || typeof value.target_id !== "string") {
    throw graphDataError();
  }
  const ids = new Set();
  const normalized = [];
  for (const node of value.nodes) {
    if (!node || typeof node.id !== "string" || !/^[a-z][a-z0-9_]{0,59}$/.test(node.id) ||
        typeof node.label !== "string" || !node.label.trim() || Array.from(node.label).length > 120 ||
        !Array.isArray(node.prerequisite_sets) || ids.has(node.id)) throw graphDataError();
    ids.add(node.id);
    const normalizedNode = { id: node.id, label: node.label, prerequisite_sets: node.prerequisite_sets };
    for (const key of ["rationale", "required_abilities", "branch_outcomes", "required_dimensions"]) {
      if (node[key] === undefined) continue;
      if (key === "rationale") {
        if (typeof node[key] !== "string" || node[key].length > 2000) throw graphDataError();
        normalizedNode[key] = node[key];
      } else {
        if (!Array.isArray(node[key]) || node[key].length > 12 || node[key].some(item => typeof item !== "string" || item.length > 1000)) throw graphDataError();
        if (key === "required_dimensions" && node[key].some(item => !MASTERY_DIMENSIONS.includes(item))) throw graphDataError();
        normalizedNode[key] = [...node[key]];
      }
    }
    normalized.push(normalizedNode);
  }
  if (!ids.has(value.target_id)) throw graphDataError();
  for (const node of normalized) {
    const seenGroups = new Set();
    node.prerequisite_sets = node.prerequisite_sets.map(group => {
      if (!Array.isArray(group) || group.length === 0 || new Set(group).size !== group.length ||
          group.some(id => typeof id !== "string" || !ids.has(id) || id === node.id)) throw graphDataError();
      const key = JSON.stringify([...group].sort());
      if (seenGroups.has(key)) throw graphDataError();
      seenGroups.add(key);
      return [...group];
    });
  }
  const byId = new Map(normalized.map(node => [node.id, node]));
  const visited = new Set();
  const active = new Set();
  function visit(id) {
    if (active.has(id)) throw graphDataError();
    if (visited.has(id)) return;
    active.add(id);
    for (const group of byId.get(id).prerequisite_sets) for (const prerequisite of group) visit(prerequisite);
    active.delete(id);
    visited.add(id);
  }
  visit(value.target_id);
  if (visited.size !== normalized.length) throw graphDataError();
  const output = { target_id: value.target_id, nodes: normalized };
  if (value.study_plan !== undefined && value.study_plan !== null) output.study_plan = validateStudyPlan(value.study_plan, ids);
  return output;
}

function validateKnown(value, validatedGraph) {
  const ids = new Set(validatedGraph.nodes.map(node => node.id));
  if (!Array.isArray(value) || new Set(value).size !== value.length || value.some(id => !ids.has(id))) {
    throw new Error("invalid-known");
  }
  return new Set(value);
}

function emptyMastery() {
  return { definition: false, intuition: false, application: false };
}

function validateMastery(value, validatedGraph) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid-mastery");
  const ids = new Set(validatedGraph.nodes.map(node => node.id));
  const restored = new Map();
  for (const [id, state] of Object.entries(value)) {
    if (!ids.has(id) || !state || typeof state !== "object" || Array.isArray(state) ||
        Object.keys(state).length !== 3 || MASTERY_DIMENSIONS.some(key => typeof state[key] !== "boolean")) {
      throw new Error("invalid-mastery");
    }
    restored.set(id, Object.fromEntries(MASTERY_DIMENSIONS.map(key => [key, state[key]])));
  }
  return restored;
}

function refreshKnownIds() {
  knownIds = new Set([...mastery].filter(([, state]) => MASTERY_DIMENSIONS.every(key => state[key])).map(([id]) => id));
}

function validatePlan(value, submittedIds, submittedGraph) {
  const byId = new Map(submittedGraph.nodes.map(node => [node.id, node]));
  if (!value || value.target_id !== submittedGraph.target_id || typeof value.completed !== "boolean") {
    throw new Error("invalid-plan");
  }
  for (const key of ["known_ids", "ready_ids", "blocked_ids", "required_ids", "recommended_ids", "selected_ids"]) {
    if (value[key] === undefined && ["required_ids", "recommended_ids", "selected_ids"].includes(key)) continue;
    if (!Array.isArray(value[key]) || value[key].some(id => !byId.has(id)) ||
        new Set(value[key]).size !== value[key].length) throw new Error("invalid-plan");
  }
  const submitted = new Set(submittedIds);
  if (value.known_ids.length !== submitted.size || value.known_ids.some(id => !submitted.has(id))) {
    throw new Error("invalid-plan");
  }
  if (value.selected_groups !== undefined) {
    if (!Array.isArray(value.selected_groups)) throw new Error("invalid-plan");
    const seen = new Set();
    for (const selection of value.selected_groups) {
      if (!selection || !byId.has(selection.node_id) || !Number.isInteger(selection.group_index) ||
          selection.group_index < 0 || selection.group_index >= byId.get(selection.node_id).prerequisite_sets.length ||
          seen.has(selection.node_id)) throw new Error("invalid-plan");
      seen.add(selection.node_id);
    }
  }
  if (value.focus_id !== undefined && value.focus_id !== null && !byId.has(value.focus_id)) {
    throw new Error("invalid-plan");
  }
  return value;
}

function saveWorkspace() {
  if (!graph || !saveEnabled) return;
  if (libraryAvailable) { markHistoryDirty(); return; }
  if (libraryInitialized) return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      version: 2, graph,
      mastery: Object.fromEntries(mastery),
      draft: ui.input.value.slice(0, MAX_TEXT_LENGTH),
      source: graphSource,
    }));
    ui.storageMessage.textContent = "已在这个浏览器中保存。刷新后会恢复当前图和掌握标记。";
  } catch {
    ui.storageMessage.textContent = "浏览器暂时无法保存；当前页面仍可使用，刷新后可能无法恢复。";
  }
}

async function restoreWorkspace() {
  const version = graphRequestVersion;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    if (raw.length > 200000) throw new Error("invalid-storage");
    const saved = JSON.parse(raw);
    if (!saved || ![1, 2].includes(saved.version) || typeof saved.draft !== "string" || saved.draft.length > MAX_TEXT_LENGTH ||
        !["example", "generated"].includes(saved.source)) throw new Error("invalid-storage");
    let restoredGraph = validateGraph(saved.graph);
    const restoredMastery = saved.version === 1
      ? new Map([...validateKnown(saved.known_ids, restoredGraph)].map(id => [id, { definition: true, intuition: true, application: true }]))
      : validateMastery(saved.mastery, restoredGraph);
    // 先恢复草稿；样例升级等待期间的输入不能被旧草稿覆盖。
    ui.input.value = saved.draft;
    const oldTargetLabel = "理解同调群取商是为了排除本身能填成边界的循环，并让表示同一个洞的循环归为同一同调类";
    if (saved.source === "example" && restoredGraph.nodes.find(node => node.id === restoredGraph.target_id)?.label === oldTargetLabel) {
      graphLoading = true;
      renderGenerationControls();
      ui.generationMessage.textContent = "正在恢复保存的样例与掌握标记，无需调用模型。";
      restoredGraph = await upgradeSavedExample(restoredGraph, oldTargetLabel);
      if (version !== graphRequestVersion) return true;
      graphLoading = false;
      renderGenerationControls();
    }
    if (version !== graphRequestVersion) return true;
    installGraph(restoredGraph, restoredMastery, saved.source, true);
    saveWorkspace();
    ui.generationMessage.textContent = "已恢复上次的学习图；没有再次调用模型。";
    ui.storageMessage.textContent = "已从这个浏览器恢复当前图和掌握标记。";
    return true;
  } catch {
    if (version !== graphRequestVersion) return true;
    // Keep a recoverable legacy copy if reading or migration fails.
    return false;
  }
}

function requireExactFields(value, fields) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value, key))) {
    throw new Error("invalid-workspace");
  }
}

function validateWorkspaceImport(value) {
  if (value?.format === "mathpath-workspace" && value.version === 2) {
    requireExactFields(value, ["format", "version", "graph", "state", "draft", "source"]);
    if (typeof value.draft !== "string" || value.draft.length > 5000 || !["example", "generated"].includes(value.source)) throw new Error("invalid-workspace");
    const checkedGraph = validateGraph(value.graph);
    const checkedState = validateStudyState(value.state, checkedGraph);
    return { graph: checkedGraph, mastery: new Map(Object.entries(checkedState.mastery)), state: checkedState, draft: value.draft, source: value.source };
  }
  requireExactFields(value, ["format", "version", "graph", "mastery", "draft", "source"]);
  if (value.format !== "mathpath-workspace" || value.version !== 1 ||
      typeof value.draft !== "string" || value.draft.length > MAX_TEXT_LENGTH ||
      !["example", "generated"].includes(value.source)) throw new Error("invalid-workspace");
  requireExactFields(value.graph, ["target_id", "nodes"]);
  if (!Array.isArray(value.graph.nodes)) throw new Error("invalid-workspace");
  for (const node of value.graph.nodes) requireExactFields(node, ["id", "label", "prerequisite_sets"]);
  const validatedGraph = validateGraph(value.graph);
  const validatedMastery = validateMastery(value.mastery, validatedGraph);
  // 先完成全部检查，再由导入操作一次替换工作区。
  buildLayout(validatedGraph);
  return { graph: validatedGraph, mastery: validatedMastery, draft: value.draft, source: value.source };
}

function exportWorkspace() {
  if (!graph) return;
  const payload = {
    format: "mathpath-workspace", version: 2, graph,
    state: collectStudyState(),
    draft: (currentHistory?.goal ?? ui.input.value).slice(0, MAX_TEXT_LENGTH), source: graphSource,
  };
  let url = null;
  let link = null;
  try {
    url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    link = document.createElement("a");
    link.href = url;
    link.download = "mathpath-workspace.json";
    document.body.append(link);
    link.click();
    ui.storageMessage.textContent = "已导出当前学习图、学习卡、笔记、作答和自报进度。账号和密钥不包含在文件中。";
  } catch {
    ui.storageMessage.textContent = "暂时无法下载进度文件，请重试。当前图和掌握标记仍然保留。";
  } finally {
    link?.remove();
    if (url) setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

async function importWorkspace(file) {
  if (!file) return;
  const version = ++importVersion;
  const requestedVersion = graphRequestVersion;
  try {
    if (!Number.isFinite(file.size) || file.size < 0 || file.size > MAX_IMPORT_BYTES) {
      throw new Error("workspace-too-large");
    }
    const raw = await file.text();
    // 读文件期间若启动了另一导入或新图请求，旧文件不再替换工作区。
    if (version !== importVersion || requestedVersion !== graphRequestVersion) return;
    if (typeof raw !== "string" || raw.length > MAX_IMPORT_BYTES) throw new Error("workspace-too-large");
    const imported = validateWorkspaceImport(JSON.parse(raw));
    if (!libraryAvailable) throw new Error("library-unavailable");
    await createHistoryForGraph(imported.graph, imported.mastery, imported.source, imported.draft,
      imported.state || { ...emptyStudyState(), mastery: Object.fromEntries(imported.mastery), graph_source: imported.source });
    setGenerationError("");
    ui.generationMessage.textContent = "已导入并创建新的本机历史记录。没有调用模型。";
  } catch (error) {
    if (version !== importVersion || requestedVersion !== graphRequestVersion) return;
    const message = error.message === "library-unavailable" ? "学习库暂时不可用，请稍后再导入。" : error.message === "workspace-too-large"
      ? "进度文件不能超过 1 MB。"
      : "进度文件格式没有通过检查，请选择有效的 MathPath JSON 导出文件。";
    setGenerationError(`${message} 当前图和掌握标记仍然保留。`);
  }
}

async function upgradeSavedExample(previous, oldTargetLabel) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch("/example", { cache: "no-store", signal: controller.signal });
    if (!response.ok) return previous;
    const canonical = validateGraph(await response.json());
    if (canonical.target_id !== previous.target_id || canonical.nodes.length !== previous.nodes.length) return previous;
    const canonicalNodes = new Map(canonical.nodes.map(node => [node.id, node]));
    const identicalExceptTargetLabel = previous.nodes.every(node => {
      const replacement = canonicalNodes.get(node.id);
      return replacement && JSON.stringify(node.prerequisite_sets) === JSON.stringify(replacement.prerequisite_sets) &&
        (node.id === previous.target_id ? node.label === oldTargetLabel : node.label === replacement.label);
    });
    // 仅修订已知历史样例的一句目标描述；保留自定义图和所有掌握标记。
    return identicalExceptTargetLabel ? canonical : previous;
  } catch {
    return previous;
  } finally {
    clearTimeout(timer);
  }
}

function wrapLabel(label, width) {
  const lines = [];
  let current = "";
  for (const character of label) {
    if (character === "\n") {
      lines.push(current);
      current = "";
    } else if (current && measure.measureText(current + character).width > width) {
      lines.push(current);
      current = character;
    } else current += character;
  }
  if (current || lines.length === 0) lines.push(current);
  return lines;
}

function buildLayout(validatedGraph) {
  const byId = new Map(validatedGraph.nodes.map(node => [node.id, node]));
  const depths = new Map();
  function depthOf(id) {
    if (depths.has(id)) return depths.get(id);
    const dependencies = byId.get(id).prerequisite_sets.flat();
    const depth = dependencies.length ? 1 + Math.max(...dependencies.map(depthOf)) : 0;
    depths.set(id, depth);
    return depth;
  }
  const layers = [];
  const positions = new Map();
  for (const node of validatedGraph.nodes) {
    const depth = depthOf(node.id);
    if (!layers[depth]) layers[depth] = [];
    const slotWidth = Math.max(344, node.prerequisite_sets.length * 86 + 16);
    layers[depth].push({ node, slotWidth });
  }
  const orderedIds = layers.flatMap(layer => layer.map(item => item.node.id));
  for (const [index, item] of layers.flat().entries()) {
    item.lines = wrapLabel(`知识点 ${index + 1} · ${item.node.label}`, 284);
    item.height = 82 + item.lines.length * 24;
  }
  const gap = 42;
  const layerWidths = layers.map(layer => layer.reduce((sum, item) => sum + item.slotWidth, 0) + (layer.length - 1) * gap);
  const width = Math.max(400, ...layerWidths) + 48;
  let nextY = 32;
  layers.forEach((layer, index) => {
    const gateSpace = index === 0 ? 0 : (layer.some(item => item.node.prerequisite_sets.length > 1) ? 104 : 70);
    const nodeY = nextY + gateSpace;
    let nextX = (width - layerWidths[index]) / 2;
    for (const item of layer) {
      const center = nextX + item.slotWidth / 2;
      const gates = item.node.prerequisite_sets.map((group, groupIndex, groups) => ({
        group, groupIndex,
        x: center + (groupIndex - (groups.length - 1) / 2) * 86,
        y: nodeY - (groups.length > 1 ? 82 : 42),
      }));
      positions.set(item.node.id, { ...item, x: center - 160, y: nodeY, center, gates });
      nextX += item.slotWidth + gap;
    }
    nextY = nodeY + Math.max(...layer.map(item => item.height)) + 48;
  });
  return { width, height: nextY, positions, orderedIds };
}

function nodeNumber(id) {
  const index = layout?.orderedIds.indexOf(id) ?? -1;
  return index >= 0 ? index + 1 : null;
}

function numberedNodeLabel(id, label = nodeById.get(id)?.label || "") {
  const number = nodeNumber(id);
  return number === null ? label : `知识点 ${number} · ${label}`;
}

function installGraph(value, states, source, restored = false) {
  const validated = validateGraph(value);
  const validatedMastery = validateMastery(Object.fromEntries(states), validated);
  const nextLayout = buildLayout(validated);
  // 验证和布局完成后才替换旧图；失败时旧图及掌握标记保持可用。
  ++planVersion;
  planController?.abort();
  closeLesson(false);
  lessonCache.clear();
  graph = validated;
  nodeById = new Map(graph.nodes.map(node => [node.id, node]));
  layout = nextLayout;
  mastery = validatedMastery;
  refreshKnownIds();
  graphSource = source;
  bookCache.clear();
  resetChatForHistory();
  plan = null;
  pending = false;
  zoomMode = "width";
  ui.target.textContent = nodeById.get(graph.target_id).label;
  ui.source.textContent = `${restored ? "从本机恢复 · " : ""}${source === "example" ? "审核过的离线样例" : "模型生成的学习图，请核对知识点与先修关系"}`;
  ui.storageButton.disabled = false;
  ui.export.disabled = false;
  ui.nodeSearch.value = "";
  ui.viewport.scrollTop = 0;
  ui.viewport.scrollLeft = 0;
  setPlanError("");
  if (!restored) saveWorkspace();
  renderStudyGoal();
  renderReviews();
  requestPlan();
}

function nodeState(id, ready, blocked) {
  if (knownIds.has(id)) return { name: "known", label: "自行标记全部掌握" };
  const partial = MASTERY_DIMENSIONS.filter(key => mastery.get(id)?.[key]).length;
  const suffix = partial ? ` · 自行标记 ${partial}/3 项` : "";
  if (pending) return { name: "neutral", label: `正在更新…${suffix}` };
  if (ready.has(id)) return { name: "ready", label: `当前可学${suffix}` };
  if (blocked.has(id)) return { name: "blocked", label: `先修未满足${suffix}` };
  return { name: "neutral", label: `${plan ? "未标记掌握" : "等待重算"}${suffix}` };
}

function setView(mode, chosen = false) {
  viewMode = mode;
  if (chosen) viewChosen = true;
  ui.workspace.classList.toggle("list-view", mode === "list");
  ui.viewport.hidden = mode !== "graph";
  ui.graphToolbar.hidden = mode !== "graph";
  ui.nodeBrowser.hidden = mode !== "list";
  ui.graphView.setAttribute("aria-pressed", String(mode === "graph"));
  ui.listView.setAttribute("aria-pressed", String(mode === "list"));
  if (mode === "graph") applyZoom();
  else renderNodeBrowser();
  if (chosen) saveWorkspace();
}

function renderNodeBrowser() {
  const focusedId = ui.nodeList.contains(document.activeElement)
    ? document.activeElement.getAttribute("data-node-id") : null;
  const query = ui.nodeSearch.value.trim().toLocaleLowerCase();
  const ready = new Set(plan?.ready_ids || []);
  const blocked = new Set(plan?.blocked_ids || []);
  const recommendations = new Set(plan?.recommended_ids || []);
  const selected = new Set(plan?.selected_ids || []);
  ui.nodeList.setAttribute("role", "list");
  ui.nodeList.replaceChildren();
  for (const id of layout?.orderedIds || []) {
    const node = nodeById.get(id);
    if (!node.label.toLocaleLowerCase().includes(query)) continue;
    const state = nodeState(id, ready, blocked);
    const partial = !knownIds.has(id) && MASTERY_DIMENSIONS.some(key => mastery.get(id)?.[key]);
    const recommended = !plan?.completed && (recommendations.has(id) || selected.has(id));
    const item = document.createElement("div");
    item.setAttribute("role", "listitem");
    item.className = `node-browser-item ${state.name}${partial ? " partial" : ""}${recommended ? " recommended" : ""}${id === graph.target_id ? " target" : ""}${id === activeLessonId ? " active-lesson-node" : ""}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "node-browser-button";
    button.setAttribute("data-node-id", id);
    button.setAttribute("aria-controls", "lesson-panel");
    button.setAttribute("aria-expanded", String(id === activeLessonId));
    const label = document.createElement("span");
    label.className = "node-browser-label";
    label.textContent = numberedNodeLabel(id);
    const status = document.createElement("span");
    status.className = "node-browser-state";
    const labels = [state.label];
    if (id === graph.target_id) labels.push("学习目标");
    if (recommendations.has(id) && !plan?.completed) labels.push(id === plan.focus_id ? "建议先从这里学" : "建议先学");
    else if (recommended) labels.push("推荐路线");
    status.textContent = labels.join(" · ");
    button.setAttribute("aria-label", `${numberedNodeLabel(id)}，${status.textContent}。打开学习卡。`);
    button.append(label, status);
    button.addEventListener("click", () => openLesson(id, button));
    item.append(button);
    ui.nodeList.append(item);
  }
  if (!ui.nodeList.children.length) {
    const empty = document.createElement("p");
    empty.className = "empty-message";
    empty.textContent = graph ? "没有匹配的知识点，试试其他名称。" : "载入学习图后即可查找知识点。";
    ui.nodeList.append(empty);
  }
  if (focusedId && viewMode === "list") findNodeButton(ui.nodeList, focusedId)?.focus({ preventScroll: true });
}

function renderProgress() {
  const total = graph?.nodes.length || 0;
  const partial = [...mastery].filter(([id, state]) => !knownIds.has(id) && MASTERY_DIMENSIONS.some(key => state[key])).length;
  const percent = total ? Math.round(knownIds.size / total * 100) : 0;
  ui.progressSummary.textContent = `自行标记全部掌握 ${knownIds.size} / ${total} 个`;
  ui.progressBar.style.setProperty("--progress", `${percent}%`);
  ui.progressBar.setAttribute("aria-valuemin", "0");
  ui.progressBar.setAttribute("aria-valuemax", String(total || 1));
  ui.progressBar.setAttribute("aria-valuenow", String(knownIds.size));
  ui.progressBar.setAttribute("aria-valuetext", `自行标记全部掌握 ${knownIds.size} / ${total} 个知识点，${percent}%`);
  ui.progressDetail.textContent = `部分标记 ${partial} 个；仅三项全部勾选计入进度。掌握程度由你自行判断。`;
}

function addEdge(parent, sourceX, sourceY, endX, endY, satisfied, selected = false, faded = false, arrow = true) {
  const middleY = (sourceY + endY) / 2;
  const path = svgElement("path", {
    d: `M ${sourceX} ${sourceY} C ${sourceX} ${middleY}, ${endX} ${middleY}, ${endX} ${endY}`,
    class: `dependency-edge${satisfied ? " satisfied" : ""}${selected ? " route-edge" : ""}${faded ? " faded" : ""}`,
  });
  if (arrow) path.setAttribute("marker-end", satisfied ? "url(#arrow-satisfied)" : selected ? "url(#arrow-route)" : "url(#arrow-default)");
  parent.append(path);
}

function addGate(parent, x, y, label, satisfied, width, selected, faded) {
  const gate = svgElement("g", { class: `${selected ? "route-gate" : ""}${faded ? " faded" : ""}` });
  gate.append(svgElement("rect", {
    x: x - width / 2, y: y - 13, width, height: 26, rx: 13,
    class: `gate-card${satisfied ? " satisfied" : ""}`,
  }));
  gate.append(svgElement("text", { x, y: y + .5, class: "gate-label" }, label));
  parent.append(gate);
}

function renderGraph() {
  if (!graph || !layout) return;
  const focusedNode = ui.canvas.contains(document.activeElement)
    ? document.activeElement.getAttribute("data-node-id") : null;
  const ready = new Set(plan?.ready_ids || []);
  const blocked = new Set(plan?.blocked_ids || []);
  const hasSelection = Array.isArray(plan?.selected_ids);
  const selected = new Set(plan?.selected_ids || []);
  const selectedGroups = new Map((plan?.selected_groups || []).map(item => [item.node_id, item.group_index]));
  const svg = svgElement("svg", {
    width: layout.width, height: layout.height,
    viewBox: `0 0 ${layout.width} ${layout.height}`,
    "aria-label": "当前学习目标的先修依赖图",
  });
  const defs = svgElement("defs");
  for (const [id, color] of [["arrow-default", "#becbbf"], ["arrow-satisfied", "#64a77d"], ["arrow-route", "#527a68"]]) {
    const marker = svgElement("marker", { id, markerWidth: 7, markerHeight: 7, refX: 6, refY: 3.5, orient: "auto", markerUnits: "strokeWidth" });
    marker.append(svgElement("path", { d: "M 0 0 L 7 3.5 L 0 7 z", fill: color }));
    defs.append(marker);
  }
  svg.append(defs);
  const edges = svgElement("g");
  const gates = svgElement("g");
  const nodes = svgElement("g");
  svg.append(edges, gates, nodes);

  for (const item of layout.positions.values()) {
    const multipleGroups = item.gates.length > 1;
    const anySatisfied = item.gates.some(gate => gate.group.every(id => knownIds.has(id)));
    for (const gate of item.gates) {
      const satisfied = gate.group.every(id => knownIds.has(id));
      const isSelected = selectedGroups.get(item.node.id) === gate.groupIndex;
      const faded = hasSelection && !isSelected;
      for (const id of gate.group) {
        const source = layout.positions.get(id);
        addEdge(edges, source.center, source.y + source.height, gate.x, gate.y - 13, knownIds.has(id), isSelected, faded);
      }
      addEdge(edges, gate.x, gate.y + 13, item.center, multipleGroups ? item.y - 29 : item.y, satisfied, isSelected, faded);
      addGate(gates, gate.x, gate.y, "全部", satisfied, 56, isSelected, faded);
    }
    if (multipleGroups) {
      addGate(gates, item.center, item.y - 16, "任选一组", anySatisfied, 88, selected.has(item.node.id), hasSelection && !selected.has(item.node.id));
      addEdge(edges, item.center, item.y - 3, item.center, item.y, anySatisfied, selected.has(item.node.id), hasSelection && !selected.has(item.node.id), false);
    }
    const state = nodeState(item.node.id, ready, blocked);
    const isSelected = selected.has(item.node.id);
    const isFocus = item.node.id === plan?.focus_id;
    const group = svgElement("g", {
      transform: `translate(${item.x}, ${item.y})`,
      class: `graph-node ${state.name}${isSelected ? " route-node" : ""}${isFocus ? " focus-node" : ""}${item.node.id === activeLessonId ? " active-lesson-node" : ""}${hasSelection && !isSelected ? " alternative-node" : ""}`,
      role: "button", tabindex: 0,
      "data-node-id": item.node.id,
      "data-node-number": nodeNumber(item.node.id),
      "aria-controls": "lesson-panel",
      "aria-expanded": String(item.node.id === activeLessonId),
      "aria-label": `${numberedNodeLabel(item.node.id)}，${state.label}${isFocus ? "，建议先学" : isSelected ? "，推荐路线" : ""}。打开学习卡。`,
    });
    group.append(svgElement("title", {}, numberedNodeLabel(item.node.id)));
    group.append(svgElement("rect", { width: 320, height: item.height, rx: 12, class: "node-card" }));
    group.append(svgElement("text", { x: 18, y: 26, class: "node-status" }, state.label));
    if (item.node.id === graph.target_id) {
      group.append(svgElement("text", { x: 302, y: 26, "text-anchor": "end", class: "target-tag" }, "学习目标"));
    }
    const label = svgElement("text", { x: 18, y: 53, class: "node-label" });
    item.lines.forEach((line, index) => label.append(svgElement("tspan", { x: 18, y: 53 + index * 24 }, line)));
    group.append(label);
    const footer = [];
    if (isFocus) footer.push("建议先学");
    else if (isSelected && !plan?.completed) footer.push("推荐路线");
    if (item.node.prerequisite_sets.length === 0) footer.push("本图未列出先修");
    if (footer.length) group.append(svgElement("text", { x: 18, y: item.height - 15, class: "node-footnote" }, footer.join(" · ")));
    group.addEventListener("click", () => openLesson(item.node.id, group));
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openLesson(item.node.id, group);
      }
    });
    nodes.append(group);
  }
  ui.canvas.replaceChildren(svg);
  applyZoom();
  if (focusedNode && viewMode === "graph") {
    const replacement = [...nodes.children].find(element => element.getAttribute("data-node-id") === focusedNode);
    replacement?.focus({ preventScroll: true });
  }
}

function applyZoom() {
  if (!graph || !layout || viewMode !== "graph") return;
  const availableWidth = Math.max(180, ui.viewport.clientWidth - 10);
  const availableHeight = Math.max(180, ui.viewport.clientHeight - 10);
  if (zoomMode === "width") zoom = Math.min(1.15, availableWidth / layout.width);
  else if (zoomMode === "all") zoom = Math.min(1, availableWidth / layout.width, availableHeight / layout.height);
  const svg = ui.canvas.querySelector("svg");
  if (svg) {
    svg.setAttribute("width", String(Math.round(layout.width * zoom)));
    svg.setAttribute("height", String(Math.round(layout.height * zoom)));
  }
  ui.zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
  ui.zoomOut.disabled = zoom <= .25;
  ui.zoomIn.disabled = zoom >= 2;
  for (const button of [ui.fitWidth, ui.fitAll, ui.actualSize]) button.disabled = false;
  ui.fitWidth.setAttribute("aria-pressed", String(zoomMode === "width"));
  ui.fitAll.setAttribute("aria-pressed", String(zoomMode === "all"));
  ui.actualSize.setAttribute("aria-pressed", String(zoomMode === "manual" && Math.abs(zoom - 1) < .001));
}

function setZoom(mode, value) {
  if (!graph) return;
  const centerX = (ui.viewport.scrollLeft + ui.viewport.clientWidth / 2) / zoom;
  const centerY = (ui.viewport.scrollTop + ui.viewport.clientHeight / 2) / zoom;
  zoomMode = mode;
  if (value !== undefined) zoom = Math.min(2, Math.max(.25, value));
  applyZoom();
  if (mode === "manual") {
    ui.viewport.scrollLeft = centerX * zoom - ui.viewport.clientWidth / 2;
    ui.viewport.scrollTop = centerY * zoom - ui.viewport.clientHeight / 2;
  } else {
    ui.viewport.scrollLeft = 0;
    ui.viewport.scrollTop = 0;
  }
}

function locateNode(id) {
  const item = layout?.positions.get(id);
  if (!item) return;
  if (viewMode === "list") {
    findNodeButton(ui.nodeList, id)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return;
  }
  // 全图概览可能较小，定位知识点时恢复可读的大小。
  if (zoom < .7) setZoom("manual", 1);
  ui.viewport.scrollIntoView({ block: "nearest", behavior: "smooth" });
  ui.viewport.scrollTo({
    top: Math.max(0, (item.y + item.height / 2) * zoom - ui.viewport.clientHeight / 2),
    left: Math.max(0, item.center * zoom - ui.viewport.clientWidth / 2),
    behavior: "smooth",
  });
  const node = [...ui.canvas.querySelectorAll("[data-node-id]")].find(element => element.getAttribute("data-node-id") === id);
  node?.focus({ preventScroll: true });
}

function addNodeListItem(list, id, focused = false) {
  const item = document.createElement("li");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "node-link";
  button.textContent = numberedNodeLabel(id);
  button.setAttribute("data-node-id", id);
  button.setAttribute("aria-controls", "lesson-panel");
  button.addEventListener("click", () => {
    locateNode(id);
    openLesson(id, button);
  });
  if (focused) {
    item.classList.add("recommended-focus");
    const hint = document.createElement("span");
    hint.className = "recommendation-hint";
    hint.textContent = "建议先从这里开始";
    item.append(hint);
  }
  item.append(button);
  list.append(item);
}

function renderSummary() {
  renderProgress();
  renderNodeBrowser();
  const partialCount = [...mastery].filter(([id, state]) => !knownIds.has(id) && MASTERY_DIMENSIONS.some(key => state[key])).length;
  ui.count.textContent = `自行标记全部掌握 ${knownIds.size} / ${graph?.nodes.length || 0} 个 · 部分标记 ${partialCount} 个`;
  ui.reset.disabled = !graph || ![...mastery.values()].some(state => MASTERY_DIMENSIONS.some(key => state[key]));
  ui.heading.textContent = Array.isArray(plan?.recommended_ids) ? "建议先学" : "现在可以学什么";
  ui.message.classList.toggle("completed", Boolean(plan?.completed));
  ui.neutralLegend.hidden = !plan?.completed;
  ui.routeLegend.hidden = !Array.isArray(plan?.selected_ids) || Boolean(plan?.completed);
  ui.ready.replaceChildren();
  ui.pathList.replaceChildren();
  ui.allReadyList.replaceChildren();
  ui.pathSection.hidden = true;
  ui.allReadySection.hidden = true;
  ui.empty.hidden = true;
  if (pending) ui.message.textContent = "正在根据你的选择更新…";
  else if (!plan) ui.message.textContent = "学习状态尚未计算完成。";
  else if (plan.completed) {
    ui.message.textContent = "按当前模式的自报状态，目标所需能力已标记。请再做一次独立检验。";
    ui.empty.textContent = "其他知识点保留你的原有标记。需要继续探索时，可打开目标学习卡，调整或清除它的掌握标记。";
    ui.empty.hidden = false;
  } else {
    const recommendations = plan.recommended_ids || plan.ready_ids;
    ui.message.textContent = Array.isArray(plan.required_ids)
      ? `推荐路线还需学习 ${plan.required_ids.length} 个知识点，其中 ${recommendations.length} 个现在可学。`
      : `当前有 ${recommendations.length} 个可学知识点。`;
    for (const id of recommendations) addNodeListItem(ui.ready, id, id === plan.focus_id);
    if (recommendations.length === 0) {
      ui.empty.textContent = "暂时没有可学候选。请检查已掌握的知识点标记。";
      ui.empty.hidden = false;
    }
    if (Array.isArray(plan.required_ids) && plan.required_ids.length > 0) {
      ui.pathSection.hidden = false;
      for (const id of plan.required_ids) addNodeListItem(ui.pathList, id);
    }
    if (Array.isArray(plan.recommended_ids) && plan.ready_ids.some(id => !plan.recommended_ids.includes(id))) {
      ui.allReadySection.hidden = false;
      ui.allReadyTitle.textContent = `全部当前可学候选（${plan.ready_ids.length}）`;
      for (const id of plan.ready_ids) addNodeListItem(ui.allReadyList, id);
    }
  }
  if (plan?.explanation) { const p = document.createElement("p"); p.className = "study-note route-explanation"; p.textContent = plan.explanation; ui.ready.append(p); }
}

async function requestPlan() {
  if (!graph) return;
  const version = ++planVersion;
  planController?.abort();
  const controller = new AbortController();
  planController = controller;
  const submittedGraph = graph;
  const submittedIds = graph.nodes.filter(node => knownIds.has(node.id)).map(node => node.id);
  const timer = setTimeout(() => controller.abort(), 20000);
  plan = null;
  pending = true;
  setPlanError("");
  renderGraph();
  renderSummary();
  try {
    const response = await fetch("/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph: submittedGraph, known_ids: submittedIds, mode: ui.studyMode.value, mastery: Object.fromEntries(mastery) }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("http");
    const value = await response.json();
    if (version !== planVersion) return;
    plan = validatePlan(value, submittedIds, submittedGraph);
  } catch {
    if (version !== planVersion) return;
    setPlanError("无法更新学习状态。图和掌握标记已保留，请确认后端正在运行后重试。");
  } finally {
    clearTimeout(timer);
    // 旧图或旧选择的结果、错误、清理都不能覆盖当前状态。
    if (version === planVersion) {
      pending = false;
      renderGraph();
      renderSummary();
    }
  }
}

function requireLessonFields(value, required, optional = []) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      required.some(key => !Object.hasOwn(value, key)) ||
      Object.keys(value).some(key => !required.includes(key) && !optional.includes(key))) {
    throw new Error("invalid-lesson");
  }
}

function validateLessonText(value, maximum) {
  if (typeof value !== "string" || !value.trim() || Array.from(value).length > maximum) {
    throw new Error("invalid-lesson");
  }
  return value;
}

function validateIllustration(value) {
  if (value === null) return null;
  requireLessonFields(value, ["title", "caption", "alt", "elements"]);
  validateLessonText(value.title, 100);
  validateLessonText(value.caption, 700);
  validateLessonText(value.alt, 500);
  if (!Array.isArray(value.elements) || value.elements.length < 1 || value.elements.length > 60) {
    throw new Error("invalid-lesson");
  }
  const coordinate = (number, maximum) => {
    if (typeof number !== "number" || !Number.isFinite(number) || number < 0 || number > maximum) {
      throw new Error("invalid-lesson");
    }
    return number;
  };
  const fields = {
    line: ["type", "x1", "y1", "x2", "y2", "tone", "arrow", "dashed"],
    circle: ["type", "cx", "cy", "r", "tone", "fill"],
    polygon: ["type", "points", "tone", "fill"],
    text: ["type", "x", "y", "text", "tone", "anchor"],
  };
  const elements = value.elements.map(element => {
    if (!element || typeof element.type !== "string" || !Object.hasOwn(fields, element.type)) throw new Error("invalid-lesson");
    requireLessonFields(element, fields[element.type]);
    if (!["ink", "green", "blue", "muted"].includes(element.tone)) throw new Error("invalid-lesson");
    const tone = element.tone;
    if (element.type === "line") {
      if (typeof element.arrow !== "boolean" || typeof element.dashed !== "boolean") throw new Error("invalid-lesson");
      return { type: "line", x1: coordinate(element.x1, 640), y1: coordinate(element.y1, 360),
        x2: coordinate(element.x2, 640), y2: coordinate(element.y2, 360), tone, arrow: element.arrow, dashed: element.dashed };
    }
    if (element.type === "circle") {
      if (typeof element.fill !== "boolean" || typeof element.r !== "number" ||
          !Number.isFinite(element.r) || element.r < 1 || element.r > 150) throw new Error("invalid-lesson");
      return { type: "circle", cx: coordinate(element.cx, 640), cy: coordinate(element.cy, 360), r: element.r, tone, fill: element.fill };
    }
    if (element.type === "polygon") {
      if (typeof element.fill !== "boolean" || !Array.isArray(element.points) ||
          element.points.length < 3 || element.points.length > 12) throw new Error("invalid-lesson");
      const points = element.points.map(point => {
        if (!Array.isArray(point) || point.length !== 2) throw new Error("invalid-lesson");
        return [coordinate(point[0], 640), coordinate(point[1], 360)];
      });
      return { type: "polygon", points, tone, fill: element.fill };
    }
    validateLessonText(element.text, 50);
    if (!["start", "middle", "end"].includes(element.anchor)) throw new Error("invalid-lesson");
    return { type: "text", x: coordinate(element.x, 640), y: coordinate(element.y, 360), text: element.text, tone, anchor: element.anchor };
  });
  return { title: value.title, caption: value.caption, alt: value.alt, elements };
}

function validateFollowupExercises(value) {
  if (!Array.isArray(value) || value.length > 3) throw new Error("invalid-lesson");
  return value.map(exercise => {
    requireLessonFields(exercise, ["level", "question", "hint", "answer"]);
    if (!["basic", "challenge"].includes(exercise.level)) throw new Error("invalid-lesson");
    return { level: exercise.level, question: validateLessonText(exercise.question, 600),
      hint: validateLessonText(exercise.hint, 500), answer: validateLessonText(exercise.answer, 1400) };
  });
}

function validateLesson(value, id) {
  requireLessonFields(value, ["node_id", "title", "definition", "intuition", "example", "proof_idea", "exercise", "source"],
    ["followup_exercises", "illustration", "math_context", "source_notes", "learning_tasks"]);
  if (value.node_id !== id || !["curated_example", "generated"].includes(value.source)) {
    throw new Error("invalid-lesson");
  }
  const textLimits = { title: 120, definition: 700, intuition: 1000, example: 1200, proof_idea: 1000 };
  for (const [key, maximum] of Object.entries(textLimits)) {
    if (typeof value[key] !== "string" || !value[key].trim() || Array.from(value[key]).length > maximum) {
      throw new Error("invalid-lesson");
    }
  }
  const exercise = value.exercise;
  requireLessonFields(exercise, ["question", "options", "correct_index", "explanation", "dimension"]);
  if (!exercise || typeof exercise.question !== "string" || !exercise.question.trim() ||
      Array.from(exercise.question).length > 500 || typeof exercise.explanation !== "string" ||
      !exercise.explanation.trim() || Array.from(exercise.explanation).length > 800 ||
      !Array.isArray(exercise.options) || exercise.options.length !== 4 ||
      exercise.options.some(option => typeof option !== "string" || !option.trim() || Array.from(option).length > 350) ||
      !Number.isInteger(exercise.correct_index) || exercise.correct_index < 0 || exercise.correct_index > 3 ||
      !MASTERY_DIMENSIONS.includes(exercise.dimension)) throw new Error("invalid-lesson");
  if (new Set(exercise.options.map(option => option.trim().toLowerCase())).size !== 4) throw new Error("invalid-lesson");
  if (value.math_context !== undefined && (typeof value.math_context !== "string" || value.math_context.length > 1500)) throw new Error("invalid-lesson");
  if (value.source_notes !== undefined && (!Array.isArray(value.source_notes) || value.source_notes.length > 6 || value.source_notes.some(source =>
    !source || typeof source.title !== "string" || typeof source.url !== "string" || typeof source.locator !== "string" || !["curated", "unverified"].includes(source.review_status)))) throw new Error("invalid-lesson");
  if (value.learning_tasks !== undefined && (!Array.isArray(value.learning_tasks) || value.learning_tasks.length > 8)) throw new Error("invalid-lesson");
  return { ...value,
    math_context: value.math_context || "", source_notes: (value.source_notes || []).map(source => ({ title: source.title, url: source.url, locator: source.locator, review_status: source.review_status })),
    learning_tasks: (value.learning_tasks || []).map(task => validateTask(task, new Set([id]))),
    followup_exercises: validateFollowupExercises(Object.hasOwn(value, "followup_exercises") ? value.followup_exercises : []),
    illustration: validateIllustration(Object.hasOwn(value, "illustration") ? value.illustration : null),
  };
}

function renderMastery() {
  if (!activeLessonId || !nodeById.has(activeLessonId)) return;
  const state = mastery.get(activeLessonId) || emptyMastery();
  for (const key of MASTERY_DIMENSIONS) ui.masteryChecks[key].checked = state[key];
  const missing = MASTERY_DIMENSIONS.filter(key => !state[key]);
  ui.masteryAll.disabled = missing.length === 0;
  ui.masteryClear.disabled = missing.length === 3;
  ui.masteryHint.textContent = missing.length === 0
    ? "三项已自行标记掌握，此节点会用于满足先修。"
    : `尚未标记：${missing.map(key => DIMENSION_LABELS[key]).join("、")}。当前路线按学习目的所需能力判断先修；自报与独立作答证据分开。`;
  updateExerciseMark();
  refreshPrerequisiteStatus();
}

function updateMastery(id, patch) {
  if (!nodeById.has(id)) return;
  const state = { ...(mastery.get(id) || emptyMastery()), ...patch };
  if (MASTERY_DIMENSIONS.some(key => state[key])) mastery.set(id, state);
  else mastery.delete(id);
  refreshKnownIds();
  renderMastery();
  renderBookGuidance();
  saveWorkspace();
  requestPlan();
}

function setLessonError(message) {
  ui.lessonErrorText.textContent = message;
  ui.lessonError.hidden = !message;
}

function clearPrerequisitePreviews() {
  ++prerequisiteVersion;
  for (const request of prerequisiteRequests.values()) request.controller?.abort();
  prerequisiteRequests.clear();
  prerequisiteViews = [];
  prerequisiteGroupViews = [];
  ui.prerequisiteGroups.replaceChildren();
  ui.prerequisiteRule.textContent = "";
}

function prerequisiteViewIsCurrent(view) {
  return view.version === prerequisiteVersion && view.parentId === activeLessonId &&
    view.graph === graph && !ui.lessonPanel.hidden && ui.prerequisiteGroups.contains(view.element);
}

function refreshPrerequisiteStatus() {
  for (const view of prerequisiteViews) {
    if (!prerequisiteViewIsCurrent(view)) continue;
    const state = mastery.get(view.id) || emptyMastery();
    const marked = MASTERY_DIMENSIONS.filter(key => state[key]);
    view.state.textContent = marked.length === 3
      ? "自报状态：自行标记全部掌握（3/3）"
      : marked.length
        ? `自报状态：已标记 ${marked.map(key => DIMENSION_LABELS[key]).join("、")}（${marked.length}/3）`
        : "自报状态：尚未标记掌握（0/3）";
  }
  for (const view of prerequisiteGroupViews) {
    view.status.textContent = view.ids.every(id => knownIds.has(id))
      ? "此组已全部自行标记掌握。" : "此组尚有未全部标记掌握的内容。";
  }
}

function prerequisiteExcerpt(value) {
  const characters = Array.from(value);
  return characters.length <= 360 ? value : `${characters.slice(0, 360).join("")}…（完整内容见学习卡）`;
}

function renderPrerequisitePreview(view) {
  if (!prerequisiteViewIsCurrent(view)) return;
  view.button.setAttribute("aria-expanded", String(view.expanded));
  view.button.textContent = view.expanded ? "收起简要讲解" : "展开简要讲解";
  view.preview.hidden = !view.expanded;
  if (!view.expanded) return;
  const entry = lessonCache.get(view.id);
  const request = prerequisiteRequests.get(view.id);
  view.preview.setAttribute("aria-busy", String(Boolean(!entry && request?.loading)));
  view.error.hidden = !request?.error || Boolean(entry);
  view.error.textContent = entry ? "" : request?.error || "";
  view.retry.hidden = view.error.hidden;
  view.retry.disabled = Boolean(request?.loading);
  view.content.hidden = !entry;
  if (entry) {
    if (view.entry !== entry) {
      view.content.replaceChildren();
      for (const [key, label] of [["definition", "定义"], ["intuition", "直觉"], ["example", "具体例子"]]) {
        const heading = document.createElement("h5");
        heading.textContent = label;
        const text = document.createElement("p");
        text.textContent = prerequisiteExcerpt(entry.lesson[key]);
        view.content.append(heading, text);
      }
      view.entry = entry;
    }
    view.status.textContent = entry.lesson.source === "generated"
      ? "模型生成的简要讲解，请核对数学内容。" : "已载入简要讲解；完整内容可在学习卡中查看。";
  } else {
    view.status.textContent = request?.loading ? "正在载入简要讲解，可能需要几十秒。" : "";
  }
}

function renderPrerequisites() {
  const node = nodeById.get(activeLessonId);
  if (!node) return;
  ui.prerequisiteRule.textContent = node.prerequisite_sets.length === 0
    ? "本图未列出先修内容；这不表示你已经掌握。"
    : node.prerequisite_sets.length > 1
      ? "任选一组（OR）；每组内部的内容都需掌握（AND）。可按需展开简要讲解。"
      : "以下内容需全部掌握（AND）。可按需展开简要讲解。";
  for (const [groupIndex, ids] of node.prerequisite_sets.entries()) {
    const group = document.createElement("section");
    group.className = "prerequisite-group";
    const heading = document.createElement("h4");
    heading.textContent = `先修组 ${groupIndex + 1} · 组内全部（AND）`;
    const groupStatus = document.createElement("p");
    groupStatus.className = "prerequisite-group-status";
    if (node.branch_outcomes?.[groupIndex]) { const p = document.createElement("p"); p.className = "study-note"; mathText(p, `这条路线能达到：${node.branch_outcomes[groupIndex]}`); group.append(p); }
    const list = document.createElement("ul");
    list.className = "prerequisite-list";
    for (const id of ids) {
      const row = document.createElement("li");
      row.className = "prerequisite-item";
      row.setAttribute("data-prerequisite-id", id);
      const title = document.createElement("p");
      title.className = "prerequisite-label";
      title.textContent = numberedNodeLabel(id);
      const state = document.createElement("p");
      state.className = "prerequisite-state";
      const actions = document.createElement("div");
      actions.className = "prerequisite-actions";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tool-button prerequisite-toggle";
      const fullCard = document.createElement("button");
      fullCard.type = "button";
      fullCard.className = "text-button prerequisite-open";
      fullCard.textContent = "打开完整学习卡";
      fullCard.setAttribute("aria-label", `打开${numberedNodeLabel(id)}的完整学习卡`);
      fullCard.addEventListener("click", () => openLesson(id, fullCard));
      const preview = document.createElement("div");
      const previewId = `prerequisite-preview-${prerequisiteVersion}-${groupIndex}-${id}`;
      preview.setAttribute("id", previewId);
      preview.className = "prerequisite-preview";
      preview.hidden = true;
      button.setAttribute("aria-controls", previewId);
      const status = document.createElement("p");
      status.className = "prerequisite-preview-status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      const error = document.createElement("p");
      error.className = "prerequisite-error";
      error.setAttribute("role", "alert");
      error.hidden = true;
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "tool-button prerequisite-retry";
      retry.textContent = "重试简要讲解";
      retry.hidden = true;
      const content = document.createElement("div");
      content.className = "prerequisite-preview-content";
      content.hidden = true;
      preview.append(status, error, retry, content);
      actions.append(button, fullCard);
      row.append(title, state, actions, preview);
      const parent = nodeById.get(id);
      if (parent.rationale || parent.required_abilities?.length || parent.required_dimensions?.length) {
        const why = document.createElement("p"); why.className = "study-note";
        mathText(why, `${parent.rationale || "本图将其列为先修。"}${parent.required_abilities?.length ? ` 所需能力：${parent.required_abilities.join("；")}` : ""}${parent.required_dimensions?.length ? ` 本路线自报要求：${parent.required_dimensions.map(key => DIMENSION_LABELS[key]).join("、")}` : ""}`);
        row.append(why);
      }
      const view = { id, parentId: activeLessonId, graph, version: prerequisiteVersion,
        element: row, state, button, preview, status, error, retry, content, expanded: false, entry: null };
      button.addEventListener("click", () => {
        if (!prerequisiteViewIsCurrent(view)) return;
        view.expanded = !view.expanded;
        renderPrerequisitePreview(view);
        if (view.expanded && !lessonCache.has(id) && !prerequisiteRequests.has(id)) requestPrerequisite(view);
      });
      retry.addEventListener("click", () => requestPrerequisite(view));
      prerequisiteViews.push(view);
      list.append(row);
    }
    group.append(heading, groupStatus, list);
    ui.prerequisiteGroups.append(group);
    prerequisiteGroupViews.push({ ids, status: groupStatus });
  }
  refreshPrerequisiteStatus();
  for (const view of prerequisiteViews) renderPrerequisitePreview(view);
}

async function requestPrerequisite(view) {
  if (!prerequisiteViewIsCurrent(view) || !view.expanded || prerequisiteRequests.get(view.id)?.loading) return;
  if (lessonCache.has(view.id)) {
    renderPrerequisitePreview(view);
    return;
  }
  const id = view.id;
  const controller = new AbortController();
  const request = { controller, version: prerequisiteVersion, parentId: activeLessonId, graph, loading: true, error: "" };
  prerequisiteRequests.set(id, request);
  const current = () => request.version === prerequisiteVersion && request.parentId === activeLessonId &&
    request.graph === graph && !ui.lessonPanel.hidden && prerequisiteRequests.get(id) === request;
  const refresh = () => {
    for (const candidate of prerequisiteViews) if (candidate.id === id) renderPrerequisitePreview(candidate);
  };
  refresh();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 150000);
  try {
    const response = await fetch("/lesson", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph: request.graph, node_id: id }), signal: controller.signal,
    });
    if (!response.ok) {
      const error = new Error("prerequisite-request-failed");
      error.userMessage = await lessonResponseFailure(response);
      throw error;
    }
    const value = await response.json();
    if (!current()) return;
    const lesson = validateLesson(value, id);
    lessonCache.set(id, { lesson, choice: null, answer: null });
    saveWorkspace();
  } catch (error) {
    if (!current()) return;
    request.error = error.userMessage || (timedOut
      ? "简要讲解请求时间较长，请稍后重试。"
      : error.message === "invalid-lesson"
        ? "简要讲解格式没有通过检查，请重试。"
        : "暂时无法载入这项先修讲解，请重试。");
  } finally {
    clearTimeout(timer);
    if (current()) {
      request.loading = false;
      refresh();
    }
  }
}

function findNodeButton(container, id) {
  return [...container.querySelectorAll("[data-node-id]")].find(element => element.getAttribute("data-node-id") === id);
}

function clearBackgroundInert() {
  for (const [element, previous] of inertBackground) element.inert = previous;
  inertBackground.clear();
}

function syncLessonMode() {
  clearBackgroundInert();
  const opened = Boolean(activeLessonId) && !ui.lessonPanel.hidden;
  const modal = opened && narrowScreen.matches;
  ui.workspace.classList.toggle("lesson-open", opened);
  document.body.classList.toggle("lesson-modal-open", modal);
  ui.lessonPanel.setAttribute("role", modal ? "dialog" : "region");
  if (modal) {
    ui.lessonPanel.setAttribute("aria-modal", "true");
    // 沿学习卡到 body 的路径禁用兄弟区域，保留卡自身以及它的父容器。
    let current = ui.lessonPanel;
    while (current.parentElement) {
      const parent = current.parentElement;
      for (const sibling of parent.children) {
        if (sibling === current) continue;
        inertBackground.set(sibling, Boolean(sibling.inert));
        sibling.inert = true;
      }
      if (parent === document.body) break;
      current = parent;
    }
    if (!ui.lessonPanel.contains(document.activeElement)) ui.lessonTitle.focus({ preventScroll: true });
  } else {
    ui.lessonPanel.removeAttribute("aria-modal");
  }
  syncChatVisibility();
  applyZoom();
}

function lessonFocusableElements() {
  return [...ui.lessonPanel.querySelectorAll('button, [href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])')]
    .filter(element => {
      if (element.disabled || element.closest("[hidden]") || element.getClientRects().length === 0) return false;
      const collapsed = element.closest("details:not([open])");
      return !collapsed || (element.tagName === "SUMMARY" && element.parentElement === collapsed);
    });
}

function handleLessonKeyboard(event) {
  if (!activeLessonId || ui.lessonPanel.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeLesson();
    return;
  }
  if (event.key !== "Tab" || !narrowScreen.matches) return;
  const focusable = lessonFocusableElements();
  if (!focusable.length) {
    event.preventDefault();
    ui.lessonTitle.focus({ preventScroll: true });
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const current = document.activeElement;
  if (!focusable.includes(current) || (event.shiftKey ? current === first : current === last)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus({ preventScroll: true });
  }
}

function renderLessonNavigation() {
  const ordered = layout?.orderedIds || [];
  const index = ordered.indexOf(activeLessonId);
  ui.lessonPrevious.disabled = index <= 0;
  ui.lessonNext.disabled = index < 0 || index >= ordered.length - 1;
  const previous = index > 0 ? nodeById.get(ordered[index - 1]) : null;
  const next = index >= 0 && index < ordered.length - 1 ? nodeById.get(ordered[index + 1]) : null;
  ui.lessonPrevious.setAttribute("aria-label", previous ? `上一个知识点：${numberedNodeLabel(previous.id)}` : "已是第一个知识点");
  ui.lessonNext.setAttribute("aria-label", next ? `下一个知识点：${numberedNodeLabel(next.id)}` : "已是最后一个知识点");
}

function navigateLesson(direction) {
  const ordered = layout?.orderedIds || [];
  const index = ordered.indexOf(activeLessonId);
  const next = ordered[index + direction];
  if (index >= 0 && next) openLesson(next);
}

function closeLesson(restoreFocus = true) {
  const previousId = activeLessonId;
  ++lessonVersion;
  lessonController?.abort();
  lessonController = null;
  lessonLoading = false;
  clearPrerequisitePreviews();
  activeLessonId = null;
  ++bookLessonVersion; ui.lessonBooks.hidden = true;
  ui.lessonPanel.hidden = true;
  clearLessonEnrichment();
  ui.lessonPanel.setAttribute("aria-busy", "false");
  syncLessonMode();
  renderLessonNavigation();
  if (graph) {
    renderGraph();
    renderNodeBrowser();
  }
  if (restoreFocus && previousId) {
    const original = lessonOpener?.isConnected && !lessonOpener.closest("[hidden]") ? lessonOpener : null;
    const replacement = lessonOpenerContainer && lessonOpenerId
      ? findNodeButton(lessonOpenerContainer, lessonOpenerId) : null;
    const visible = [original, replacement].find(element => element && !element.closest("[hidden]") && !element.closest("[inert]"));
    const fallback = findNodeButton(viewMode === "list" ? ui.nodeList : ui.canvas, lessonOpenerId || previousId);
    (visible || fallback || ui.input).focus({ preventScroll: true });
  }
  lessonOpener = null;
  lessonOpenerContainer = null;
  lessonOpenerId = null;
}

function openLesson(id, opener = document.activeElement) {
  if (!nodeById.has(id)) return;
  if (activeLessonId === id && !ui.lessonPanel.hidden) {
    ui.lessonTitle.focus({ preventScroll: true });
    return;
  }
  if (opener && !ui.lessonPanel.contains(opener)) {
    lessonOpener = opener;
    lessonOpenerId = opener.getAttribute("data-node-id") || id;
    lessonOpenerContainer = [ui.canvas, ui.nodeList, ui.ready, ui.pathList, ui.allReadyList].find(container => container.contains(opener)) || null;
  }
  ++lessonVersion;
  lessonController?.abort();
  lessonController = null;
  lessonLoading = false;
  clearPrerequisitePreviews();
  activeLessonId = id;
  ui.lessonPanel.hidden = false;
  ui.lessonTitle.textContent = numberedNodeLabel(id);
  ui.lessonSource.textContent = "";
  ui.lessonStatus.textContent = "";
  ui.lessonContent.hidden = true;
  clearLessonEnrichment();
  setLessonError("");
  ui.lessonPanel.querySelector(".lesson-body").scrollTop = 0;
  syncLessonMode();
  renderLessonNavigation();
  renderMastery();
  renderPrerequisites();
  ui.lessonNotes.value = studyState.notes[id] || "";
  renderEvidence();
  renderBookGuidance();
  saveWorkspace();
  renderGraph();
  renderNodeBrowser();
  ui.lessonTitle.focus({ preventScroll: true });
  const cached = lessonCache.get(id);
  if (cached) renderLesson(cached);
  else requestLesson(id);
}

function renderExerciseFeedback(entry) {
  const answered = Number.isInteger(entry.answer);
  ui.exerciseFeedback.hidden = !answered;
  ui.exerciseExplanation.hidden = !answered;
  ui.exerciseMark.hidden = !answered || entry.answer !== entry.lesson.exercise.correct_index;
  if (answered) {
    const correct = entry.answer === entry.lesson.exercise.correct_index;
    ui.exerciseFeedback.textContent = correct
      ? "与本卡参考答案一致。你可以自行判断是否标记这一项掌握。"
      : "与本卡参考答案不同。可以结合下面的解释再试一次，已有掌握标记保留。";
    ui.exerciseFeedback.classList.toggle("correct", correct);
    ui.exerciseExplanation.textContent = entry.lesson.exercise.explanation;
  }
  updateExerciseMark();
}

function updateExerciseMark() {
  const entry = lessonCache.get(activeLessonId);
  if (!entry || !Number.isInteger(entry.answer) || entry.answer !== entry.lesson.exercise.correct_index) {
    ui.exerciseMark.hidden = true;
    return;
  }
  const dimension = entry.lesson.exercise.dimension;
  const marked = Boolean(mastery.get(activeLessonId)?.[dimension]);
  ui.exerciseMark.hidden = false;
  ui.exerciseMark.disabled = marked;
  ui.exerciseMark.textContent = marked ? `已自行标记“${DIMENSION_LABELS[dimension]}”` : `自行标记“${DIMENSION_LABELS[dimension]}”`;
}

function setIllustrationZoom(enlarged) {
  ui.illustrationViewport.classList.toggle("enlarged", enlarged);
  ui.illustrationZoom.setAttribute("aria-pressed", String(enlarged));
  ui.illustrationZoom.textContent = enlarged ? "适配卡片" : "放大查看";
  if (!enlarged) {
    ui.illustrationViewport.scrollLeft = 0;
    ui.illustrationViewport.scrollTop = 0;
  }
}

function clearLessonEnrichment() {
  for (const element of ui.illustrationSection.querySelectorAll(".interactive-homology")) element.remove();
  ui.adaptivePracticeTasks.replaceChildren();
  ui.adaptivePracticeTasks.setAttribute("data-task-request", uuid());
  ui.targetedHelpActions.replaceChildren();
  ui.targetedHelpResult.replaceChildren();
  ui.illustrationSection.hidden = true;
  ui.illustrationViewport.replaceChildren();
  ui.illustrationTitle.textContent = "";
  ui.illustrationCaption.textContent = "";
  ui.illustrationViewport.scrollLeft = 0;
  ui.illustrationViewport.scrollTop = 0;
  setIllustrationZoom(false);
  ui.followupSection.hidden = true;
  ui.followupList.replaceChildren();
}

function renderIllustration(illustration) {
  if (!illustration) return;
  // 数据只描述图元；标签、属性、颜色和尺寸都由这里固定，不读取 SVG/HTML 或 URL。
  const tones = { ink: "#233d31", green: "#2d7750", blue: "#2b669d", muted: "#627568" };
  const svg = svgElement("svg", {
    viewBox: "0 0 640 360", width: 640, height: 360, class: "lesson-illustration",
    role: "img", "aria-labelledby": "lesson-illustration-svg-title", "aria-describedby": "lesson-illustration-svg-description",
    preserveAspectRatio: "xMidYMid meet",
  });
  svg.append(svgElement("title", { id: "lesson-illustration-svg-title" }, illustration.title),
    svgElement("desc", { id: "lesson-illustration-svg-description" }, illustration.alt));
  for (const element of illustration.elements) {
    const color = tones[element.tone];
    const stroke = { stroke: color, "stroke-width": 2.5, "stroke-linecap": "round", "stroke-linejoin": "round" };
    if (element.type === "line") {
      const attributes = { x1: element.x1, y1: element.y1, x2: element.x2, y2: element.y2, ...stroke };
      if (element.dashed) attributes["stroke-dasharray"] = "8 7";
      svg.append(svgElement("line", attributes));
      if (element.arrow) {
        const distance = Math.hypot(element.x2 - element.x1, element.y2 - element.y1);
        if (distance > 0) {
          const ux = (element.x2 - element.x1) / distance;
          const uy = (element.y2 - element.y1) / distance;
          const length = Math.min(12, distance / 2);
          const width = length / 2;
          const baseX = element.x2 - ux * length;
          const baseY = element.y2 - uy * length;
          const points = [[element.x2, element.y2], [baseX - uy * width, baseY + ux * width], [baseX + uy * width, baseY - ux * width]];
          svg.append(svgElement("polygon", { points: points.map(point => point.join(",")).join(" "), fill: color }));
        }
      }
    } else if (element.type === "circle") {
      svg.append(svgElement("circle", { cx: element.cx, cy: element.cy, r: element.r,
        ...stroke, fill: element.fill ? color : "none", "fill-opacity": element.fill ? .14 : 1 }));
    } else if (element.type === "polygon") {
      svg.append(svgElement("polygon", { points: element.points.map(point => point.join(",")).join(" "),
        ...stroke, fill: element.fill ? color : "none", "fill-opacity": element.fill ? .14 : 1 }));
    } else if (element.type === "text") {
      svg.append(svgElement("text", { x: element.x, y: element.y, fill: color, "text-anchor": element.anchor,
        "font-size": 24 }, element.text));
    }
  }
  ui.illustrationTitle.textContent = illustration.title;
  ui.illustrationCaption.textContent = illustration.caption;
  ui.illustrationViewport.append(svg);
  ui.illustrationSection.hidden = false;
}

function renderFollowupExercises(exercises) {
  if (!exercises?.length) return;
  for (const [index, exercise] of exercises.entries()) {
    const item = document.createElement("li");
    item.className = "followup-item";
    const heading = document.createElement("h4");
    heading.className = "followup-title";
    heading.textContent = `第 ${index + 1} 题 · ${exercise.level === "basic" ? "基础" : "进阶"}`;
    const question = document.createElement("p");
    question.className = "followup-question";
    question.textContent = exercise.question;
    item.append(heading, question);
    for (const [key, label] of [["hint", "提示"], ["answer", "参考答案"]]) {
      const details = document.createElement("details");
      details.className = `followup-support followup-${key}`;
      const summary = document.createElement("summary");
      summary.textContent = label;
      const content = document.createElement("p");
      content.textContent = exercise[key];
      details.append(summary, content);
      item.append(details);
    }
    ui.followupList.append(item);
  }
  ui.followupSection.hidden = false;
}

function renderLesson(entry) {
  const lesson = entry.lesson;
  clearLessonEnrichment();
  ui.lessonPanel.setAttribute("aria-busy", "false");
  ui.lessonTitle.textContent = numberedNodeLabel(activeLessonId, lesson.title);
  ui.lessonSource.textContent = lesson.source === "curated_example"
    ? "已审核的离线样例学习卡 · 无需调用模型"
    : "模型生成的学习卡 · 数学内容与参考答案需要核对";
  ui.lessonSource.classList.toggle("generated", lesson.source === "generated");
  if (lesson.math_context) ui.lessonSource.textContent += ` · 数学约定：${lesson.math_context}`;
  ui.lessonStatus.textContent = "学习卡将保存在本机历史中，再次打开会直接恢复。";
  mathText(ui.lessonDefinition, lesson.definition);
  mathText(ui.lessonIntuition, lesson.intuition);
  renderIllustration(lesson.illustration);
  renderInteractiveHomology();
  mathText(ui.lessonExample, lesson.example);
  mathText(ui.lessonProof, lesson.proof_idea);
  const state = mastery.get(activeLessonId) || emptyMastery();
  document.getElementById("lesson-definition-section").open = !state.definition;
  document.getElementById("lesson-intuition-section").open = !state.intuition;
  document.getElementById("lesson-example-section").open = !state.application;
  ui.exerciseQuestion.textContent = lesson.exercise.question;
  ui.exerciseDimension.textContent = `本题对应：${DIMENSION_LABELS[lesson.exercise.dimension]}`;
  ui.exerciseOptions.replaceChildren();
  lesson.exercise.options.forEach((option, index) => {
    const label = document.createElement("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "exercise-answer";
    radio.value = String(index);
    radio.checked = entry.choice === index;
    radio.addEventListener("change", () => {
      entry.choice = index;
      entry.answer = null;
      renderExerciseFeedback(entry);
    });
    const text = document.createElement("span");
    text.textContent = `${String.fromCharCode(65 + index)}. ${option}`;
    label.append(radio, text);
    ui.exerciseOptions.append(label);
  });
  renderExerciseFeedback(entry);
  renderFollowupExercises(lesson.followup_exercises);
  renderTargetedHelp();
  loadStudyTasks(ui.adaptivePracticeTasks, "lesson", activeLessonId);
  renderEvidence();
  ui.lessonContent.hidden = false;
  setLessonError("");
}

async function lessonResponseFailure(response) {
  if ([502, 503, 504].includes(response.status)) {
    try {
      const body = await response.json();
      if (typeof body.detail === "string" && body.detail.trim()) {
        return body.detail.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 300);
      }
    } catch { /* 不展示服务器原始输出。 */ }
  }
  return "暂时无法载入学习卡，请稍后重试。";
}

async function requestLesson(id) {
  if (id !== activeLessonId || !graph) return;
  const version = ++lessonVersion;
  lessonController?.abort();
  const controller = new AbortController();
  lessonController = controller;
  const submittedGraph = graph;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 150000);
  lessonLoading = true;
  ui.lessonPanel.setAttribute("aria-busy", "true");
  ui.lessonRetry.disabled = true;
  ui.lessonContent.hidden = true;
  clearLessonEnrichment();
  ui.lessonStatus.textContent = "正在载入学习卡。模型生成可能需要几十秒，你仍可修改掌握标记。";
  setLessonError("");
  try {
    const response = await fetch("/lesson", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph: submittedGraph, node_id: id }), signal: controller.signal,
    });
    if (!response.ok) {
      const error = new Error("lesson-request-failed");
      error.userMessage = await lessonResponseFailure(response);
      throw error;
    }
    const value = await response.json();
    if (version !== lessonVersion || id !== activeLessonId || submittedGraph !== graph) return;
    const lesson = validateLesson(value, id);
    const entry = { lesson, choice: null, answer: null };
    lessonCache.set(id, entry);
    saveWorkspace();
    renderLesson(entry);
  } catch (error) {
    if (version !== lessonVersion || id !== activeLessonId || submittedGraph !== graph) return;
    const message = error.userMessage || (timedOut
      ? "学习卡请求时间较长，暂时没有结果，请稍后重试。"
      : error.message === "invalid-lesson"
        ? "学习卡格式没有通过检查，请重试。"
        : "暂时无法连接后端，请确认服务正在运行后重试。");
    setLessonError(`${message} 当前图和掌握标记仍然保留。`);
    ui.lessonStatus.textContent = "学习卡载入未完成；掌握标记仍可操作。";
  } finally {
    clearTimeout(timer);
    if (version === lessonVersion && id === activeLessonId) {
      lessonLoading = false;
      ui.lessonPanel.setAttribute("aria-busy", "false");
      ui.lessonRetry.disabled = false;
    }
  }
}

async function responseFailure(response, source) {
  if (response.status === 422) return "请输入 1 至 5000 字的有效数学目标或短文本。";
  if (source === "generated" && [502, 503, 504].includes(response.status)) {
    try {
      const body = await response.json();
      if (typeof body.detail === "string" && body.detail.trim()) {
        return body.detail.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 300);
      }
    } catch { /* 未知错误格式使用固定提示，不展示服务器原始输出。 */ }
  }
  return source === "example" ? "暂时无法载入样例，请确认后端正在运行后重试。" : "暂时无法生成学习图，请稍后重试。";
}

let exampleCatalog = [{ id: "homology", title: "同调群为何取商", description: "同调的定义与几何含义", goal: "理解同调群为什么要取商" }];

async function loadExampleCatalog() {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch("/examples", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error("examples-unavailable");
    const items = await response.json();
    if (!Array.isArray(items) || !items.length || items.length > 12) throw new Error("invalid-examples");
    const ids = new Set();
    for (const item of items) {
      requireExactFields(item, ["id", "title", "description", "goal"]);
      if (!/^[a-z][a-z0-9_]{0,59}$/.test(item.id) || ids.has(item.id) ||
          ![item.title, item.description, item.goal].every(text => typeof text === "string" && text.trim() && text.length <= 5000)) throw new Error("invalid-examples");
      ids.add(item.id);
    }
    const selected = ui.exampleSelect.value;
    exampleCatalog = items; ui.exampleSelect.replaceChildren();
    for (const item of items) { const option = document.createElement("option"); option.value = item.id; option.textContent = item.title; ui.exampleSelect.append(option); }
    ui.exampleSelect.value = ids.has(selected) ? selected : items[0].id;
  } catch { /* The default homology sample remains usable when catalog retrieval fails. */ }
  finally { clearTimeout(timer); }
}

function renderGenerationControls() {
  ui.generate.disabled = graphLoading || scopeChecking;
  ui.example.disabled = graphLoading || scopeChecking;
  ui.exampleSelect.disabled = graphLoading || scopeChecking;
  ui.generationRetry.disabled = graphLoading || scopeChecking;
  ui.generate.textContent = scopeChecking ? "正在细化目标…" : graphLoading && graphController?.source === "generated" ? "正在生成…" : "生成学习图";
  ui.example.textContent = graphLoading && graphController?.source === "example" ? "正在载入…" : "载入离线样例";
  ui.form.setAttribute("aria-busy", String(graphLoading || scopeChecking));
}

async function loadRequestedGraph(source, text = "") {
  cancelScopeSelection();
  if (!libraryAvailable || historySwitching) { setGenerationError("学习库暂时不可用，请先重试连接后再创建记录。"); return; }
  try { if (!await flushHistory()) throw new Error("unsaved-history"); } catch { setGenerationError("当前改动尚未保存，请先处理保存问题。当前学习图仍保留。"); return; }
  const exampleId = ui.exampleSelect.value || "homology";
  const example = exampleCatalog.find(item => item.id === exampleId) || exampleCatalog[0];
  const version = ++graphRequestVersion;
  graphController?.abort();
  const controller = new AbortController();
  controller.source = source;
  graphController = controller;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, source === "generated" ? 150000 : 20000);
  graphLoading = true;
  setGenerationError("");
  ui.generationMessage.textContent = source === "generated"
    ? "正在生成并检查学习图，可能需要几十秒。当前图仍可查看和点选。"
    : `正在载入${example.title}，不会调用模型。`;
  renderGenerationControls();
  try {
    const response = await fetch(source === "example" ? exampleId === "homology" ? "/example" : `/example?example_id=${encodeURIComponent(exampleId)}` : "/analyze", source === "example" ? {
      cache: "no-store", signal: controller.signal,
    } : {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, mode: studyModeForModel() }), signal: controller.signal,
    });
    if (!response.ok) {
      const message = await responseFailure(response, source);
      const error = new Error("request-failed");
      error.userMessage = message;
      throw error;
    }
    const value = await response.json();
    if (version !== graphRequestVersion) return;
    await createHistoryForGraph(value, new Map(), source, source === "example" ? example.goal : text);
    ui.generationMessage.textContent = source === "example"
      ? `已载入${example.title}。点击知识点打开审核过的学习卡，无需联网。`
      : `已生成 ${graph.nodes.length} 个知识点。点击节点可生成学习卡，请核对图和学习内容。`;
  } catch (error) {
    if (version !== graphRequestVersion) return;
    const message = error.userMessage || (timedOut
      ? "请求时间较长，暂时没有得到结果。请稍后重试。"
      : error.message === "invalid-graph"
        ? "返回的学习图没有通过检查，请重试生成。"
        : "暂时无法连接后端，请确认服务正在运行后重试。");
    setGenerationError(`${message}${graph ? " 当前图和掌握标记仍然保留。" : ""}`, source);
    ui.generationMessage.textContent = source === "example" ? "样例载入未完成。" : "学习图生成未完成。";
    if (!graph) {
      ui.target.textContent = "尚未载入学习图。";
      ui.message.textContent = "载入样例或生成学习图后即可查看候选。";
      const placeholder = document.createElement("p");
      placeholder.className = "placeholder";
      placeholder.textContent = "载入样例，或输入你的数学目标";
      ui.canvas.replaceChildren(placeholder);
    }
  } finally {
    clearTimeout(timer);
    if (version === graphRequestVersion) {
      graphLoading = false;
      renderGenerationControls();
    }
  }
}

function cancelScopeSelection() {
  ++scopeVersion; scopeController?.abort(); scopeController = null; scopeChecking = false;
  scopeResult = null; selectedScopeId = null; ui.scopePanel.hidden = true; ui.scopeOptions.replaceChildren(); ui.scopeConfirm.disabled = true; renderGenerationControls();
}

function validateScope(value, text) {
  requireExactFields(value, ["needs_selection", "reason", "options", "original_text"]);
  if (typeof value.needs_selection !== "boolean" || typeof value.reason !== "string" || value.reason.length > 2000 || value.original_text !== text || !Array.isArray(value.options) || value.options.length > 5 || value.needs_selection && value.options.length < 2) throw new Error("invalid-scope");
  const ids = new Set();
  for (const option of value.options) { requireExactFields(option, ["id", "title", "goal", "description"]); if (Object.values(option).some(item => typeof item !== "string" || !item.trim() || item.length > 5000) || ids.has(option.id)) throw new Error("invalid-scope"); ids.add(option.id); }
  return value;
}

function renderScopeOptions(value) {
  scopeResult = value; selectedScopeId = null; ui.scopePanel.hidden = false; ui.scopeReason.textContent = value.reason; ui.scopeOptions.replaceChildren(); ui.scopeConfirm.disabled = true;
  for (const option of value.options) { const label = document.createElement("label"); label.className = "scope-option"; const radio = document.createElement("input"); radio.type = "radio"; radio.name = "scope-goal"; radio.value = option.id; const body = document.createElement("span"); const title = document.createElement("strong"); title.textContent = option.title; const description = document.createElement("span"); description.textContent = `${option.description}\n本次目标：${option.goal}`; body.append(title, description); label.append(radio, body); radio.addEventListener("change", () => { if (radio.checked) { selectedScopeId = option.id; ui.scopeConfirm.disabled = false; } }); ui.scopeOptions.append(label); }
  ui.generationMessage.textContent = "这个范围较大。请选择一个方向后确认；还没有请求模型或改动当前学习图。"; ui.scopePanel.scrollIntoView({ block: "nearest" });
}

async function generateGraph() {
  if (scopeChecking || graphLoading) return;
  const text = ui.input.value.trim();
  if (text.length === 0 || Array.from(text).length > MAX_TEXT_LENGTH) {
    setGenerationError("请输入 1 至 5000 字的数学目标或短文本。");
    ui.input.focus();
    return;
  }
  saveWorkspace();
  cancelScopeSelection(); const version = ++scopeVersion; const mode = studyModeForModel(); const epoch = historyEpoch;
  const controller = new AbortController(); scopeController = controller; scopeChecking = true; renderGenerationControls(); setGenerationError(""); ui.generationMessage.textContent = "先检查目标是否需要细分，这一步不会调用模型。";
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch("/study/scope", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal, body: JSON.stringify({ text, mode }) });
    if (!response.ok) throw new Error("scope-unavailable"); const value = validateScope(await response.json(), text);
    if (version !== scopeVersion || epoch !== historyEpoch || ui.input.value.trim() !== text || studyModeForModel() !== mode) return;
    if (value.needs_selection) renderScopeOptions(value); else await loadRequestedGraph("generated", text);
  } catch { if (version === scopeVersion) { setGenerationError("目标范围检查未完成，请重试；当前学习图仍保留。"); ui.generationMessage.textContent = "尚未调用模型生成。"; } }
  finally { clearTimeout(timer); if (version === scopeVersion) { scopeController = null; scopeChecking = false; renderGenerationControls(); } }
}

ui.chatLauncher.addEventListener("click", openChat);
ui.chatClose.addEventListener("click", closeChat);
ui.chatCollapse.addEventListener("click", () => {
  finishChatPointer(); chatCollapsed = !chatCollapsed; positionChatWindow();
  if (chatCollapsed) ui.chatCollapse.focus({ preventScroll: true });
  else ui.chatQuestion.focus({ preventScroll: true });
});
ui.chatResetPosition.addEventListener("click", () => { finishChatPointer(); positionChatWindow(true); });
ui.chatTitlebar.addEventListener("pointerdown", event => beginChatPointer(event, "move"));
ui.chatResizeGrip.addEventListener("pointerdown", event => beginChatPointer(event, "resize"));
for (const element of [ui.chatTitlebar, ui.chatResizeGrip]) {
  element.addEventListener("lostpointercapture", finishChatPointer);
}
document.addEventListener("pointermove", moveChatPointer);
document.addEventListener("pointerup", finishChatPointer);
document.addEventListener("pointercancel", finishChatPointer);
ui.chatTitlebar.addEventListener("keydown", event => keyboardChatGeometry(event, "move"));
ui.chatResizeGrip.addEventListener("keydown", event => keyboardChatGeometry(event, "resize"));
ui.chatWindow.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  event.preventDefault(); event.stopPropagation?.(); closeChat();
});
ui.chatQuestion.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
    event.preventDefault(); sendChatQuestion();
  }
});
ui.chatForm.addEventListener("submit", event => { event.preventDefault(); sendChatQuestion(); });
ui.chatCancel.addEventListener("click", () => cancelChatQuestion());
ui.chatKeepProblem.addEventListener("click", () => keepProblem(chatUnresolvedCandidate));
ui.chatScopeCancel.addEventListener("click", () => { clearChatScope(); ui.chatStatus.textContent = "已取消方向选择。请修改问题后重新发送；没有调用模型。"; ui.chatQuestion.focus(); });
ui.chatQuestion.addEventListener("input", () => { if (!ui.chatScopePanel.hidden || chatScopeApproved) clearChatScope(); });
ui.chatContext.addEventListener("change", () => { chatContextChosen = true; renderChatContext(); });
ui.chatUseModel.addEventListener("change", renderChatMode);
window.addEventListener("resize", () => { finishChatPointer(); if (chatOpened) positionChatWindow(); });

ui.fullBackup.addEventListener("click", exportFullBackup);
ui.restoreBackup.addEventListener("click", () => { if (!libraryActionBusy) ui.restoreBackupFile.click(); });
ui.restoreBackupFile.addEventListener("change", () => previewFullBackup(ui.restoreBackupFile.files?.[0]));
ui.libraryButton.addEventListener("click", () => openLibrary(ui.libraryButton));
ui.problemsButton.addEventListener("click", () => openLibrary(ui.problemsButton, "problems"));
ui.libraryHistoryTab.addEventListener("click", () => setLibraryTab("histories"));
ui.libraryProblemsTab.addEventListener("click", () => setLibraryTab("problems"));
ui.problemFilter.addEventListener("change", () => loadProblems());
ui.problemRefresh.addEventListener("click", () => loadProblems());
ui.problemLoadMore.addEventListener("click", () => loadProblems(true));
ui.selectAllProblems.addEventListener("change", () => { selectedProblems = new Set(ui.selectAllProblems.checked ? problemRecords.map(item => item.id) : []); renderProblems(); });
ui.deleteProblems.addEventListener("click", deleteSelectedProblems);
let problemSearchTimer = null;
ui.problemSearch.addEventListener("input", () => { clearTimeout(problemSearchTimer); problemSearchTimer = setTimeout(() => loadProblems(), 250); });
ui.scopeCancel.addEventListener("click", () => { cancelScopeSelection(); ui.generationMessage.textContent = "已取消范围选择，可修改学习目标；没有调用模型。"; ui.input.focus(); });
ui.scopeConfirm.addEventListener("click", () => { const chosen = scopeResult?.options.find(option => option.id === selectedScopeId); if (!chosen || ui.input.value.trim() !== scopeResult.original_text) return; const goal = chosen.goal; cancelScopeSelection(); ui.input.value = goal; saveWorkspace(); loadRequestedGraph("generated", goal); });
ui.libraryClose.addEventListener("click", closeLibrary);
ui.manageProjects.addEventListener("click", () => { ui.projectManagement.hidden = !ui.projectManagement.hidden; if (!ui.projectManagement.hidden) ui.projectCreateTitle.focus(); });
ui.projectCreateForm.addEventListener("submit", event => {
  event.preventDefault();
  libraryMutation(async () => { const title = ui.projectCreateTitle.value.trim(); if (!title) throw new Error("empty-title");
    await libraryRequest("/library/projects", { method: "POST", body: JSON.stringify({ title }) }); ui.projectCreateTitle.value = ""; }, "项目已创建。选择历史后可移入该项目。" );
});
ui.selectAllHistories.addEventListener("change", () => { selectedHistories = new Set(ui.selectAllHistories.checked ? libraryHistories.map(item => item.id) : []); renderLibrary(); });
ui.selectAllProjects.addEventListener("change", () => { selectedProjects = new Set(ui.selectAllProjects.checked ? libraryProjects.map(item => item.id) : []); renderLibrary(); });
ui.deleteHistories.addEventListener("click", deleteSelectedHistories);
ui.deleteProjects.addEventListener("click", deleteSelectedProjects);
ui.moveHistories.addEventListener("click", () => {
  const ids = [...selectedHistories]; if (!ids.length) return;
  const project_id = ui.moveHistoryProject.value || null;
  libraryMutation(async () => { await flushHistory();
    const previousRecord = currentHistory;
    await libraryRequest("/library/histories/move", { method: "POST", body: JSON.stringify({ ids, project_id }) });
    if (previousRecord && ids.includes(previousRecord.id)) await refreshHistoryAfterBatch(previousRecord);
    selectedHistories.clear(); }, `已移动 ${ids.length} 条历史。` );
});
ui.libraryConfirmYes.addEventListener("click", () => { const action = libraryConfirmationAction; libraryConfirmationAction = null; ui.libraryConfirmation.hidden = true; action?.(); });
ui.libraryConfirmNo.addEventListener("click", () => { ui.libraryConfirmation.hidden = true; libraryConfirmationAction = null; ui.libraryClose.focus(); });
ui.historyLoadMore.addEventListener("click", () => loadLibrary(true));
let historySearchTimer = null;
ui.historySearch.addEventListener("input", () => { clearTimeout(historySearchTimer); historySearchTimer = setTimeout(() => { selectedHistories.clear(); loadLibrary(); }, 250); });
ui.historySaveRetry.addEventListener("click", async () => {
  if (!libraryAvailable || !currentHistory) { await initializeLibrary(); return; }
  if (historyConflict) { exportWorkspace(); await openHistory(currentHistory.id, true); }
  else try { await flushHistory(); } catch { /* A safe message is already visible. */ }
});
ui.studyMode.addEventListener("change", () => { cancelScopeSelection(); saveWorkspace(); requestPlan(); renderBookGuidance(); });
ui.lessonNotes.addEventListener("input", () => { if (!activeLessonId) return; studyState.notes[activeLessonId] = ui.lessonNotes.value.slice(0, 6000); saveWorkspace(); });
ui.finalCheckButton.addEventListener("click", () => {
  ui.finalCheckSection.hidden = !ui.finalCheckSection.hidden;
  if (!ui.finalCheckSection.hidden) {
    if (graph.study_plan?.final_tasks.length) renderTasks(ui.finalCheckTasks, graph.study_plan.final_tasks);
    else loadStudyTasks(ui.finalCheckTasks, "final");
  }
});
ui.mixedPracticeButton.addEventListener("click", () => {
  const wasHidden = ui.mixedPracticeTasks.hidden;
  if (wasHidden) loadStudyTasks(ui.mixedPracticeTasks, "mixed"); else ui.mixedPracticeTasks.hidden = true;
});
document.addEventListener("keydown", event => {
  if (ui.libraryOverlay.hidden) return;
  if (event.key === "Escape") { event.preventDefault(); if (!ui.libraryConfirmation.hidden) { ui.libraryConfirmation.hidden = true; libraryConfirmationAction = null; ui.libraryClose.focus(); } else closeLibrary(); return; }
  if (event.key !== "Tab") return;
  const focusable = libraryFocusable(); const first = focusable[0]; const last = focusable[focusable.length - 1];
  if (!first) { event.preventDefault(); ui.libraryPanel.focus(); }
  else if (event.shiftKey && (document.activeElement === first || !ui.libraryPanel.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (document.activeElement === last || !ui.libraryPanel.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
});
document.addEventListener("focusin", event => { if (!ui.libraryOverlay.hidden && !ui.libraryPanel.contains(event.target)) ui.libraryClose.focus({ preventScroll: true }); });
window.addEventListener("beforeunload", event => {
  if (currentHistory && historyDirty !== historySaved) { event.preventDefault(); event.returnValue = ""; }
});

ui.modelSettingsButton.addEventListener("click", () => openModelSettings(ui.modelSettingsButton));
ui.modelSettingsClose.addEventListener("click", closeModelSettings);
ui.modelSettingsForm.addEventListener("submit", event => {
  event.preventDefault();
  saveModelSettings();
});
ui.modelSettingsClear.addEventListener("click", () => saveModelSettings(true));
ui.modelSettingsTest.addEventListener("click", testModelSettings);
ui.chatgptLoginButton.addEventListener("click", startChatgptLogin);
ui.modelProvider.addEventListener("change", () => {
  if (ui.modelProvider.value !== "api") ui.modelApiKey.value = "";
  renderModelSettingsControls();
  setModelSettingsMessage("选择尚未保存，点击“保存并使用”后生效。");
  if (chatgptSettingsVisible()) readChatgptStatus();
  else stopChatgptStatusPolling();
});
document.addEventListener("keydown", handleModelSettingsKeyboard);
document.addEventListener("focusin", event => {
  if (!ui.modelSettingsOverlay.hidden && !ui.modelSettingsPanel.contains(event.target)) {
    ui.modelSettingsClose.focus({ preventScroll: true });
  }
});

ui.form.addEventListener("submit", event => {
  event.preventDefault();
  if (!graphLoading) generateGraph();
});
ui.example.addEventListener("click", () => loadRequestedGraph("example"));
ui.generationRetry.addEventListener("click", () => failedSource === "example" ? loadRequestedGraph("example") : generateGraph());
ui.input.addEventListener("input", () => {
  if (scopeResult || scopeChecking) { cancelScopeSelection(); ui.generationMessage.textContent = "目标已修改，重新点击生成可检查范围。"; }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveWorkspace, 250);
});
ui.reset.addEventListener("click", () => {
  mastery.clear();
  refreshKnownIds();
  renderMastery();
  saveWorkspace();
  requestPlan();
});
ui.graphView.addEventListener("click", () => setView("graph", true));
ui.listView.addEventListener("click", () => setView("list", true));
ui.nodeSearch.addEventListener("input", renderNodeBrowser);
ui.export.addEventListener("click", exportWorkspace);
ui.import.addEventListener("click", () => ui.importFile.click());
ui.importFile.addEventListener("change", () => {
  const file = ui.importFile.files?.[0];
  ui.importFile.value = "";
  importWorkspace(file);
});
ui.lessonClose.addEventListener("click", () => closeLesson());
ui.lessonPrevious.addEventListener("click", () => navigateLesson(-1));
ui.lessonNext.addEventListener("click", () => navigateLesson(1));
document.addEventListener("keydown", handleLessonKeyboard);
document.addEventListener("focusin", event => {
  if (activeLessonId && narrowScreen.matches && !ui.lessonPanel.contains(event.target)) {
    ui.lessonTitle.focus({ preventScroll: true });
  }
});
ui.lessonRetry.addEventListener("click", () => {
  if (!lessonLoading && activeLessonId) requestLesson(activeLessonId);
});
for (const key of MASTERY_DIMENSIONS) {
  ui.masteryChecks[key].addEventListener("change", () => {
    if (activeLessonId) updateMastery(activeLessonId, { [key]: ui.masteryChecks[key].checked });
  });
}
ui.masteryAll.addEventListener("click", () => {
  if (activeLessonId) updateMastery(activeLessonId, { definition: true, intuition: true, application: true });
});
ui.masteryClear.addEventListener("click", () => {
  if (activeLessonId) updateMastery(activeLessonId, emptyMastery());
});
ui.exerciseForm.addEventListener("submit", async event => {
  event.preventDefault();
  const entry = lessonCache.get(activeLessonId);
  if (!entry) return;
  if (!Number.isInteger(entry.choice)) {
    ui.exerciseFeedback.textContent = "先选择一个答案，再检查。";
    ui.exerciseFeedback.classList.remove("correct");
    ui.exerciseFeedback.hidden = false;
    ui.exerciseExplanation.hidden = true;
    ui.exerciseMark.hidden = true;
    return;
  }
  const submittedGraph = graph; const epoch = historyEpoch; const id = activeLessonId;
  const hintLevel = entry.microReferenceSeen ? 3 : 0;
  entry.answer = entry.choice;
  entry.microReferenceSeen = true;
  renderExerciseFeedback(entry);
  const exercise = entry.lesson.exercise;
  const task = { id: `${id}_exercise`, node_id: id, kind: "exercise", format: "choice", question: exercise.question,
    options: [...exercise.options], correct_index: exercise.correct_index, reference_answer: exercise.explanation,
    hints: ["先确认这道题是在考定义、直观还是具体运算。", "核对题目的对象、系数与方向约定。", exercise.explanation.slice(0, 600)],
    rubric: [{ id: "reason_1", description: "所选答案与题目唯一正确选项一致" }], dimension: exercise.dimension, source: entry.lesson.source };
  const answer = String(entry.choice);
  ui.exerciseSubmit.disabled = true;
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch("/study/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ graph: submittedGraph, node_id: id, task_id: task.id, answer, hint_level: hintLevel, lesson: entry.lesson, use_model: false }) });
    if (!response.ok) throw new Error("feedback-unavailable");
    const checked = validateFeedback(await response.json());
    if (epoch !== historyEpoch || submittedGraph !== graph || activeLessonId !== id || lessonCache.get(id) !== entry) return;
    if (checked.node_id !== id || checked.task_id !== task.id) throw new Error("invalid-feedback");
    const stored = recordAttempt(task, answer, hintLevel, checked);
    ui.exerciseFeedback.textContent = checked.summary + (stored ? " 已记录本题表现，不自动标记掌握。" : " 作答达到上限，本次结果尚未保存。");
  } catch {
    if (epoch === historyEpoch && submittedGraph === graph && activeLessonId === id && lessonCache.get(id) === entry) {
      recordAttempt(task, answer, hintLevel, null, "ungraded");
      ui.exerciseFeedback.textContent = "参考对照已显示，但检查未完成。此题未判定独立通过，已有掌握标记保留。";
    }
  } finally { clearTimeout(timer); if (epoch === historyEpoch && submittedGraph === graph && activeLessonId === id) ui.exerciseSubmit.disabled = false; }
});
ui.exerciseMark.addEventListener("click", () => {
  const entry = lessonCache.get(activeLessonId);
  if (entry && Number.isInteger(entry.answer) && entry.answer === entry.lesson.exercise.correct_index) {
    updateMastery(activeLessonId, { [entry.lesson.exercise.dimension]: true });
  }
});
ui.illustrationZoom.addEventListener("click", () => {
  setIllustrationZoom(ui.illustrationZoom.getAttribute("aria-pressed") !== "true");
});
ui.retry.addEventListener("click", () => requestPlan());
ui.zoomOut.addEventListener("click", () => setZoom("manual", zoom - .15));
ui.zoomIn.addEventListener("click", () => setZoom("manual", zoom + .15));
ui.fitWidth.addEventListener("click", () => setZoom("width"));
ui.fitAll.addEventListener("click", () => setZoom("all"));
ui.actualSize.addEventListener("click", () => setZoom("manual", 1));
ui.storageButton.addEventListener("click", () => {
  openLibrary(ui.storageButton);
});

if (typeof ResizeObserver !== "undefined") new ResizeObserver(applyZoom).observe(ui.viewport);
else window.addEventListener("resize", applyZoom);

function handleViewportModeChange() {
  if (!viewChosen) setView(narrowScreen.matches ? "list" : "graph");
  syncLessonMode();
}
if (narrowScreen.addEventListener) narrowScreen.addEventListener("change", handleViewportModeChange);
else narrowScreen.addListener(handleViewportModeChange);
setView(viewMode);
renderProgress();
renderChatContext(); renderChatMode(); renderChatMessages(); renderChatControls(); syncChatVisibility();
loadExampleCatalog();

initializeLibrary();
