"use strict";

// Run without a browser, credentials, account login or external model access.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const oldSupport = fs.readFileSync(path.join(__dirname, "frontend_v03.cjs"), "utf8");
const supportSource = oldSupport.slice(0, oldSupport.indexOf("function checkLessonValidation"))
  .replace("AbortController, Blob,", 'AbortController, Blob, URLSearchParams, crypto: require("node:crypto").webcrypto,')
  .replace('if (element.getAttribute("id"))', 'if (element.attributes.has("checked")) element.checked = true;\n    if (element.getAttribute("id"))')
  .replace('window: { matchMedia: () => media, addEventListener() {} },', 'window: { innerWidth: 1200, innerHeight: 850, listeners: new Map(), matchMedia: () => media, addEventListener(type, listener) { if (!this.listeners.has(type)) this.listeners.set(type, []); this.listeners.get(type).push(listener); } },');
const support = new Function("require", "__dirname", `${supportSource}\nreturn {makeEnvironment,fixture,flags,envelope,file,flush,response,lessonFixture};`)(require, __dirname);
const { makeEnvironment, fixture, flags, envelope, file, flush, response, lessonFixture } = support;
const treeText = element => [element.textContent, ...element.children.map(treeText)].join(" ");
const copy = value => JSON.parse(JSON.stringify(value));
const state = overrides => ({ version: 1, mastery: {}, lessons: {}, notes: {}, attempts: [], reviews: {},
  chat_turns: [],
  study_mode: "intuition", graph_source: "generated", diagnostic_answers: {}, final_answers: {}, active_node_id: null, view: "graph", ...overrides });
const task = overrides => ({ id: "vector_independent", node_id: "vector", kind: "independent", format: "open", question: "Explain the reason.",
  options: [], correct_index: null, hints: ["Recall the definition.", "Consider a concrete example.", "Compare the key step."],
  reference_answer: "A reference proof.", rubric: [{ id: "reason_one", description: "Give a justified inference." }], dimension: "application", source: "local_adaptation", ...overrides });
const feedback = overrides => ({ node_id: "vector", task_id: "vector_independent", outcome: "needs_review", summary: "Compare your justification with the reference.",
  steps: [{ criterion_id: "reason_one", status: "uncertain", comment: "Check this inference." }], next_hint: null, next_action: "compare_reference",
  source: "local_reference", review_required: true, reference_answer: "A reference proof.", ...overrides });

function actualPythonJSON(code, input = "") {
  const project = path.resolve(__dirname, "..");
  const python = process.env.MATHPATH_TEST_PYTHON || path.join(project, ".venv", "Scripts", "python.exe");
  const execution = spawnSync(python, ["-B", "-c", `import tempfile,os\nwith tempfile.TemporaryDirectory(prefix='mathpath-v04-schema-') as test_data:\n os.environ['MATHPATH_DATA_DIR']=test_data\n os.environ.pop('MATHPATH_DESKTOP',None)\n ${code.split("\n").join("\n ")}`],
    { cwd: project, input, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONDONTWRITEBYTECODE: "1" }, maxBuffer: 4 * 1024 * 1024 });
  assert.equal(execution.status, 0, `Actual Python schema check failed: ${execution.stderr}`);
  return JSON.parse(execution.stdout);
}

