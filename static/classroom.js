"use strict";

const MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024;
const ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ACTIVE_STATES = new Set(["uploading_local", "queued", "uploading_remote", "processing_remote", "analyzing", "cleaning_remote"]);
const STATUS_LABELS = { uploading_local: "视频上传到本机", uploaded: "视频已保存", queued: "等待解析", uploading_remote: "上传到视频服务", processing_remote: "视频服务处理中", analyzing: "逐段解析中", cleaning_remote: "清理临时视频", completed: "各时间段处理完毕", failed: "解析中断", cancelled: "已停止解析", interrupted: "任务已中断" };
const KIND_LABELS = { introduction: "引入", definition: "定义", theorem: "命题 / 定理", proof: "证明", example: "例题", exercise: "课堂习题", discussion: "讨论", other: "课堂内容" };
const EVIDENCE_LABELS = { audio: "声音", visual: "画面", audio_visual: "声音与画面", unclear: "来源不清晰" };
const classroom = Object.fromEntries([
  "lecture-refresh", "lecture-history", "lecture-history-status", "video-dropzone", "lecture-video-file", "selected-video", "lecture-upload", "lecture-upload-cancel", "lecture-upload-progress", "lecture-upload-status", "classroom-error", "lecture-workspace", "current-lecture-heading", "lecture-meta", "lecture-status-badge", "lecture-player", "lecture-player-note", "lecture-model-settings", "lecture-analysis-form", "lecture-api-key", "lecture-video-model", "lecture-chunk-seconds", "lecture-remote-consent", "lecture-request-estimate", "lecture-start", "lecture-cancel", "lecture-export-markdown", "lecture-export-json", "lecture-delete", "lecture-coverage-value", "lecture-analysis-progress", "lecture-job-status", "lecture-job-error", "lecture-cleanup-warning", "lecture-timeline-empty", "lecture-clips", "lecture-partial-note", "lecture-delete-confirm", "lecture-delete-description", "lecture-delete-no", "lecture-delete-yes", "classroom-welcome",
].map(id => [id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()), document.getElementById(id)]));
let selectedVideo = null;
let selectedDuration = null;
let currentLecture = null;
let lectureList = [];
let selectionVersion = 0;
let historyVersion = 0;
let uploadRequest = null;
let metadataVersion = 0;
let metadataCleanup = null;
let actionBusy = false;
let selectionPending = false;
let pollTimer = null;
let selectedController = null;
let renderedVideoSource = "";
const renderedClips = new Map();

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function setClassroomError(message) {
  classroom.classroomError.textContent = message;
  classroom.classroomError.hidden = !message;
}

function cleanText(value, maximum = 20000) {
  return typeof value === "string" && value.length <= maximum;
}

function safeNumber(value, maximum = 10800) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= maximum;
}

function validateLecture(value, summary = false) {
  if (!value || !ID_PATTERN.test(value.id) || !cleanText(value.filename, 200) || !value.filename.trim() ||
      !Object.hasOwn(STATUS_LABELS, value.status) || !Number.isInteger(value.size_bytes) || value.size_bytes < 0 || value.size_bytes > MAX_VIDEO_BYTES ||
      (value.size_bytes === 0 && (!["uploading_local", "interrupted"].includes(value.status) || value.completed_chunks !== 0)) ||
      !cleanText(value.mime_type, 100) || !cleanText(value.created_at, 60) || !cleanText(value.updated_at, 60) ||
      value.source !== "model_candidate" || value.review_required !== true ||
      !Number.isInteger(value.completed_chunks) || value.completed_chunks < 0 || value.completed_chunks > 360 ||
      !Number.isInteger(value.total_chunks) || value.total_chunks < value.completed_chunks || value.total_chunks > 360 ||
      !safeNumber(value.processed_seconds) || !safeNumber(value.coverage_ratio, 1) ||
      typeof value.cleanup_failed !== "boolean" || (value.video_available !== undefined && typeof value.video_available !== "boolean") || (value.error !== null && !cleanText(value.error, 2000)) ||
      (value.duration_seconds !== null && (!safeNumber(value.duration_seconds) || value.duration_seconds === 0)) ||
      (value.estimated_duration_seconds !== null && !safeNumber(value.estimated_duration_seconds)) ||
      (value.model !== null && !cleanText(value.model, 120)) || (value.chunk_seconds !== null && ![180, 300, 600].includes(value.chunk_seconds))) {
    throw new Error("课堂记录格式无效，请刷新列表后重试。");
  }
  if (value.duration_seconds !== null && value.processed_seconds > value.duration_seconds + .05) throw new Error("课堂处理区间超出了视频时长，请重新读取记录。");
  if (!summary) {
    if (!Array.isArray(value.clips) || value.clips.length !== value.completed_chunks) throw new Error("课堂分段记录不完整，请重新读取。");
    let previousEnd = 0;
    for (const [index, clip] of value.clips.entries()) {
      if (!clip || clip.index !== index || !safeNumber(clip.start_seconds) || !safeNumber(clip.end_seconds) ||
          clip.end_seconds <= clip.start_seconds || Math.abs(clip.start_seconds - previousEnd) > .05 ||
          (value.duration_seconds !== null && clip.end_seconds > value.duration_seconds + .05)) throw new Error("课堂时间区间不连续，请重新读取记录。");
      validateClip(clip.analysis, clip.start_seconds, clip.end_seconds);
      previousEnd = clip.end_seconds;
    }
    if (Math.abs(previousEnd - value.processed_seconds) > .05) throw new Error("课堂进度与分段记录不一致，请刷新重试。");
  }
  return value;
}

function textList(value, maximumItems = 80, maximumText = 20000) {
  return Array.isArray(value) && value.length <= maximumItems && value.every(item => cleanText(item, maximumText));
}

function validateClip(value, start, end) {
  if (!value || !cleanText(value.title, 300) || !cleanText(value.overview) || !Array.isArray(value.items) || value.items.length > 80 ||
      !textList(value.learning_goals) || !textList(value.coverage_notes) || !textList(value.uncertainties) ||
      !Array.isArray(value.practice) || value.practice.length > 20) throw new Error("课堂解析内容格式无效，请重新读取记录。");
  for (const item of value.items) {
    if (!item || !safeNumber(item.start_seconds) || !safeNumber(item.end_seconds) || item.start_seconds < start - .05 ||
        item.end_seconds > end + .05 || item.end_seconds <= item.start_seconds || !Object.hasOwn(KIND_LABELS, item.kind) ||
        !Object.hasOwn(EVIDENCE_LABELS, item.evidence) || !cleanText(item.title, 300) || !cleanText(item.source_summary) ||
        !cleanText(item.explanation) || !textList(item.formulas) || !textList(item.steps) || !textList(item.uncertainties)) throw new Error("课堂内容的时间或字段无效，请刷新重试。");
  }
  for (const practice of value.practice) {
    if (!practice || !cleanText(practice.question) || !cleanText(practice.hint) || !cleanText(practice.answer) ||
        !["from_video", "supplement"].includes(practice.origin)) throw new Error("课堂练习格式无效，请刷新重试。");
  }
}