function backend() {
  let counter = 1;
  const projects = new Map(); const histories = new Map(); const migration = new Map(); const problems = new Map();
  const restoredBackups = new Set();
  const id = () => `11111111-1111-4111-8111-${String(counter++).padStart(12, "0")}`;
  const timestamp = () => new Date().toISOString();
  function makeHistory(payload) {
    const record = { id: id(), title: payload.title, goal: payload.goal, project_id: payload.project_id ?? null, graph: copy(payload.graph),
      state: state(copy(payload.state)), revision: 1, created_at: timestamp(), updated_at: timestamp() };
    histories.set(record.id, record); return record;
  }
  function handle(request) {
    const parsed = new URL(request.url, "http://127.0.0.1:8000"); const url = parsed.pathname;
    const method = request.options?.method || "GET"; const payload = request.options?.body ? JSON.parse(request.options.body) : {};
    let value;
    if (url === "/examples") return { ok: true, status: 200, json: async () => [
      { id: "homology", title: "同调群取商", description: "链与边界", goal: "理解同调群为什么要取商" },
      { id: "rank_nullity", title: "秩–零化度", description: "核、像与维数", goal: "理解秩–零化度定理" },
      { id: "epsilon_delta", title: "ε–δ 极限", description: "量词与邻域", goal: "用 ε–δ 定义证明线性函数极限" },
    ] };
    if (url === "/library/backup") return { ok: true, status: 200, json: async () => copy({
      format: "mathpath_library_backup", version: 1, created_at: timestamp(),
      projects: [...projects.values()], histories: [...histories.values()], problems: [...problems.values()],
    }) };
    if (url.startsWith("/library/backup/")) {
      const key = JSON.stringify(payload); const repeat = parsed.searchParams.get("repeat") === "true";
      const prior = restoredBackups.has(key);
      const summary = { projects: payload.projects.length, histories: payload.histories.length, problems: payload.problems.length,
        already_restored: prior && !repeat };
      if (url.endsWith("/restore") && (!prior || repeat)) {
        const projectIds = new Map(); const historyIds = new Map();
        for (const item of payload.projects) { const newId = id(); projectIds.set(item.id, newId); projects.set(newId, { ...copy(item), id: newId }); }
        for (const item of payload.histories) { const newId = id(); historyIds.set(item.id, newId); histories.set(newId, { ...copy(item), id: newId, project_id: projectIds.get(item.project_id) || null, revision: 1 }); }
        for (const item of payload.problems) { const newId = id(); problems.set(newId, { ...copy(item), id: newId, history_id: historyIds.get(item.history_id) || null }); }
        restoredBackups.add(key);
      }
      return { ok: true, status: 200, json: async () => summary };
    }
    if (url === "/library/problems" && method === "GET") { let items = [...problems.values()]; const filter = parsed.searchParams.get("status") || "open"; const query = parsed.searchParams.get("query") || ""; if (filter !== "all") items = items.filter(item => item.status === filter); items = items.filter(item => (item.question + item.goal + item.node_label).includes(query)); value = items.slice(Number(parsed.searchParams.get("offset") || 0), Number(parsed.searchParams.get("offset") || 0) + Number(parsed.searchParams.get("limit") || 50)); }
    else if (url === "/library/problems" && method === "POST") { const prior = [...problems.values()].find(item => item.status === "open" && item.question === payload.question && item.history_id === payload.history_id && item.node_id === payload.node_id); value = prior || { ...payload, id: id(), status: "open", created_at: timestamp(), updated_at: timestamp() }; problems.set(value.id, value); }
    else if (url === "/library/problems/delete") { payload.ids.forEach(key => problems.delete(key)); value = { deleted_count: payload.ids.length }; }
    else if (url.startsWith("/library/problems/") && method === "PATCH") { value = problems.get(url.split("/").pop()); value.status = payload.status; value.updated_at = timestamp(); }
    else if (url === "/library/projects" && method === "GET") value = [...projects.values()];
    else if (url === "/library/projects" && method === "POST") { const project = { id: id(), title: payload.title, created_at: timestamp(), updated_at: timestamp() }; projects.set(project.id, project); value = project; }
    else if (url === "/library/projects/delete") { for (const projectId of payload.ids) { projects.delete(projectId); for (const record of histories.values()) if (record.project_id === projectId) { record.project_id = null; ++record.revision; } } value = { deleted_count: payload.ids.length }; }
    else if (url.startsWith("/library/projects/") && method === "PATCH") { const record = projects.get(url.split("/").pop()); record.title = payload.title; value = record; }
    else if (url === "/library/histories" && method === "GET") {
      let items = [...histories.values()].reverse(); const filter = parsed.searchParams.get("project_id"); const query = parsed.searchParams.get("query");
      if (filter) items = items.filter(item => filter === "uncategorized" ? item.project_id === null : item.project_id === filter);
      if (query) items = items.filter(item => (item.title + " " + item.goal).includes(query));
      const offset = Number(parsed.searchParams.get("offset") || 0); const limit = Number(parsed.searchParams.get("limit") || 50);
      value = items.slice(offset, offset + limit).map(({ graph, state: saved, ...metadata }) => ({ ...metadata, node_count: graph.nodes.length, lesson_count: Object.keys(saved.lessons).length, attempt_count: saved.attempts.length }));
    } else if (url === "/library/histories" && method === "POST") {
      if (payload.migration_key && migration.has(payload.migration_key)) value = histories.get(migration.get(payload.migration_key));
      else { value = makeHistory(payload); if (payload.migration_key) migration.set(payload.migration_key, value.id); }
    } else if (url === "/library/histories/delete") { for (const historyId of payload.ids) histories.delete(historyId); value = { deleted_count: payload.ids.length }; }
    else if (url === "/library/histories/move") { for (const historyId of payload.ids) { const record = histories.get(historyId); record.project_id = payload.project_id; ++record.revision; } value = { moved_count: payload.ids.length }; }
    else if (url.startsWith("/library/histories/")) {
      const record = histories.get(url.split("/").pop());
      if (!record) return { ok: false, status: 404, json: async () => ({ detail: "deleted" }) };
      if (method === "PATCH") {
        if (payload.expected_revision !== record.revision) return { ok: false, status: 409, json: async () => ({ detail: "conflict" }) };
        for (const key of ["title", "goal", "project_id", "graph", "state"]) if (Object.hasOwn(payload, key)) record[key] = copy(payload[key]);
        ++record.revision; record.updated_at = timestamp();
      }
      value = record;
    } else if (url === "/example" || url === "/analyze") value = fixture;
    else if (url === "/plan") {
      const known = payload.known_ids || [];
      value = { target_id: payload.graph.target_id, completed: false, known_ids: known, planning_known_ids: known, mode: payload.mode,
        ready_ids: payload.graph.nodes.filter(node => !known.includes(node.id) && (!node.prerequisite_sets.length || node.prerequisite_sets.some(group => group.every(parent => known.includes(parent))))).map(node => node.id),
        blocked_ids: [], recommended_ids: ["vector"], required_ids: ["vector", "chain", "goal"], selected_ids: payload.graph.nodes.map(node => node.id), focus_id: "vector", explanation: "按当前目的所需自报能力推荐，不等同独立检验。" };
    } else if (url === "/lesson") value = lessonFixture(payload.node_id);
    else if (url === "/study/tasks") value = { tasks: payload.node_id === "vector" || payload.kind === "mixed" ? [task()] : [] };
    else if (url === "/study/feedback") value = payload.task_id.endsWith("_exercise")
      ? feedback({ task_id: payload.task_id, node_id: payload.node_id, source: "local_check", outcome: "correct", next_action: "independent_check", review_required: true, summary: "Matches a generated key; it needs review." })
      : feedback({ task_id: payload.task_id, node_id: payload.node_id, source: payload.use_model ? "model_candidate" : "local_reference" });
    else if (url === "/study/help") value = { response: "Local explanation.", source: payload.use_model ? "model_candidate" : "local_reference", review_required: true };
    else if (url === "/study/chat") value = { response: "Compare $Z_n/B_n$. <img src=x onerror=alert(1)>", source: payload.use_model ? "model_candidate" : "local_reference", review_required: true, answer_status: "answered", problem_id: null, problem_save_failed: false };
    else if (url === "/study/scope") value = payload.text === "我想学习拓扑学" ? { original_text: payload.text, needs_selection: true, reason: "先细化一个具体目标。", options: [{ id: "open_sets", title: "开集与连续", goal: "理解用开集定义连续映射", description: "从开集和原像开始。" }, { id: "fundamental_group", title: "基本群", goal: "理解基本群如何记录环路的变形", description: "从基点环路开始。" }] } : { original_text: payload.text, needs_selection: false, reason: "目标已经具体。", options: [] };
    else if (url === "/study/references") value = { books: [{ id: "hatcher", title: "Algebraic Topology", author: "Allen Hatcher", url: "https://pi.math.cornell.edu/~hatcher/AT/AT.pdf", section: "§2.1", why: "阅读链与同调的定义。" }], message: "固定教材目录；请核对当前对象与条件。" };
    else if (url === "/settings/model") value = { provider: "chatgpt", base_url: "https://api.openai.com/v1", model: "", api_format: "chat_completions", output_mode: "json_object", has_api_key: false, revision: "default" };
    else if (url === "/settings/chatgpt/status") value = { status: "idle", message: "本次运行尚未发起登录。", attempt: 0 };
    else throw new Error(`Unexpected offline request ${method} ${url}`);
    return { ok: true, status: 200, json: async () => copy(value) };
  }
  return { projects, histories, migration, problems, handle, makeHistory };
}

async function settle(env, store, skip = () => false) {
  for (let iteration = 0; iteration < 40; ++iteration) {
    await flush();
    const pending = env.requests.filter(request => !request.settled && !skip(request));
    if (!pending.length) { await flush(); if (!env.requests.some(request => !request.settled && !skip(request))) return; continue; }
    for (const request of pending) { request.settled = true; request.resolve(store.handle(request)); }
  }
  throw new Error("Offline settle did not stabilize");
}

async function operation(env, store, code, skip) {
  const promise = env.evaluate(code); await settle(env, store, skip); await promise; await settle(env, store, skip);
}

async function checkFullBackupAndExamples() {
  const env = makeEnvironment(); const store = backend(); await settle(env, store);
  const recordId = env.evaluate("currentHistory.id"); const originalGoal = store.histories.get(recordId).goal;
  assert.equal(env.get("example-select").children.length, 3, "all curated examples are selectable");
  env.get("library-button").click(); await settle(env, store);
  await operation(env, store, "exportFullBackup()");
  const backup = JSON.parse(await env.downloads.at(-1).text());
  assert.equal(backup.format, "mathpath_library_backup"); assert.equal(backup.histories.length, 1);
  for (const field of ["api_key", "modelSettings", "access_token", "authorization"]) assert(!JSON.stringify(backup).includes(`"${field}"`));
  env.context.fullBackupFile = file(backup);
  const restoreCount = () => env.requests.filter(item => item.url.startsWith("/library/backup/restore")).length;
  await operation(env, store, "previewFullBackup(fullBackupFile)");
  assert.equal(restoreCount(), 0); assert.match(env.get("library-confirm-description").textContent, /1 条历史/);
  assert.match(env.get("library-confirm-yes").textContent, /添加/);
  env.get("library-confirm-no").click(); await settle(env, store); assert.equal(store.histories.size, 1);
  await operation(env, store, "previewFullBackup(fullBackupFile)"); env.get("library-confirm-yes").click(); await settle(env, store);
  assert.equal(store.histories.size, 2); assert.equal(env.evaluate("currentHistory.id"), recordId);
  assert.equal(store.histories.get(recordId).goal, originalGoal); assert.match(env.get("backup-message").textContent, /恢复完成/);
  await operation(env, store, "previewFullBackup(fullBackupFile)"); assert.match(env.get("library-confirm-description").textContent, /可能产生重复/);
  env.get("library-confirm-no").click(); await settle(env, store); assert.equal(store.histories.size, 2);
  await operation(env, store, "previewFullBackup(fullBackupFile)"); env.get("library-confirm-yes").click(); await settle(env, store);
  assert.equal(store.histories.size, 3); assert(env.requests.some(item => item.url.endsWith("restore?repeat=true")));
  env.context.oversizedBackup = { size: 50 * 1024 * 1024 + 1, text() { throw new Error("must not read oversized file"); } };
  const previewsBefore = env.requests.filter(item => item.url === "/library/backup/preview").length;
  await operation(env, store, "previewFullBackup(oversizedBackup)"); assert.match(env.get("backup-message").textContent, /50 MiB/);
  assert.equal(env.requests.filter(item => item.url === "/library/backup/preview").length, previewsBefore);
  let resolveDelayedFile;
  env.context.delayedBackup = { size: 50, text: () => new Promise(resolve => { resolveDelayedFile = resolve; }) };
  const delayedPreview = env.evaluate("previewFullBackup(delayedBackup)"); await flush();
  env.get("library-close").click(); resolveDelayedFile(JSON.stringify(backup)); await delayedPreview; await settle(env, store);
  assert.equal(env.requests.filter(item => item.url === "/library/backup/preview").length, previewsBefore, "closing the library cancels delayed file checks");
  assert(env.get("library-confirmation").hidden, "late file reads cannot reopen a confirmation");
  env.get("library-button").click(); await settle(env, store);
  env.context.invalidBackup = { size: 1, text: async () => "{" };
  await operation(env, store, "previewFullBackup(invalidBackup)");
  assert.match(env.get("backup-message").textContent, /尚未添加/); assert.equal(store.histories.size, 3);
  env.get("library-close").click(); env.get("example-select").value = "rank_nullity";
  await operation(env, store, 'loadRequestedGraph("example")');
  assert.equal(store.histories.get(env.evaluate("currentHistory.id")).goal, "理解秩–零化度定理");
  assert(env.requests.some(item => item.url === "/example?example_id=rank_nullity"));
  assert(!env.requests.some(item => item.url === "/analyze" || item.url === "/settings/chatgpt/login"));
}