function clock(seconds) {
  const total = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  return total >= 3600
    ? `${Math.floor(total / 3600)}:${String(Math.floor(total % 3600 / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`
    : `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function bytesLabel(bytes) {
  return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GiB` : `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
}

function mathText(element, text) {
  // Only KaTeX receives TeX. All ordinary model text remains literal DOM text.
  const pattern = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$(?!\s)[^$\n]+?\$)/g;
  let position = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > position) element.append(node("span", "", text.slice(position, match.index)));
    const token = match[0];
    const displayMode = token.startsWith("$$") || token.startsWith("\\[");
    const tex = token.startsWith("$") ? token.slice(displayMode ? 2 : 1, displayMode ? -2 : -1) : token.slice(2, -2);
    const part = node("span", "math-fragment");
    try {
      if (!window.katex?.render) throw new Error("renderer-unavailable");
      window.katex.render(tex, part, { displayMode, throwOnError: true, trust: false, strict: "ignore", maxExpand: 1000 });
    } catch { part.textContent = token; }
    element.append(part);
    position = match.index + token.length;
  }
  if (position < text.length) element.append(node("span", "", text.slice(position)));
  if (!text) element.textContent = "";
  return element;
}

async function requestJSON(url, { method = "GET", body, signal, timeoutMs = 30000 } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, timeoutMs);
  try {
    const response = await fetch(url, { method, cache: "no-store", credentials: "same-origin", signal: controller.signal,
      ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
    const value = await response.json().catch(() => null);
    if (!response.ok) throw new Error(value && cleanText(value.detail, 2000) ? value.detail : "课堂请求未完成，请稍后重试。");
    return value;
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("读取或提交已停止，请检查当前课堂状态后重试。");
    throw error instanceof Error ? error : new Error("无法连接本机课堂服务。");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

function updateControls() {
  const active = currentLecture && ACTIVE_STATES.has(currentLecture.status);
  classroom.lectureUpload.disabled = !selectedVideo || Boolean(uploadRequest);
  classroom.lectureVideoFile.disabled = Boolean(uploadRequest);
  classroom.lectureUploadCancel.hidden = !uploadRequest;
  classroom.lectureStart.disabled = !currentLecture || currentLecture.video_available === false || active || actionBusy || selectionPending || !classroom.lectureRemoteConsent.checked || !classroom.lectureApiKey.value.trim();
  classroom.lectureStart.textContent = currentLecture?.video_available === false ? "请重新上传完整视频" : currentLecture?.status === "completed" ? "解析已完成" : currentLecture?.clips.length ? "继续解析未完成部分" : "开始逐段解析";
  if (currentLecture?.status === "completed") classroom.lectureStart.disabled = true;
  classroom.lectureCancel.hidden = !active || currentLecture.status === "uploading_local";
  classroom.lectureCancel.disabled = actionBusy || selectionPending;
  classroom.lectureDelete.disabled = !currentLecture || active || actionBusy || selectionPending;
  classroom.lectureApiKey.disabled = Boolean(active || actionBusy || selectionPending);
  classroom.lectureVideoModel.disabled = Boolean(active || actionBusy || selectionPending || currentLecture?.clips.length);
  classroom.lectureChunkSeconds.disabled = Boolean(active || actionBusy || selectionPending || currentLecture?.clips.length);
  classroom.lectureRemoteConsent.disabled = Boolean(active || actionBusy || selectionPending);
  const duration = currentLecture?.duration_seconds || currentLecture?.estimated_duration_seconds;
  const chunk = Number(classroom.lectureChunkSeconds.value);
  classroom.lectureRequestEstimate.textContent = duration
    ? `按${currentLecture.duration_seconds ? "视频服务确认的时长" : "浏览器预计时长"} ${clock(duration)}，约需 ${Math.ceil(duration / chunk)} 次分段请求。续跑仅解析未完成部分；重传视频仍可能产生处理用量。`
    : "视频时长确认后，将逐段处理整堂课。每段会调用一次视频模型。";
}

function renderHistory() {
  classroom.lectureHistory.replaceChildren();
  for (const lecture of lectureList) {
    const row = node("li");
    const button = node("button", "history-select");
    button.type = "button";
    button.setAttribute("aria-current", String(lecture.id === currentLecture?.id));
    button.append(node("span", "history-name", lecture.filename), node("span", "history-subtitle", `${STATUS_LABELS[lecture.status]} · ${lecture.completed_chunks} 段已保存`));
    button.addEventListener("click", () => selectLecture(lecture.id));
    row.append(button); classroom.lectureHistory.append(row);
  }
  classroom.lectureHistoryStatus.textContent = lectureList.length ? `${lectureList.length} 条课堂记录` : "还没有课堂记录，上传第一段视频开始。";
}

async function refreshHistory() {
  const version = ++historyVersion;
  classroom.lectureRefresh.disabled = true;
  try {
    const records = await requestJSON("/lectures");
    if (version !== historyVersion) return;
    if (!Array.isArray(records) || records.length > 2000) throw new Error("课堂列表格式无效，请重试。");
    lectureList = records.map(record => validateLecture(record, true));
    renderHistory();
  } catch (error) {
    if (version === historyVersion) classroom.lectureHistoryStatus.textContent = error.message || "无法读取课堂记录，请刷新重试。";
  } finally { if (version === historyVersion) classroom.lectureRefresh.disabled = false; }
}

function seekVideo(time) {
  if (!currentLecture || !safeNumber(time)) return;
  const player = classroom.lecturePlayer;
  try {
    player.currentTime = time;
    player.focus({ preventScroll: true });
    player.scrollIntoView({ block: "nearest", behavior: "smooth" });
    classroom.lecturePlayerNote.textContent = `已定位到 ${clock(time)}，点击播放可核对原课堂。`;
  } catch { classroom.lecturePlayerNote.textContent = "视频元信息尚未载入，请先点击播放器，再选择时间。"; }
}

function seekButton(start, end) {
  const button = node("button", "seek-button", `▷ ${clock(start)} — ${clock(end)}`);
  button.type = "button";
  button.setAttribute("aria-label", `回看 ${clock(start)} 开始的课堂片段`);
  button.addEventListener("click", () => seekVideo(start));
  return button;
}

function addList(parent, heading, values, uncertain = false) {
  if (!values.length) return;
  const section = node("section", uncertain ? "uncertain-note" : "");
  section.append(node("h4", "", heading));
  const list = node("ul", "lecture-list");
  for (const text of values) list.append(mathText(node("li"), text));
  section.append(list); parent.append(section);
}

function renderClip(clip) {
  const analysis = clip.analysis;
  const card = node("details", "lecture-clip");
  card.setAttribute("data-clip-index", String(clip.index));
  card.open = clip.index === 0;
  const summary = node("summary");
  const heading = node("span");
  heading.append(node("span", "clip-summary-time", `第 ${clip.index + 1} 段 · ${clock(clip.start_seconds)} — ${clock(clip.end_seconds)}`), node("span", "clip-summary-title", analysis.title));
  summary.append(heading); card.append(summary);
  card.append(mathText(node("p", "clip-overview"), analysis.overview), seekButton(clip.start_seconds, clip.end_seconds));
  addList(card, "这一段的学习目标", analysis.learning_goals);
  for (const [itemIndex, item] of analysis.items.entries()) {
    const section = node("section", "lecture-item");
    section.append(seekButton(item.start_seconds, item.end_seconds));
    const title = node("div", "item-heading");
    title.append(node("span", "item-kind", KIND_LABELS[item.kind]), mathText(node("h4"), item.title));
    section.append(title);
    const original = node("div", "source-note");
    original.append(node("strong", "", "课堂内容（模型识别）"), node("span", "source-badge", `依据：${EVIDENCE_LABELS[item.evidence]}`));
    original.append(mathText(node("p"), item.source_summary)); section.append(original);
    if (item.explanation.trim()) {
      const explanation = node("div", "supplement-note");
      explanation.append(node("h4", "", "辅助解读"), mathText(node("p"), item.explanation)); section.append(explanation);
    }
    addList(section, "公式与符号（待核对）", item.formulas);
    addList(section, "推导步骤（模型整理）", item.steps);
    addList(section, "这里需要回看核对", item.uncertainties, true);
    if (item.evidence === "unclear" && !item.uncertainties.length) section.append(node("p", "uncertain-note", "此处的声音或画面证据不清晰，请回看原视频，不据此确定公式或结论。"));
    const actions = node("div", "item-actions");
    const stuck = node("button", "text-button", "这一步卡住了");
    stuck.type = "button";
    stuck.addEventListener("click", () => window.MathPathTutor?.selectItem(clip.index, itemIndex));
    actions.append(stuck);
    const learn = node("a", "", "围绕这个知识点建立学习地图 →");
    learn.href = `/?lecture_goal=${encodeURIComponent(item.title.slice(0, 1000))}`;
    actions.append(learn); section.append(actions); card.append(section);
  }
  if (analysis.practice.length) {
    const exercises = node("section", "clip-exercises");
    exercises.append(node("h4", "", "学完这一段，自己试一试"));
    for (const [index, task] of analysis.practice.entries()) {
      const taskNode = node("article", "lecture-exercise");
      taskNode.append(node("span", "item-kind", task.origin === "from_video" ? "课堂原题（模型识别）" : "辅助补充题"));
      taskNode.append(mathText(node("p"), `${index + 1}. ${task.question}`));
      for (const [label, value] of [["看一点提示", task.hint], ["对照参考答案", task.answer]]) {
        if (!value.trim()) continue;
        const detail = node("details");
        detail.append(node("summary", "", label), mathText(node("p"), value)); taskNode.append(detail);
      }
      exercises.append(taskNode);
    }
    card.append(exercises);
  }
  addList(card, "这一段的识别范围与缺口", analysis.coverage_notes);
  addList(card, "仍需核对", analysis.uncertainties, true);
  return card;
}

function renderClips() {
  const expected = new Set();
  for (const clip of currentLecture.clips) {
    expected.add(clip.index);
    const fingerprint = JSON.stringify(clip);
    const previous = renderedClips.get(clip.index);
    if (previous?.fingerprint === fingerprint) continue;
    const card = renderClip(clip);
    if (previous) { card.open = previous.card.open; previous.card.replaceWith(card); }
    else classroom.lectureClips.append(card);
    renderedClips.set(clip.index, { fingerprint, card });
  }
  for (const [index, value] of renderedClips) {
    if (!expected.has(index)) { value.card.remove(); renderedClips.delete(index); }
  }
  classroom.lectureTimelineEmpty.hidden = currentLecture.clips.length > 0;
}

function renderLecture(lecture) {
  if(lecture.status==="completed" && typeof window.dispatchEvent==="function" && typeof CustomEvent==="function") window.dispatchEvent(new CustomEvent("mathpath-content-ready",{detail:{source_kind:"lecture",source_id:lecture.id,source_title:lecture.filename}}));
  window.MathPathTutor?.onLecture(lecture);
  const changed = lecture.id !== currentLecture?.id;
  currentLecture = lecture;
  classroom.lectureWorkspace.hidden = false;
  classroom.classroomWelcome.hidden = true;
  classroom.currentLectureHeading.textContent = lecture.filename;
  const duration = lecture.duration_seconds ? `时长 ${clock(lecture.duration_seconds)}（已读取本机文件）` : lecture.estimated_duration_seconds ? `预计时长 ${clock(lecture.estimated_duration_seconds)}（浏览器元信息）` : "时长等待本机读取";
  classroom.lectureMeta.textContent = `${duration} · ${bytesLabel(lecture.size_bytes)}`;
  classroom.lectureStatusBadge.textContent = STATUS_LABELS[lecture.status];
  const videoSource = lecture.video_available === false ? "" : `/lectures/${lecture.id}/video`;
  if (videoSource !== renderedVideoSource) {
    if (videoSource) classroom.lecturePlayer.src = videoSource;
    else { classroom.lecturePlayer.pause(); classroom.lecturePlayer.removeAttribute("src"); classroom.lecturePlayer.load(); }
    renderedVideoSource = videoSource;
    classroom.lecturePlayerNote.textContent = videoSource ? "点击解析旁的时间，回到视频中的对应位置。" : "这条记录的完整原视频不可用，请重新上传视频。已有的解析仍可查看和导出。";
  }
  if (changed) {
    renderedClips.clear(); classroom.lectureClips.replaceChildren();
    if (!videoSource) classroom.lecturePlayerNote.textContent = "这条记录的完整原视频不可用，请重新上传视频。已有的解析仍可查看和导出。";
    classroom.lectureDeleteConfirm.hidden = true;
    if (lecture.model) classroom.lectureVideoModel.value = lecture.model;
    if (lecture.chunk_seconds) classroom.lectureChunkSeconds.value = String(lecture.chunk_seconds);
    classroom.lectureRemoteConsent.checked = false;
    classroom.lectureModelSettings.open = !lecture.clips.length && lecture.status === "uploaded";
  }
  if (lecture.total_chunks > 0) {
    classroom.lectureAnalysisProgress.value = Math.min(100, lecture.coverage_ratio * 100);
    classroom.lectureCoverageValue.textContent = `${lecture.completed_chunks} / ${lecture.total_chunks} 段`;
  } else {
    classroom.lectureAnalysisProgress.value = 0;
    classroom.lectureCoverageValue.textContent = ACTIVE_STATES.has(lecture.status) ? "准备中" : "尚未开始";
  }
  const statusMessages = {
    uploading_local: "视频正在上传到本机，完成后才能开始解析；关闭上传页面可能中断保存。",
    uploaded: "视频已保存在本机。点击“生成解析”，自动从开头处理到结尾。",
    queued: "任务已排队；尚未轮到时可以停止。",
    uploading_remote: "正在将本机视频上传到所选视频服务，请保留此课堂记录。",
    processing_remote: "视频服务正在准备声音与画面。这一阶段还没有新的课堂笔记。",
    analyzing: `已保存 ${lecture.completed_chunks} 段，接下来解析下一时间区间。`,
    cleaning_remote: "正在清理平台上的临时视频，解析内容已保存在本机。",
    completed: `已处理全片时间区间，共 ${lecture.completed_chunks} 段。请继续检查各段的识别缺口与公式。`,
    failed: `解析暂时中断，已保存 ${lecture.completed_chunks} 段。处理问题后可明确点击继续。`,
    cancelled: `已停止后续解析，保留 ${lecture.completed_chunks} 段。已经发出的请求可能仍计费。`,
    interrupted: `上次任务未正常结束，已保留 ${lecture.completed_chunks} 段。点击生成解析可继续。`,
  };
  classroom.lectureJobStatus.textContent = lecture.local_processing?.message || statusMessages[lecture.status];
  classroom.lectureJobError.textContent = lecture.error || "";
  classroom.lectureJobError.hidden = !lecture.error;
  classroom.lectureCleanupWarning.hidden = !lecture.cleanup_failed;
  classroom.lecturePartialNote.hidden = lecture.status === "completed" || lecture.completed_chunks === 0;
  classroom.lecturePartialNote.textContent = `当前仅有 ${clock(lecture.processed_seconds)} 以内的连续区间解析；后面的课堂还未完成，请勿当作全课笔记。`;
  classroom.lectureExportMarkdown.href = `/lectures/${lecture.id}/export?format=markdown`;
  classroom.lectureExportJson.href = `/lectures/${lecture.id}/export?format=json`;
  renderClips(); renderHistory(); updateControls();
  window.MathPathClassroomNotes?.onLecture(lecture);
  window.MathPathLocalVideo?.onLecture(lecture);
}

function schedulePoll(version) {
  clearTimeout(pollTimer);
  if (version === selectionVersion && currentLecture && ACTIVE_STATES.has(currentLecture.status)) pollTimer = setTimeout(() => pollLecture(version), 1800);
}

async function pollLecture(version) {
  if (version !== selectionVersion || !currentLecture) return;
  const id = currentLecture.id;
  try {
    const value = validateLecture(await requestJSON(`/lectures/${id}`, { signal: selectedController?.signal }));
    if (version !== selectionVersion || currentLecture?.id !== id) return;
    renderLecture(value);
    if (!ACTIVE_STATES.has(value.status)) await refreshHistory();
    schedulePoll(version);
  } catch (error) {
    if (version !== selectionVersion) return;
    classroom.lectureJobStatus.textContent = `${error.message || "暂时无法读取解析进度。"} 已显示的笔记仍保留；刷新记录可重新连接任务。`;
    // Stop polling after a network failure. A manual refresh reconnects without
    // triggering another provider request or duplicating a job.
  }
}

async function selectLecture(id) {
  if (!ID_PATTERN.test(id)) return;
  const version = ++selectionVersion;
  clearTimeout(pollTimer); selectedController?.abort();
  selectedController = new AbortController();
  selectionPending = true; classroom.lectureRemoteConsent.checked = false; updateControls();
  window.MathPathTutor?.onPending(true);
  window.MathPathClassroomNotes?.onPending(true); window.MathPathLocalVideo?.onPending(true);
  classroom.lectureDeleteConfirm.hidden = true;
  setClassroomError("");
  try {
    const value = validateLecture(await requestJSON(`/lectures/${id}`, { signal: selectedController.signal }));
    if (version !== selectionVersion) return;
    renderLecture(value);
    const url = new URL(window.location.href); url.searchParams.set("lecture", id);
    window.history.replaceState(null, "", url.pathname + url.search);
    schedulePoll(version);
  } catch (error) { if (version === selectionVersion) setClassroomError(error.message || "无法打开课堂记录。"); }
  finally { if (version === selectionVersion) { selectionPending = false; updateControls(); window.MathPathTutor?.onPending(false); window.MathPathClassroomNotes?.onPending(false); window.MathPathLocalVideo?.onPending(false); } }
}

function chooseVideo(file) {
  if (uploadRequest) return;
  ++metadataVersion; metadataCleanup?.(); metadataCleanup = null;
  selectedVideo = null; selectedDuration = null;
  classroom.lectureUploadStatus.textContent = ""; setClassroomError("");
  if (!file) { classroom.selectedVideo.textContent = "还没有选择文件"; updateControls(); return; }
  if (!/\.(mp4|webm|mov|m4v|avi)$/i.test(file.name) || !Number.isSafeInteger(file.size) || file.size <= 0 || file.size > MAX_VIDEO_BYTES) {
    classroom.selectedVideo.textContent = "请选择不超过 2 GiB 的 MP4 / WebM / MOV / AVI 视频。"; updateControls(); return;
  }
  selectedVideo = file;
  classroom.selectedVideo.textContent = `${file.name} · ${bytesLabel(file.size)}`; updateControls();
  const version = metadataVersion;
  const preview = document.createElement("video");
  const url = URL.createObjectURL(file);
  let cleaned = false;
  const cleanup = () => { if (cleaned) return; cleaned = true; clearTimeout(timer); preview.removeAttribute("src"); preview.load(); URL.revokeObjectURL(url); };
  const timer = setTimeout(cleanup, 8000);
  metadataCleanup = cleanup;
  preview.preload = "metadata";
  preview.addEventListener("loadedmetadata", () => {
    if (version === metadataVersion && selectedVideo === file && Number.isFinite(preview.duration) && preview.duration > 0) {
      if (preview.duration > 10800) {
        selectedVideo = null; classroom.selectedVideo.textContent = "当前单条课堂最多支持 3 小时，请先按课时分开视频。";
      } else {
        selectedDuration = preview.duration; classroom.selectedVideo.textContent = `${file.name} · ${bytesLabel(file.size)} · 预计 ${clock(preview.duration)}`;
      }
      updateControls();
    }
    cleanup();
  });
  preview.addEventListener("error", cleanup, { once: true });
  preview.src = url;
}

function uploadRawVideo(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    uploadRequest = xhr; updateControls();
    const query = new URLSearchParams({ filename: file.name });
    if (selectedDuration !== null) query.set("duration_seconds", String(selectedDuration));
    xhr.open("POST", `/lectures?${query}`);
    const suffix = file.name.split(".").pop().toLowerCase();
    const mime = { mp4: "video/mp4", m4v: "video/mp4", webm: "video/webm", mov: "video/quicktime", avi: "video/x-msvideo" }[suffix];
    xhr.setRequestHeader("Content-Type", mime);
    xhr.upload.addEventListener("progress", event => {
      if (uploadRequest !== xhr) return;
      classroom.lectureUploadProgress.hidden = false;
      if (event.lengthComputable && event.total > 0) {
        classroom.lectureUploadProgress.value = event.loaded / event.total * 100;
        classroom.lectureUploadStatus.textContent = event.loaded === event.total ? "视频已传送，正在确认本机保存结果…" : `正在保存到本机：${bytesLabel(event.loaded)} / ${bytesLabel(event.total)}`;
      } else classroom.lectureUploadProgress.removeAttribute("value");
    });
    xhr.addEventListener("load", () => {
      let value;
      try { value = JSON.parse(xhr.responseText); } catch { reject(new Error("视频上传未返回有效记录，请刷新课堂列表核对。")); return; }
      if (xhr.status < 200 || xhr.status >= 300) { reject(new Error(cleanText(value?.detail, 2000) ? value.detail : "视频上传失败，请重试。")); return; }
      try { resolve(validateLecture(value)); } catch (error) { reject(error); }
    });
    xhr.addEventListener("error", () => reject(new Error("本机视频上传连接中断，请刷新课堂列表后重试。")));
    xhr.addEventListener("abort", () => reject(new Error("已取消等待上传；请刷新课堂列表核对是否已经保存。")));
    xhr.send(file);
  });
}

async function uploadVideo() {
  if (!selectedVideo || uploadRequest) return;
  const file = selectedVideo;
  const version = ++selectionVersion;
  selectedController?.abort(); clearTimeout(pollTimer); setClassroomError("");
  selectedController = new AbortController();
  selectionPending = true; classroom.lectureRemoteConsent.checked = false; updateControls();
  window.MathPathTutor?.onPending(true);
  classroom.lectureUploadProgress.value = 0; classroom.lectureUploadProgress.hidden = false;
  window.MathPathClassroomNotes?.onPending(true); window.MathPathLocalVideo?.onPending(true);
  classroom.lectureUploadStatus.textContent = "正在将视频保存到本机，尚未发送给模型。";
  try {
    const lecture = await uploadRawVideo(file);
    classroom.lectureUploadStatus.textContent = "视频已保存在本机；确认视频模型设置后，再开始解析。";
    selectedVideo = null; selectedDuration = null; metadataCleanup?.(); classroom.lectureVideoFile.value = "";
    classroom.selectedVideo.textContent = "可以继续选择其他课堂视频";
    if (version === selectionVersion) { renderLecture(lecture); const url = new URL(window.location.href); url.searchParams.set("lecture", lecture.id); window.history.replaceState(null, "", url.pathname + url.search); }
    await refreshHistory();
  } catch (error) { classroom.lectureUploadStatus.textContent = error.message || "视频上传失败，所选文件已保留，可重新尝试。"; }
  finally { uploadRequest = null; if (version === selectionVersion) { selectionPending = false; window.MathPathTutor?.onPending(false); window.MathPathClassroomNotes?.onPending(false); window.MathPathLocalVideo?.onPending(false); } classroom.lectureUploadProgress.hidden = true; updateControls(); schedulePoll(selectionVersion); }
}

async function startAnalysis(event) {
  event?.preventDefault();
  if (!currentLecture || actionBusy || selectionPending || ACTIVE_STATES.has(currentLecture.status) || currentLecture.status === "completed") return;
  if (currentLecture.video_available === false) { setClassroomError("完整原视频不可用，请重新上传视频后开始解析。"); return; }
  if (!classroom.lectureRemoteConsent.checked) { setClassroomError("请先确认视频将发送给 Google 视频服务，并了解可能产生的额度用量。"); return; }
  const apiKey = classroom.lectureApiKey.value.trim();
  const model = classroom.lectureVideoModel.value.trim();
  const chunk = Number(classroom.lectureChunkSeconds.value);
  if (!apiKey || apiKey.length > 4096 || /[\r\n\x00]/.test(apiKey)) { setClassroomError("请填写有效的视频 API 密钥。"); return; }
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$/.test(model) || ![180, 300, 600].includes(chunk)) { setClassroomError("请检查视频模型名称和分段长度。"); return; }
  const version = selectionVersion; const id = currentLecture.id;
  actionBusy = true; setClassroomError(""); updateControls();
  try {
    const value = validateLecture(await requestJSON(`/lectures/${id}/analyze`, { method: "POST", body: { api_key: apiKey, model, chunk_seconds: chunk, remote_upload_confirmed: true } }));
    classroom.lectureApiKey.value = "";
    if (version === selectionVersion && currentLecture?.id === id) { renderLecture(value); schedulePoll(version); }
    await refreshHistory();
  } catch (error) { if (version === selectionVersion) setClassroomError(error.message && !error.message.includes(apiKey) ? error.message : "未能开始解析，请检查设置。"); }
  finally { actionBusy = false; updateControls(); }
}

async function cancelAnalysis() {
  if (!currentLecture || actionBusy || selectionPending || !ACTIVE_STATES.has(currentLecture.status)) return;
  const id = currentLecture.id; const version = selectionVersion;
  actionBusy = true; updateControls(); setClassroomError("");
  try {
    const value = validateLecture(await requestJSON(`/lectures/${id}/cancel`, { method: "POST" }));
    if (version === selectionVersion && currentLecture?.id === id) { renderLecture(value); schedulePoll(version); }
    await refreshHistory();
  } catch (error) { if (version === selectionVersion) setClassroomError(error.message || "无法停止任务，请刷新后检查。"); }
  finally { actionBusy = false; updateControls(); }
}

async function deleteLecture() {
  if (!currentLecture || actionBusy || selectionPending || ACTIVE_STATES.has(currentLecture.status)) return;
  const id = currentLecture.id; const version = selectionVersion;
  actionBusy = true; classroom.lectureDeleteYes.disabled = true; setClassroomError("");
  try {
    await requestJSON(`/lectures/${id}`, { method: "DELETE" });
    if (version === selectionVersion && currentLecture?.id === id) {
      ++selectionVersion; clearTimeout(pollTimer); selectedController?.abort(); currentLecture = null;
      window.MathPathTutor?.onLecture(null);
      window.MathPathClassroomNotes?.onLecture(null);
      classroom.lecturePlayer.pause(); classroom.lecturePlayer.removeAttribute("src"); classroom.lecturePlayer.load();
      renderedVideoSource = "";
      renderedClips.clear(); classroom.lectureClips.replaceChildren(); classroom.lectureWorkspace.hidden = true; classroom.classroomWelcome.hidden = false;
      classroom.lectureDeleteConfirm.hidden = true;
      const url = new URL(window.location.href); url.searchParams.delete("lecture"); window.history.replaceState(null, "", url.pathname + url.search);
    }
    await refreshHistory();
  } catch (error) { if (version === selectionVersion) setClassroomError(error.message || "删除未完成，当前课堂仍保留。"); }
  finally { actionBusy = false; classroom.lectureDeleteYes.disabled = false; updateControls(); }
}

classroom.lectureVideoFile.addEventListener("change", () => chooseVideo(classroom.lectureVideoFile.files?.[0]));
classroom.lectureUpload.addEventListener("click", uploadVideo);
classroom.lectureUploadCancel.addEventListener("click", () => uploadRequest?.abort());
classroom.lectureAnalysisForm.addEventListener("submit", startAnalysis);
classroom.lectureCancel.addEventListener("click", cancelAnalysis);
classroom.lectureApiKey.addEventListener("input", updateControls);
classroom.lectureRemoteConsent.addEventListener("change", updateControls);
classroom.lectureChunkSeconds.addEventListener("change", updateControls);
classroom.lectureRefresh.addEventListener("click", async () => { await refreshHistory(); if (currentLecture) selectLecture(currentLecture.id); });
classroom.lectureDelete.addEventListener("click", () => {
  if (!currentLecture || actionBusy || selectionPending || ACTIVE_STATES.has(currentLecture.status)) return;
  classroom.lectureDeleteDescription.textContent = `将删除本机的“${currentLecture.filename}”、原视频、${currentLecture.completed_chunks} 段解析，以及这堂课的卡点诊断和作答。导出的文件不会删除；学习地图与其他课堂保留。此操作无法撤销。`;
  classroom.lectureDeleteConfirm.hidden = false; classroom.lectureDeleteNo.focus(); classroom.lectureDeleteConfirm.scrollIntoView({ block: "nearest", behavior: "smooth" });
});
classroom.lectureDeleteNo.addEventListener("click", () => { classroom.lectureDeleteConfirm.hidden = true; classroom.lectureDelete.focus(); });
classroom.lectureDeleteYes.addEventListener("click", deleteLecture);
classroom.lectureDeleteConfirm.addEventListener("keydown", event => { if (event.key === "Escape") { classroom.lectureDeleteConfirm.hidden = true; classroom.lectureDelete.focus(); } });
classroom.lecturePlayer.addEventListener("error", () => { classroom.lecturePlayerNote.textContent = "浏览器暂时不能播放这个视频，解析记录仍保留。可用原播放器回看，或另存为 MP4（H.264 / AAC）后重新上传。"; });
classroom.videoDropzone.addEventListener("keydown", event => { if ((event.key === "Enter" || event.key === " ") && !uploadRequest) { event.preventDefault(); classroom.lectureVideoFile.click(); } });
for (const type of ["dragover", "dragenter"]) classroom.videoDropzone.addEventListener(type, event => { event.preventDefault(); if (!uploadRequest) classroom.videoDropzone.classList.add("drag-over"); });
for (const type of ["dragleave", "drop"]) classroom.videoDropzone.addEventListener(type, event => { event.preventDefault(); classroom.videoDropzone.classList.remove("drag-over"); if (type === "drop" && event.dataTransfer?.files?.length) chooseVideo(event.dataTransfer.files[0]); });
window.addEventListener("beforeunload", event => { if (uploadRequest) { event.preventDefault(); event.returnValue = ""; } });

async function initializeClassroom() {
  updateControls();
  await refreshHistory();
  const id = new URL(window.location.href).searchParams.get("lecture");
  if (id && ID_PATTERN.test(id)) await selectLecture(id);
  else if (id) setClassroomError("链接中的课堂编号无效，请从左侧课堂列表选择。");
}
initializeClassroom();