async function checkFloatingChat() {
  const env = makeEnvironment(); const store = backend(); await settle(env, store);
  const recordId = env.evaluate("currentHistory.id");
  const chatRequests = () => env.requests.filter(item => item.url === "/study/chat");
  const rect = () => JSON.parse(env.evaluate("JSON.stringify(chatRect)"));
  const validateRect = () => { const value = rect(); assert(value.x >= 8 && value.y >= 8); assert(value.x + value.width <= env.context.window.innerWidth - 8); assert(value.y + (env.evaluate("chatCollapsed") ? 64 : value.height) <= env.context.window.innerHeight - 8); };
  assert(env.get("chat-use-model").checked, "model answer is an explicit visible default with a cost notice");
  assert.match(env.get("chat-mode-note").textContent, /消耗/);
  assert.equal(chatRequests().length, 0, "startup does not submit a chat question");
  env.get("chat-launcher").click();
  assert(!env.get("chat-window").hidden); assert.equal(env.document.activeElement, env.get("chat-question"));
  const initial = rect();
  env.get("chat-titlebar").dispatch("pointerdown", { pointerId: 11, clientX: 750, clientY: 300, button: 0, isPrimary: true });
  assert(env.evaluate("!!chatPointer"));
  env.document.dispatch("pointermove", { pointerId: 11, clientX: -2000, clientY: -2000 }); validateRect(); assert.equal(rect().x, 8);
  env.document.dispatch("pointercancel", { pointerId: 11 }); assert.equal(env.evaluate("chatPointer"), null);
  env.get("chat-titlebar").dispatch("keydown", { key: "ArrowRight", shiftKey: true }); assert.equal(rect().x, 48);
  env.get("chat-reset-position").click(); assert.deepEqual(rect(), initial);
  env.get("chat-resize-grip").dispatch("keydown", { key: "ArrowRight" }); assert.equal(rect().width, initial.width + 10);
  env.get("chat-resize-grip").dispatch("pointerdown", { pointerId: 12, clientX: 1100, clientY: 790, button: 0 });
  env.document.dispatch("pointermove", { pointerId: 12, clientX: 5000, clientY: 5000 }); validateRect();
  env.document.dispatch("pointerup", { pointerId: 12 }); assert.equal(env.evaluate("chatPointer"), null);
  env.get("chat-reset-position").click();
  env.get("chat-collapse").click(); assert(env.get("chat-body").hidden); assert.equal(env.get("chat-window").style.height, "64px");
  env.get("chat-collapse").click(); assert(!env.get("chat-body").hidden);
  env.get("chat-question").value = "Draft retained on close"; env.get("chat-close").click();
  assert(env.get("chat-window").hidden); assert.equal(env.get("chat-question").value, "Draft retained on close"); env.get("chat-launcher").click();
  env.context.window.innerWidth = 760; env.context.window.innerHeight = 600;
  for (const listener of env.context.window.listeners.get("resize")) listener(); validateRect(); assert(rect().width >= 300 && rect().height >= 300);
  await operation(env, store, "openLibrary()"); assert(env.get("chat-window").hidden && env.get("chat-launcher").hidden); env.get("library-close").click(); assert(!env.get("chat-window").hidden);
  await operation(env, store, "openModelSettings()"); assert(env.get("chat-window").hidden); env.get("model-settings-close").click(); assert(!env.get("chat-window").hidden);
  env.setNarrow(true); env.evaluate('openLesson("vector")'); await settle(env, store); assert(env.get("chat-window").hidden); env.evaluate("closeLesson()"); assert(!env.get("chat-window").hidden); env.setNarrow(false);
  assert.equal(chatRequests().length, 0, "open, drag, resize, collapse and modal changes never call the model");

  env.get("chat-context").value = "vector"; env.get("chat-context").dispatch("change");
  env.get("chat-question").value = "Why this quotient?"; env.get("chat-form").dispatch("submit"); await settle(env, store);
  assert.equal(chatRequests().length, 1); const firstPayload = JSON.parse(chatRequests()[0].options.body);
  assert(firstPayload.use_model); assert.equal(firstPayload.node_id, "vector"); assert(firstPayload.lesson, "only already loaded card is sent"); assert.deepEqual(firstPayload.turns, []);
  assert.equal(env.evaluate("studyState.chat_turns.length"), 1); assert.equal(store.histories.get(recordId).state.chat_turns.length, 1);
  assert.match(env.get("chat-status").textContent, /已保存/); assert.equal(env.get("chat-question").value, "");
  assert.match(treeText(env.get("chat-messages")), /<img src=x onerror=alert\(1\)>/); assert.equal(env.get("chat-messages").querySelectorAll("img,script").length, 0, "reply HTML remains literal text");
  const known = env.snapshot().known;
  env.get("chat-use-model").checked = false; env.get("chat-use-model").dispatch("change"); assert.match(env.get("chat-mode-note").textContent, /不会调用模型/);
  env.get("chat-question").value = "And the next step?"; env.get("chat-question").dispatch("keydown", { key: "Enter", ctrlKey: true }); await settle(env, store);
  const secondPayload = JSON.parse(chatRequests().at(-1).options.body); assert(!secondPayload.use_model); assert.equal(secondPayload.turns.length, 1); assert.equal(secondPayload.turns[0].question, "Why this quotient?");
  assert.deepEqual(env.snapshot().known, known, "answers never mark mastery");
  env.context.oldChatTurns = JSON.parse(env.evaluate("JSON.stringify(studyState.chat_turns)"));
  await operation(env, store, 'loadRequestedGraph("example")'); assert.equal(env.evaluate("studyState.chat_turns.length"), 0); assert.equal(env.get("chat-question").value, "");
  await operation(env, store, `openHistory("${recordId}")`); assert.equal(env.evaluate("studyState.chat_turns.length"), 2); assert.match(treeText(env.get("chat-messages")), /And the next step/);

  const requestCount = chatRequests().length; env.get("chat-question").value = "Keep this failed draft";
  const failure = env.evaluate("sendChatQuestion()"); await settle(env, store, item => item.url === "/study/chat");
  const failed = env.requests.find(item => !item.settled && item.url === "/study/chat"); failed.settled = true; failed.resolve({ ok: false, status: 503 }); await failure; await settle(env, store);
  assert.equal(env.get("chat-question").value, "Keep this failed draft"); assert.equal(chatRequests().length, requestCount + 1); assert.equal(env.evaluate("studyState.chat_turns.length"), 2);
  const cancelled = env.evaluate("sendChatQuestion()"); await settle(env, store, item => item.url === "/study/chat");
  const pending = env.requests.find(item => !item.settled && item.url === "/study/chat"); env.get("chat-cancel").click(); assert.equal(env.evaluate("chatSending"), false); assert.equal(env.get("chat-question").value, "Keep this failed draft");
  pending.settled = true; pending.resolve(store.handle(pending)); await cancelled; await settle(env, store); assert.equal(env.evaluate("studyState.chat_turns.length"), 2, "cancelled late reply is ignored");

  const lateRequest = env.evaluate("sendChatQuestion()"); await settle(env, store, item => item.url === "/study/chat");
  const late = env.requests.find(item => !item.settled && item.url === "/study/chat");
  await operation(env, store, 'loadRequestedGraph("example")', item => item === late); assert.equal(env.evaluate("chatSending"), false);
  late.settled = true; late.resolve(store.handle(late)); await lateRequest; await settle(env, store); assert.equal(env.evaluate("studyState.chat_turns.length"), 0, "stale reply cannot enter another history");

  env.evaluate("const originalFlushForChat=flushHistory; flushHistory=async()=>false");
  env.get("chat-question").value = "Received but not saved"; await operation(env, store, "sendChatQuestion()"); assert.match(env.get("chat-status").textContent, /保存没有完成/);
  env.evaluate("flushHistory=originalFlushForChat"); await operation(env, store, "flushHistory()");
  const one = JSON.parse(env.evaluate("JSON.stringify(studyState.chat_turns[0])"));
  env.context.longTurns = Array.from({ length: 15 }, (_, index) => ({ ...one, id: `33333333-3333-4333-8333-${String(index).padStart(12, "0")}`, question: "q".repeat(6000), response: "r".repeat(6000) }));
  assert.equal(env.evaluate("chatRecentTurns(longTurns).length"), 5, "recent context is bounded by 60000 characters without trimming saved records");
  env.context.manyTurns = Array.from({ length: 100 }, (_, index) => ({ ...one, id: `44444444-4444-4444-8444-${String(index).padStart(12, "0")}` }));
  env.evaluate("studyState.chat_turns=manyTurns;renderChatControls()"); const atLimit = chatRequests().length; env.get("chat-question").value = "Over the limit"; await operation(env, store, "sendChatQuestion()");
  assert.equal(chatRequests().length, atLimit); assert.equal(env.evaluate("studyState.chat_turns.length"), 100, "100 saved turns are preserved instead of silently discarding old turns");
  for (const change of [value => { value.chat_turns = null; }, value => { value.chat_turns = [one, one]; }, value => { value.chat_turns[0].node_id = "outside_graph"; }, value => { value.chat_turns[0].review_required = false; }, value => { value.chat_turns[0].source = "curated_example"; }, value => { value.chat_turns[0].created_at = "2026-10-13T09:00:00"; }, value => { value.chat_turns[0].api_key = "must_not_export"; }]) {
    const candidate = state({ chat_turns: [copy(one)] }); change(candidate); env.context.badChatState = candidate; assert.throws(() => env.evaluate("validateStudyState(badChatState,graph)"), /invalid-workspace|invalid-response/);
  }
  env.evaluate("currentHistory=null;graph=null;nodeById=new Map();resetChatForHistory()"); env.get("chat-question").value = "A free-standing question"; await operation(env, store, "sendChatQuestion()");
  assert.equal(env.evaluate("chatEphemeralTurns.length"), 1); const freePayload = JSON.parse(chatRequests().at(-1).options.body); assert.equal(freePayload.graph, null); assert.equal(freePayload.node_id, null); assert.match(env.get("chat-status").textContent, /只在本页暂存/);
  assert(!env.requests.some(item => item.url === "/settings/chatgpt/login"));
}

async function checkV042GuidanceAndProblems() {
  const env = makeEnvironment(); const store = backend(); await settle(env, store);
  const analyzeCount = () => env.requests.filter(item => item.url === "/analyze").length;
  const chatCount = () => env.requests.filter(item => item.url === "/study/chat").length;
  const referenceCount = () => env.requests.filter(item => item.url === "/study/references").length;
  const initialGraph = env.snapshot().graph;
  const originalHistoryId = env.evaluate("currentHistory.id"); const originalGoal = store.histories.get(originalHistoryId).goal;
  env.get("goal-input").value = "我想学习拓扑学"; env.get("goal-form").dispatch("submit"); await settle(env, store);
  assert(!env.get("scope-panel").hidden); assert(env.get("scope-confirm").disabled); assert.equal(analyzeCount(), 0); assert.deepEqual(env.snapshot().graph, initialGraph);
  const radio = env.get("scope-options").querySelector("input"); radio.checked = true; radio.dispatch("change"); assert(!env.get("scope-confirm").disabled); assert.equal(analyzeCount(), 0, "choosing a scope alone never generates");
  env.get("scope-cancel").click(); assert(env.get("scope-panel").hidden); assert.equal(env.get("goal-input").value, "我想学习拓扑学"); assert.equal(analyzeCount(), 0);
  await operation(env, store, "flushHistory()"); assert.equal(store.histories.get(originalHistoryId).goal, originalGoal, "editing the next goal never rewrites the existing graph's historical goal");
  env.get("export-button").click(); const originalExport = JSON.parse(await env.downloads.at(-1).text()); assert.equal(originalExport.draft, originalGoal, "export identifies the old graph's real goal rather than the next-goal draft");
  env.context.ownedGoalBackup = file(originalExport); await operation(env, store, "importWorkspace(ownedGoalBackup)"); assert.equal(env.evaluate("currentHistory.goal"), originalGoal); assert.equal(env.get("goal-input").value, originalGoal, "imported original graph restores its original goal");
  env.get("goal-input").value = "我想学习拓扑学";
  env.get("goal-form").dispatch("submit"); await settle(env, store); const selected = env.get("scope-options").querySelectorAll("input")[1]; selected.checked = true; selected.dispatch("change");
  env.get("scope-confirm").click(); await settle(env, store); assert.equal(analyzeCount(), 1); assert.equal(JSON.parse(env.requests.find(item => item.url === "/analyze").options.body).text, "理解基本群如何记录环路的变形");
  assert.equal(store.histories.get(env.evaluate("currentHistory.id")).goal, "理解基本群如何记录环路的变形"); assert.equal(store.histories.get(originalHistoryId).goal, originalGoal);
  assert(env.get("scope-panel").hidden);
  env.get("goal-input").value = "A concrete computation"; await operation(env, store, "generateGraph()"); assert.equal(analyzeCount(), 2, "specific goals pass through without another confirmation");
  env.get("goal-input").value = "我想学习拓扑学"; const staleScope = env.evaluate("generateGraph()"); await settle(env, store, item => item.url === "/study/scope");
  const stale = env.requests.find(item => !item.settled && item.url === "/study/scope"); env.get("goal-input").value = "Changed clear goal"; env.get("goal-input").dispatch("input"); stale.settled = true; stale.resolve(store.handle(stale)); await staleScope; await settle(env, store); assert(env.get("scope-panel").hidden); assert.equal(analyzeCount(), 2, "changed text ignores late scope choices");

  assert(env.get("goal-books").hidden); assert.equal(referenceCount(), 0);
  env.get("study-mode").value = "proof"; env.get("study-mode").dispatch("change"); await settle(env, store); assert(!env.get("goal-books").hidden); assert.match(treeText(env.get("goal-books-content")), /Allen Hatcher/); assert.match(treeText(env.get("goal-books-content")), /§2.1/);
  env.evaluate('openLesson("vector")'); await settle(env, store); assert(!env.get("lesson-books").hidden);
  env.get("study-mode").value = "intuition"; env.get("study-mode").dispatch("change"); await settle(env, store); assert(env.get("goal-books").hidden && env.get("lesson-books").hidden);
  env.evaluate('updateMastery("vector",{definition:true,intuition:true,application:true})'); await settle(env, store); assert(!env.get("lesson-books").hidden, "all three self-reported abilities reveal books independently of proof mode");
  const oldBookCount = referenceCount(); env.evaluate("renderBookGuidance()"); await settle(env, store); assert.equal(referenceCount(), oldBookCount, "book cache does not generate or repeat requests");
  env.context.badBook = { books: [{ id: "bad", title: "False", author: "X", url: "https://trusted.example@bad.example/", section: "1", why: "bad" }], message: "x" }; assert.throws(() => env.evaluate("validateBooks(badBook)"), /invalid-books/);
  env.context.unknownBook = { books: [], message: "目前没有核实过这个主题的教材。" }; assert.doesNotThrow(() => env.evaluate("validateBooks(unknownBook)"));

  env.get("chat-launcher").click(); env.get("chat-use-model").checked = false;
  env.get("chat-question").value = "我想学习拓扑学"; const changedChatScope = env.evaluate("sendChatQuestion()"); await settle(env, store, item => item.url === "/study/scope"); const oldChatScope = env.requests.find(item => !item.settled && item.url === "/study/scope"); env.get("chat-question").value = "这一步为什么"; env.get("chat-question").dispatch("input"); oldChatScope.settled = true; oldChatScope.resolve(store.handle(oldChatScope)); await settle(env, store); await changedChatScope; assert(env.get("chat-scope-panel").hidden); assert.equal(chatCount(), 0); assert.equal(env.get("chat-question").value, "这一步为什么", "changed chat draft ignores the old preflight result");
  env.get("chat-question").value = "我想学习拓扑学"; env.get("chat-form").dispatch("submit"); await settle(env, store); assert(!env.get("chat-scope-panel").hidden); assert.equal(chatCount(), 0);
  env.get("chat-scope-options").querySelector("button").click(); assert.equal(chatCount(), 0, "chat scope selection only fills a draft"); assert.equal(env.get("chat-question").value, "理解用开集定义连续映射"); env.get("chat-form").dispatch("submit"); await settle(env, store); assert.equal(chatCount(), 1);
  assert.equal(env.evaluate("studyState.chat_turns[0].answer_status"), "answered");
  const recordId = env.evaluate("currentHistory.id"); env.get("chat-messages").querySelector(".chat-record-problem").click(); await settle(env, store); assert.equal(store.problems.size, 1);
  const manual = [...store.problems.values()][0]; assert.equal(manual.reason, "user_marked"); assert.equal(manual.history_id, recordId);
  env.get("problems-button").click(); await settle(env, store); assert(!env.get("problem-library-content").hidden); assert(env.get("history-library-content").hidden); assert.equal(env.get("problem-list").querySelectorAll("article").length, 1);
  env.get("problem-list").querySelector("button").click(); await settle(env, store); assert.equal(store.problems.get(manual.id).status, "resolved"); assert.equal(env.get("problem-list").querySelectorAll("article").length, 0);
  env.get("problem-filter").value = "resolved"; env.get("problem-filter").dispatch("change"); await settle(env, store); assert.equal(env.get("problem-list").querySelector("button").textContent, "重新打开"); env.get("problem-list").querySelector("button").click(); await settle(env, store); assert.equal(store.problems.get(manual.id).status, "open");
  env.get("problem-filter").value = "all"; env.get("problem-filter").dispatch("change"); await settle(env, store); env.get("problem-list").querySelectorAll("button")[1].click(); assert(!env.get("library-confirmation").hidden); assert(store.problems.has(manual.id)); env.get("library-confirm-no").click(); assert(store.problems.has(manual.id));
  env.get("problem-list").querySelectorAll("button")[1].click(); env.get("library-confirm-yes").click(); await settle(env, store); assert.equal(store.problems.size, 0); assert(store.histories.has(recordId), "deleting a problem preserves learning history"); env.get("library-close").click();

  env.get("chat-question").value = "Please evaluate this uncertain inference"; const uncertain = env.evaluate("sendChatQuestion()"); await settle(env, store, item => item.url === "/study/chat");
  const waiting = env.requests.find(item => !item.settled && item.url === "/study/chat"); waiting.settled = true; waiting.resolve(response({ response: "I am not certain about this step.", source: "model_candidate", review_required: true, answer_status: "uncertain", problem_id: null, problem_save_failed: true })); await settle(env, store); await uncertain;
  assert.equal(env.evaluate("studyState.chat_turns.at(-1).answer_status"), "uncertain"); assert(!env.get("chat-keep-problem").hidden); assert.match(env.get("chat-status").textContent, /未能自动记入/); env.get("chat-keep-problem").click(); await settle(env, store); assert.equal(store.problems.size, 1, "auto-save failure supports explicit local retry");
  const openId = [...store.problems.keys()][0];
  env.get("chat-question").value = "Now another answer"; await operation(env, store, "sendChatQuestion()"); assert.equal(store.problems.get(openId).status, "open", "later answers never automatically resolve previous problems");
  env.get("chat-question").value = "Failed model request"; const failure = env.evaluate("sendChatQuestion()"); await settle(env, store, item => item.url === "/study/chat"); const failed = env.requests.find(item => !item.settled && item.url === "/study/chat"); failed.settled = true; failed.resolve({ ok: false, status: 503, json: async () => ({ detail: "safe", problem_id: openId, problem_save_failed: false }) }); await failure; await settle(env, store); assert.match(env.get("chat-status").textContent, /已记入/); assert(env.get("chat-keep-problem").hidden); assert.equal(env.get("chat-question").value, "Failed model request");
  env.get("chat-messages").querySelectorAll(".chat-record-problem").at(-1).click(); await settle(env, store); assert.equal(store.problems.size, 2);
  env.get("problems-button").click(); await settle(env, store); env.get("select-all-problems").checked = true; env.get("select-all-problems").dispatch("change"); assert.equal(env.evaluate("selectedProblems.size"), 2);
  env.get("select-all-problems").checked = false; env.get("select-all-problems").dispatch("change"); const onlySelected = env.get("problem-list").querySelector("input"); onlySelected.checked = true; onlySelected.dispatch("change"); assert.equal(env.evaluate("selectedProblems.size"), 1);
  const selectedId = env.evaluate("[...selectedProblems][0]"); env.get("delete-problems").click(); assert.equal(store.problems.size, 2); assert.match(env.get("library-confirm-description").textContent, /所选 1 条/); env.get("library-confirm-yes").click(); await settle(env, store); assert.equal(store.problems.size, 1); assert(!store.problems.has(selectedId)); assert(store.histories.has(recordId)); env.get("library-close").click();
  env.context.stateCandidate = state({ chat_turns: [JSON.parse(env.evaluate("JSON.stringify(studyState.chat_turns[0])"))] }); delete env.context.stateCandidate.chat_turns[0].answer_status; assert.equal(env.evaluate("validateStudyState(stateCandidate,graph).chat_turns[0].answer_status"), "answered", "older chat records remain compatible");
  env.context.stateCandidate.chat_turns[0].answer_status = "proved"; assert.throws(() => env.evaluate("validateStudyState(stateCandidate,graph)"), /invalid-workspace/);
  assert.equal(analyzeCount(), 2); assert(!env.requests.some(item => item.url === "/settings/chatgpt/login"));
}

async function main() {
  await checkFullBackupAndExamples();
  const env = makeEnvironment({ saved: { version: 2, graph: fixture, mastery: { base: flags }, draft: "Old goal", source: "generated" } });
  const store = backend();
  await settle(env, store);
  assert.equal(store.histories.size, 1, "legacy workspace migrates once");
  assert.deepEqual(env.snapshot().known, ["base"], "legacy mastery is retained");
  assert(env.storage.get("mathpath.v1.workspace"), "legacy copy is preserved for recovery");
  assert.match(env.storage.get("mathpath.v04.legacy-import"), /^done:/);
  await operation(env, store, "initializeLibrary()");
  assert.equal(store.histories.size, 1, "reinitialization does not duplicate migration");
  assert(!env.requests.some(item => item.url === "/analyze" || item.url === "/settings/chatgpt/login"), "startup never generates or logs in");
  assert.equal(env.evaluate("historyDirty"), 0, "restoration does not write or mark dirty");

  // The original safe content validators remain in force.
  env.context.lessonCandidate = lessonFixture();
  assert.doesNotThrow(() => env.evaluate('validateLesson(lessonCandidate,"vector")'));
  env.context.lessonCandidate.illustration.elements[0].href = "javascript:alert(1)";
  assert.throws(() => env.evaluate('validateLesson(lessonCandidate,"vector")'), /invalid-lesson/);
  const oldGraph = env.snapshot().graph;
  env.context.bad = { ...fixture, nodes: [{ id: "goal", label: "bad", prerequisite_sets: [["goal"]] }] };
  assert.throws(() => env.evaluate("validateGraph(bad)"), /invalid-graph/);
  assert.deepEqual(env.snapshot().graph, oldGraph);

  env.evaluate('openLesson("vector")'); await settle(env, store);
  assert(!env.get("lesson-content").hidden);
  assert.equal(env.get("lesson-illustration-viewport").querySelectorAll("script,img,image,foreignObject").length, 0);
  assert.match(treeText(env.get("lesson-illustration-viewport")), /<img src=x onerror=alert\(1\)>/);
  env.get("lesson-notes").value = "My own mathematical reasoning."; env.get("lesson-notes").dispatch("input");
  await operation(env, store, "flushHistory()");
  const firstId = env.evaluate("currentHistory.id");
  assert.equal(store.histories.get(firstId).state.notes.vector, "My own mathematical reasoning.");
  assert(store.histories.get(firstId).state.lessons.vector, "loaded lessons persist in the history");
  assert.equal(env.snapshot().known.length, 1, "notes and lesson loading do not mark mastery");

  // The original micro-exercise path uses conservative server feedback too.
  const microChoice = env.get("exercise-options").querySelectorAll("input")[0]; microChoice.checked = true; microChoice.dispatch("change");
  env.get("exercise-form").dispatch("submit"); await settle(env, store);
  assert.equal(env.evaluate("studyState.attempts.at(-1).outcome"), "ungraded", "a generated answer key does not certify independent success");
  assert.equal(env.evaluate("studyState.attempts.at(-1).task.question"), "Which answer?");
  assert(env.evaluate("studyState.attempts.at(-1).feedback.review_required"));
  env.get("exercise-form").dispatch("submit"); await settle(env, store);
  assert.equal(env.evaluate("studyState.attempts.at(-1).hint_level"), 3, "repeated micro attempts after seeing the reference count assistance");

  const card = env.get("adaptive-practice-tasks").querySelector("article");
  assert(card, "open-answer exercise is available");
  const answer = card.querySelector("textarea"); answer.value = "I justify each step.";
  const form = card.querySelector("form"); form.dispatch("submit"); await settle(env, store);
  assert.equal(env.evaluate("studyState.attempts.at(-1).outcome"), "ungraded", "local open-answer comparison is not automatic success");
  assert(!JSON.parse(env.requests.filter(item => item.url === "/study/feedback").at(-1).options.body).use_model);
  assert.equal(env.snapshot().known.length, 1);
  const nextAction = card.querySelector(".teaching-next-action"); assert(!nextAction.hidden);
  const requestCountBeforeAction = env.requests.length; nextAction.click();
  assert(card.querySelector(".task-reference").open, "feedback recommendation is an actual reference action");
  assert.equal(env.requests.length, requestCountBeforeAction, "next teaching action does not call a model");
  const check = card.querySelector(".model-feedback-choice").querySelector("input"); check.checked = true;
  form.dispatch("submit"); await settle(env, store);
  assert(JSON.parse(env.requests.filter(item => item.url === "/study/feedback").at(-1).options.body).use_model, "model feedback requires explicit choice");
  assert.equal(env.evaluate("studyState.attempts.at(-1).outcome"), "ungraded", "model candidate feedback needs review");
  card.querySelector(".task-hints").querySelector("button").click();
  assert.equal(env.evaluate("studyState.attempts.at(-1).hint_level"), 3, "already viewed reference retains assistance evidence");
  const reference = card.querySelector(".task-reference"); reference.open = true; reference.dispatch("toggle");
  assert.equal(env.evaluate("studyState.attempts.at(-1).hint_level"), 3, "reference viewing is evidence of assistance");
  assert.equal(env.evaluate("studyState.attempts.at(-1).outcome"), "viewed");
  const selfButton = card.querySelector(".self-check-actions").querySelectorAll("button")[0]; selfButton.click();
  assert.equal(env.evaluate("studyState.attempts.at(-1).outcome"), "hinted", "viewed reference cannot count as independent success");
  assert(env.evaluate('!!studyState.reviews.vector'), "answering schedules a review");
  await operation(env, store, "flushHistory()");
  assert(store.histories.get(firstId).state.attempts.length >= 5);
  assert.match(treeText(env.get("attempt-history")), /当时的题目/);
  env.context.changedTask = task({ question: "A different question with the same task id" });
  env.evaluate("renderTasks(ui.adaptivePracticeTasks,[changedTask])");
  assert.equal(env.get("adaptive-practice-tasks").querySelector("textarea").value, "", "a task id does not reuse answers for a changed question");
  const priorAttempts = env.evaluate("JSON.stringify(studyState.attempts)");
  env.context.capTask = task();
  env.evaluate("studyState.attempts=Array.from({length:500},()=>({id:uuid()}))");
  const firstCapId = env.evaluate("studyState.attempts[0].id");
  assert.equal(env.evaluate('recordAttempt(capTask,"Extra answer",0)'), null);
  assert.equal(env.evaluate("studyState.attempts.length"), 500); assert.equal(env.evaluate("studyState.attempts[0].id"), firstCapId);
  assert.match(env.get("history-save-status").textContent, /本次新增作答未保存/);
  env.context.priorAttempts = JSON.parse(priorAttempts); env.evaluate("studyState.attempts=priorAttempts");

  // Multi-project CRUD and selections use explicit confirmation.
  env.get("library-button").click(); await settle(env, store);
  assert(!env.get("library-panel").hidden);
  assert(env.get("goal-form").closest("[inert]"));
  env.get("manage-projects").click(); env.get("project-create-title").value = "Topology"; env.get("project-create-form").dispatch("submit"); await settle(env, store);
  assert.equal(store.projects.size, 1);
  const projectId = [...store.projects.keys()][0];
  env.get("select-all-histories").checked = true; env.get("select-all-histories").dispatch("change");
  assert.match(env.get("history-selected-count").textContent, /1/);
  env.get("move-history-project").value = projectId; env.get("move-histories").click(); await settle(env, store);
  assert.equal(store.histories.get(firstId).project_id, projectId);
  assert.equal(env.evaluate("currentHistory.revision"), store.histories.get(firstId).revision, "batch move refreshes active revision");
  env.get("select-all-projects").checked = true; env.get("select-all-projects").dispatch("change"); env.get("delete-projects").click();
  assert(!env.get("library-confirmation").hidden);
  assert.equal(store.projects.size, 1, "delete waits for confirmation");
  assert.match(env.get("library-confirm-description").textContent, /全部历史都会保留/);
  env.get("library-confirm-yes").click(); await settle(env, store);
  assert.equal(store.projects.size, 0); assert.equal(store.histories.size, 1); assert.equal(store.histories.get(firstId).project_id, null);

  // Exports include learning data but no model configuration or credentials.
  env.get("library-close").click(); env.get("export-button").click();
  const exported = JSON.parse(await env.downloads.at(-1).text());
  assert.equal(exported.version, 2); assert(exported.state.notes.vector); assert(exported.state.attempts.length);
  for (const key of ["api_key", "modelSettings", "access_token", "api_settings", "authorization"]) assert(!JSON.stringify(exported).includes(`"${key}"`));
  env.context.exportFile = file(exported);
  await operation(env, store, "importWorkspace(exportFile)");
  assert.equal(store.histories.size, 2, "import creates a separate history");
  assert.equal(env.get("lesson-notes").value, "My own mathematical reasoning.");
  const secondId = env.evaluate("currentHistory.id");
  const lessonCount = env.requests.filter(item => item.url === "/lesson").length;
  env.evaluate('openLesson("vector")'); await settle(env, store);
  assert.equal(env.requests.filter(item => item.url === "/lesson").length, lessonCount, "restored lesson opens without a model request");

  // A conflict retains local changes and prevents navigation from overwriting them.
  env.get("lesson-notes").value = "Unsaved conflict edit"; env.get("lesson-notes").dispatch("input");
  ++store.histories.get(secondId).revision;
  const saving = env.evaluate("flushHistory().catch(()=>false)"); await settle(env, store); await saving;
  assert(env.evaluate("historyConflict"));
  assert.equal(env.evaluate("studyState.notes.vector"), "Unsaved conflict edit");
  await operation(env, store, `openHistory("${firstId}")`);
  assert.equal(env.evaluate("currentHistory.id"), secondId, "conflicted navigation keeps the original history");
  env.evaluate("historyConflict=false; currentHistory.revision=" + store.histories.get(secondId).revision);
  await operation(env, store, "flushHistory()");

  // Delayed feedback belongs to its original record and cannot leak on switching.
  env.evaluate('openLesson("vector")'); await settle(env, store);
  const currentCard = env.get("adaptive-practice-tasks").querySelector("article"); currentCard.querySelector("textarea").value = "Late response"; currentCard.querySelector("form").dispatch("submit");
  await settle(env, store, request => request.url === "/study/feedback");
  const late = env.requests.find(item => !item.settled && item.url === "/study/feedback");
  await operation(env, store, `openHistory("${firstId}")`, request => request === late);
  const attemptsBefore = env.evaluate("studyState.attempts.length"); late.settled = true; late.resolve(store.handle(late)); await settle(env, store);
  assert.equal(env.evaluate("studyState.attempts.length"), attemptsBefore, "stale feedback never modifies another record");

  // Delete the current record, then mutate retained view: it must not resurrect.
  env.get("library-button").click(); await settle(env, store);
  env.evaluate(`selectedHistories=new Set(["${firstId}"]); renderLibrarySelection()`); env.get("delete-histories").click();
  assert(store.histories.has(firstId)); env.get("library-confirm-yes").click(); await settle(env, store);
  assert(!store.histories.has(firstId)); assert.equal(env.evaluate("currentHistory"), null);
  const countAfterDelete = store.histories.size; env.evaluate('updateMastery("base",{intuition:false})');
  await settle(env, store); await operation(env, store, "flushHistory()");
  assert.equal(store.histories.size, countAfterDelete, "autosave never recreates a deleted history");
  assert.match(env.get("history-save-status").textContent, /不会再次自动保存/);

  // A fresh successful graph starts a new record; a failed generation creates none.
  env.get("library-close").click(); await operation(env, store, 'loadRequestedGraph("example")');
  assert.equal(store.histories.size, countAfterDelete + 1);
  const fresh = env.evaluate("currentHistory.id");
  const generation = env.evaluate('loadRequestedGraph("generated","A new mathematical goal")');
  await settle(env, store, request => request.url === "/analyze");
  const failed = env.requests.find(item => !item.settled && item.url === "/analyze");
  failed.settled = true; failed.resolve({ ok: false, status: 503, json: async () => ({ detail: "Unavailable" }) });
  await settle(env, store); await generation;
  assert.equal(env.evaluate("currentHistory.id"), fresh); assert.equal(store.histories.size, countAfterDelete + 1);

  // Modal keyboard focus and safe legacy import remain usable on narrow screens.
  env.setNarrow(true); env.get("library-button").click(); await settle(env, store);
  const focusables = env.evaluate("libraryFocusable()"); focusables.at(-1).focus();
  assert(env.document.dispatch("keydown", { key: "Tab", shiftKey: false }).defaultPrevented);
  assert.equal(env.document.activeElement, focusables[0]);
  env.document.dispatch("keydown", { key: "Escape" }); assert(env.get("library-panel").hidden);
  env.get("model-settings-button").click(); await settle(env, store);
  assert(!env.get("chatgpt-login-section").hidden);
  assert(!env.requests.some(item => item.url === "/settings/chatgpt/login"), "opening settings never initiates login");
  env.get("model-provider").value = "api"; env.get("model-provider").dispatch("change");
  assert(env.get("chatgpt-login-section").hidden);
  assert(!env.storage.has("api_key")); env.get("model-settings-close").click();
  env.get("library-button").click(); await settle(env, store);
  env.evaluate("openModelSettings()"); await settle(env, store);
  assert(env.get("library-panel").hidden && !env.get("model-settings-panel").hidden, "native settings action closes the library modal before opening its own focus trap");
  env.evaluate("openLibrary()"); await settle(env, store);
  assert(env.get("model-settings-panel").hidden && !env.get("library-panel").hidden, "opening library closes settings and stops its polling");
  assert.equal(env.evaluate("chatgptPollTimer"), null);
  env.get("library-close").click();

  await checkFloatingChat();
  await checkV042GuidanceAndProblems();

  // Validate actual packaged Python models and math content, not just broad mocks.
  const actual = actualPythonJSON(`import json
from lesson_builder import load_example_graph,_curated_lesson
from study_builder import get_study_tasks,build_learning_feedback
g=load_example_graph()
cards={node.id:_curated_lesson(g,node.id) for node in g.nodes}
tasks=get_study_tasks(g)
for node in g.nodes: tasks+=get_study_tasks(g,node.id,lesson=cards[node.id])
tasks=list({item.id:item for item in tasks}.values())
feedback=[]
for item in tasks:
 feedback.append(build_learning_feedback(g,item.node_id,item.id,str(item.correct_index) if item.format=='choice' else '不确定',lesson=cards[item.node_id],use_model=False).model_dump())
print(json.dumps({'graph':g.model_dump(),'lessons':{key:value.model_dump() for key,value in cards.items()},'tasks':[item.model_dump() for item in tasks],'feedback':feedback},ensure_ascii=False))`);
  env.context.actualContent = actual;
  assert.doesNotThrow(() => env.evaluate("validateGraph(actualContent.graph)"));
  for (const [id, lesson] of Object.entries(actual.lessons)) { env.context.realLesson = lesson; env.context.realId = id; assert.doesNotThrow(() => env.evaluate("validateLesson(realLesson,realId)")); }
  env.evaluate("const actualIds=new Set(actualContent.graph.nodes.map(node=>node.id)); actualContent.tasks.forEach(task=>validateTask(task,actualIds)); actualContent.feedback.forEach(validateFeedback)");
  assert(actual.tasks.length >= 50, "actual diagnostic, final, mixed and node exercises all satisfy frontend validators");
  const actualState = state({ graph_source: "example", mastery: { chains_as_formal_sums: flags }, lessons: actual.lessons, notes: { chains_as_formal_sums: "自己的笔记" }, chat_turns: [{ id: "66666666-6666-4666-8666-666666666666", node_id: "chains_as_formal_sums", question: "链的系数可以是负数吗？", response: "整数系数允许负数；核对当前方向约定。", source: "model_candidate", review_required: true, created_at: "2026-10-13T09:00:00+08:00" }] });
  env.context.actualState = actualState;
  const checked = JSON.parse(env.evaluate("JSON.stringify(validateStudyState(actualState,validateGraph(actualContent.graph)))"));
  const roundtrip = actualPythonJSON(`import json,sys
from library_models import HistoryCreate
value=HistoryCreate.model_validate_json(sys.stdin.read())
print(json.dumps({'nodes':len(value.graph.nodes),'lessons':len(value.state.lessons),'mastery':value.state.mastery['chains_as_formal_sums'].model_dump(),'chat':value.state.chat_turns[0].model_dump()}))`,
    JSON.stringify({ title: "实际同调内容的契约验证", goal: "理解同调群取商", project_id: null, graph: actual.graph, state: checked }));
  assert.equal(roundtrip.nodes, 8); assert.equal(roundtrip.lessons, 8); assert.deepEqual(roundtrip.mastery, flags);
  assert.equal(roundtrip.chat.question, actualState.chat_turns[0].question); assert(roundtrip.chat.review_required);

  // Preserve the full task snapshot through the real backend state validator.
  const selected = actual.tasks.find(item => item.format === "open");
  const fullAttempt = { id: "22222222-2222-4222-8222-222222222222", node_id: selected.node_id, task_id: selected.id, task: selected, answer: "我的推理", hint_level: 0, attempt_type: selected.kind, outcome: "ungraded", created_at: new Date().toISOString(), feedback: actual.feedback.find(item => item.task_id === selected.id) };
  actualState.attempts = [fullAttempt]; env.context.actualState = actualState;
  const checkedAttempt = JSON.parse(env.evaluate("JSON.stringify(validateStudyState(actualState,validateGraph(actualContent.graph)))"));
  const taskRoundtrip = actualPythonJSON(`import json,sys
from library_models import HistoryCreate
value=HistoryCreate.model_validate_json(sys.stdin.read())
print(json.dumps({'task':value.state.attempts[0].task.model_dump()}))`, JSON.stringify({ title: "作答快照", goal: "解释", project_id: null, graph: actual.graph, state: checkedAttempt }));
  assert.equal(taskRoundtrip.task.question, selected.question);

  console.log("MathPath v0.5.0 frontend offline checks passed: full backup download/preview/cancel/append/repeat/size and delayed-file checks, offline example selection, goal/chat scope choice without automatic generation, reference-book triggers/cache/links, unresolved problems/manual records/status/delete/failure retry, floating chat movement/resize/keyboard/modal suspension, context/multiturn/100-turn preservation, cancellation/stale replies/save failures, safe text, migration, histories, projects, batch selection, safe deletion, revisions, learning records, optional feedback, teaching actions, hints, review, snapshot identity, record limits, import/export, modal focus, credential isolation and actual Python/math-content/chat schema roundtrips.");
}

const watchdog = setTimeout(() => { console.error("Offline frontend checks stalled with an unresolved request"); process.exitCode = 1; }, 25000);
main().then(() => clearTimeout(watchdog)).catch(error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
