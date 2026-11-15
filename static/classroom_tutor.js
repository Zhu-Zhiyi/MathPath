"use strict";

const ct = Object.fromEntries(["item", "question", "context", "use-model", "diagnose", "cancel", "status", "history", "result", "refresh", "panel"]
  .map(id => [id, document.getElementById(`tutor-${id}`)]));
let ctLecture = null, ctRecords = [], ctSession = null, ctVersion = 0, ctBusy = false, ctPending = false, ctController = null;
const ctRequests = new Map();
const ctDrafts = new Map();
const ctActions = { replay_source: "回看原片段", review_prerequisite: "先补够用的先修", explain_bridge: "补上中间理由", try_check: "先做一道检查题", try_again: "补写自己的解释", independent_check: "换一道题独立检验" };
const ctKinds = { prerequisite: "可能缺少先修", proof_gap: "可能漏了推导理由", notation: "可能卡在符号", strategy: "可能卡在思路", unclear: "暂不能确定卡点" };

function ctStatus(text) { ct.status.textContent = text; }
function ctElements() {
  return (ctLecture?.clips || []).flatMap(clip => clip.analysis.items.map((item, index) => ({ id: `c${clip.index}_i${index}`, ...item })));
}
function ctControls() {
  const blocked = ctBusy || ctPending;
  ct.diagnose.disabled = blocked || !ct.item.value || !ct.question.value.trim();
  ct.item.disabled = blocked; ct.question.disabled = blocked; ct.context.disabled = blocked;
  ct["use-model"].disabled = blocked; ct.history.disabled = blocked || !ctRecords.length;
  ct.refresh.disabled = blocked || !ctLecture; ct.cancel.hidden = !ctBusy;
  for (const button of ct.result.querySelectorAll("button,textarea")) button.disabled = blocked;
}
function ctValidate(record) {
  if (!record || !ID_PATTERN.test(record.id) || typeof record.question !== "string" || record.question.length > 3000 ||
      typeof record.learner_context !== "string" || !["model_candidate", "local_reference"].includes(record.source) || record.review_required !== true ||
      !Array.isArray(record.evidence) || !record.evidence.length || record.evidence.length > 3 || !Array.isArray(record.attempts) || record.attempts.length > 12) throw new Error("诊断记录格式无效，请刷新重试。");
  const d = record.diagnosis;
  if (!d || !["candidate", "insufficient_evidence"].includes(d.status) || !Object.hasOwn(ctKinds, d.difficulty_kind) ||
      typeof d.hypothesis !== "string" || !Object.hasOwn(ctActions, d.next_action) || !Array.isArray(d.prerequisites) || d.prerequisites.length > 4 ||
      !Array.isArray(d.evidence_quotes) || d.evidence_quotes.length > 4 || !textList(d.repair_steps, 8, 1600) || !textList(d.uncertainties, 8, 1000) ||
      !d.checkpoint || ["question", "hint", "reference_answer"].some(key => typeof d.checkpoint[key] !== "string") || !textList(d.checkpoint.rubric, 5, 800)) throw new Error("卡点建议格式无效。");
  for (const evidence of record.evidence) if (!evidence || typeof evidence.id !== "string" || typeof evidence.source_summary !== "string" ||
      !safeNumber(evidence.start_seconds) || !safeNumber(evidence.end_seconds) || evidence.end_seconds <= evidence.start_seconds) throw new Error("诊断片段定位无效。");
  for (const quote of d.evidence_quotes) {
    const source = record.evidence.find(item => item.id === quote?.evidence_id);
    if (!source || typeof quote.quote !== "string" || !quote.quote.trim() || !source.source_summary.includes(quote.quote)) throw new Error("诊断引文无法定位。");
  }
  for (const p of d.prerequisites) if (!p || ["concept", "why_needed", "quick_check"].some(key => typeof p[key] !== "string")) throw new Error("先修建议格式无效。");
  for (const a of record.attempts) if (!a || !ID_PATTERN.test(a.id) || typeof a.answer !== "string" || a.review_required !== true ||
      !["model_candidate", "local_reference"].includes(a.source) || !a.feedback || !["needs_review", "partly_supported", "matches_reference"].includes(a.feedback.assessment) ||
      !["replay_source", "review_prerequisite", "try_again", "independent_check"].includes(a.feedback.next_action) ||
      ["feedback", "remaining_gap", "next_prompt"].some(key => typeof a.feedback[key] !== "string")) throw new Error("作答反馈格式无效。");
  return record;
}
function ctGoal(text) {
  const link = node("a", "secondary-link", "把这个缺口接到学习地图 →");
  link.href = `/?lecture_goal=${encodeURIComponent(text.slice(0, 4500))}`;
  return link;
}
function ctRememberDraft() {
  if (!ctSession || !ctLecture) return;
  const draft = ct.result.querySelector("textarea")?.value || "";
  if (ctDrafts.size > 100) ctDrafts.clear();
  ctDrafts.set(`${ctLecture.id}:${ctSession.id}`, draft);
}
function ctSelectSource() {
  ctRememberDraft(); ctSession = null; ct.result.replaceChildren(); ct.history.value = "";
  ctStatus("已选择新的片段。原诊断保存在历史中；请说明当前卡点再诊断。"); ctControls();
}
function ctShow(record) {
  ctRememberDraft();
  const draft = ctDrafts.get(`${ctLecture.id}:${record.id}`) || "";
  ctSession = ctValidate(record);
  const d = record.diagnosis;
  ct.result.replaceChildren();
  ct.result.append(node("p", "review-badge", record.source === "local_reference" ? "本地对照 · 尚未诊断" : "卡点假设 · 待作答检验"));
  ct.result.append(mathText(node("p", "lecture-text"), `这次的问题：${record.question}`));
  ct.result.append(node("h4", "", ctKinds[d.difficulty_kind]), mathText(node("p", "lecture-text"), d.hypothesis));
  const sources = node("div", "tutor-sources");
  for (const quote of d.evidence_quotes) {
    const source = record.evidence.find(item => item.id === quote.evidence_id);
    const entry = node("div", "source-note");
    entry.append(node("strong", "", "对应课堂解析（非已核对原话）"), seekButton(source.start_seconds, source.end_seconds), mathText(node("p"), quote.quote));
    sources.append(entry);
  }
  ct.result.append(sources);
  for (const p of d.prerequisites) {
    const box = node("section", "tutor-prerequisite");
    box.append(mathText(node("h4"), p.concept), mathText(node("p"), `为什么需要：${p.why_needed}`),
      mathText(node("p"), `先自查：${p.quick_check}`), ctGoal(`补齐${p.concept}，以理解课堂中的${record.question}`));
    ct.result.append(box);
  }
  addList(ct.result, "只补当前够用的这几步", d.repair_steps);
  addList(ct.result, "仍需核对", d.uncertainties, true);
  const next = node("p", "tutor-next", `建议下一步：${ctActions[d.next_action]}。这只是待检验的建议。`);
  ct.result.append(next);
  const check = node("section", "tutor-checkpoint");
  check.append(node("h4", "", "先用自己的话解释，再看参考"), mathText(node("p", "lecture-text"), d.checkpoint.question));
  const label = node("label", "", "你的解释"); label.setAttribute("for", "tutor-answer");
  const input = node("textarea"); input.id = "tutor-answer"; input.setAttribute("id", "tutor-answer"); input.rows = 4; input.maxLength = 6000;
  input.value = draft;
  const submit = node("button", "primary-button", "保存解释并选择下一步"); submit.type = "button";
  submit.addEventListener("click", () => ctAnswer(input.value));
  check.append(label, input, submit);
  for (const [heading, value] of [["需要一点提示", d.checkpoint.hint], ["对照参考要点（待核对）", d.checkpoint.reference_answer]]) {
    const detail = node("details", "tutor-reference"); detail.append(node("summary", "", heading), mathText(node("p"), value)); check.append(detail);
  }
  ct.result.append(check);
  for (const [index, attempt] of record.attempts.entries()) {
    const box = node("section", "tutor-attempt");
    box.append(node("h4", "", `第 ${index + 1} 次解释`), mathText(node("p"), attempt.answer), node("span", "review-badge", "候选意见 · 不自动授予掌握"), mathText(node("p"), attempt.feedback.feedback));
    if (attempt.feedback.remaining_gap) box.append(mathText(node("p"), `仍缺的理由：${attempt.feedback.remaining_gap}`));
    box.append(node("p", "tutor-next", ctActions[attempt.feedback.next_action]), mathText(node("p"), `下一问：${attempt.feedback.next_prompt}`));
    if (attempt.feedback.next_action === "replay_source") {
      const source = record.evidence.find(item => item.id === record.item_id) || record.evidence[0];
      box.append(seekButton(source.start_seconds, source.end_seconds));
    } else if (attempt.feedback.next_action === "review_prerequisite") {
      for (const p of d.prerequisites) { const link = ctGoal(`补齐${p.concept}，解决${record.question}`); link.textContent = `围绕“${p.concept}”补先修 →`; box.append(link); }
    }
    const retry = node("button", "text-button", "补写或重试这道检查题"); retry.type = "button";
    retry.addEventListener("click", () => input.focus()); box.append(retry); ct.result.append(box);
    const follow = node("button", "text-button", "把下一问带到新的诊断"); follow.type = "button";
    follow.addEventListener("click", () => { ctRememberDraft(); ctSession = null; ct.result.replaceChildren(); ct.history.value = ""; ct.question.value = attempt.feedback.next_prompt; ct.question.focus(); ctStatus("已填入下一问。确认后点击诊断，不会自动调用模型。"); ctControls(); });
    box.append(follow);
  }
  const remove = node("button", "text-button danger-text", "删除这条诊断及其作答"); remove.type = "button";
  remove.addEventListener("click", () => {
    remove.hidden = true;
    const confirm = node("button", "danger-button", "确认删除这条诊断及作答"); confirm.type = "button";
    const cancel = node("button", "text-button", "保留这条诊断"); cancel.type = "button";
    confirm.addEventListener("click", () => ctDelete(record.id));
    cancel.addEventListener("click", () => { confirm.remove(); cancel.remove(); remove.hidden = false; });
    ct.result.append(confirm, cancel);
  });
  ct.result.append(remove); ctControls();
}
function ctHistoryOptions() {
  ct.history.replaceChildren();
  const empty = node("option", "", ctRecords.length ? "选择一条已保存诊断" : "还没有诊断记录"); empty.value = ""; ct.history.append(empty);
  for (const record of [...ctRecords].reverse()) { const option = node("option", "", `${record.question.slice(0, 70)} · ${record.attempts.length} 次解释`); option.value = record.id; ct.history.append(option); }
  if (ctSession && ctRecords.some(r => r.id === ctSession.id)) ct.history.value = ctSession.id;
  ctControls();
}
async function ctRefresh() {
  if (!ctLecture || ctPending) return;
  const version = ctVersion, id = ctLecture.id;
  try {
    const values = await requestJSON(`/lectures/${id}/tutor`);
    if (version !== ctVersion) return;
    if (!Array.isArray(values) || values.length > 50) throw new Error("诊断历史格式无效。");
    ctRecords = values.map(ctValidate); ctHistoryOptions();
    if (ctSession && ctRecords.some(item => item.id === ctSession.id)) ctShow(ctRecords.find(item => item.id === ctSession.id));
    else if (!ct.question.value.trim() && ctRecords.length) {
      const last = ctRecords.at(-1); ctShow(last); ct.question.value = last.question; ct.context.value = last.learner_context; ct.item.value = last.item_id; ctControls();
    }
  } catch (error) { if (version === ctVersion) ctStatus(error.message || "诊断历史暂时无法读取。"); }
}
function ctId(key, payload) {
  const signature = JSON.stringify([ctLecture.id, key, payload]);
  if (!ctRequests.has(signature)) { if (ctRequests.size > 100) ctRequests.clear(); ctRequests.set(signature, crypto.randomUUID()); }
  return ctRequests.get(signature);
}
async function ctSubmit(path, body) {
  const version = ctVersion;
  ctController?.abort(); ctController = new AbortController(); const controller = ctController;
  ctBusy = true; ctControls(); ctStatus(body.use_model ? "正在依据所选课堂片段和你的描述整理候选建议…" : "正在整理本地参考对照…");
  try {
    const result = ctValidate(await requestJSON(path, { method: "POST", body, signal: controller.signal, timeoutMs: 120000 }));
    if (version !== ctVersion || controller.signal.aborted) return;
    const index = ctRecords.findIndex(r => r.id === result.id); if (index >= 0) ctRecords[index] = result; else ctRecords.push(result);
    ctShow(result); ctHistoryOptions(); ctStatus("已保存到这堂课。诊断与反馈仍需核对；可继续解释或回看原片段。");
  } catch (error) { if (version === ctVersion) ctStatus(`${error.message || "本次未完成。"} 可先刷新诊断记录；停止等待不保证取消已发出的模型请求。`); }
  finally { if (version === ctVersion) { ctBusy = false; ctController = null; ctControls(); } }
}
function ctDiagnose() {
  if (ctBusy || ctPending || !ctLecture || !ct.item.value || !ct.question.value.trim()) return;
  const body = { item_id: ct.item.value, question: ct.question.value.trim(), learner_context: ct.context.value.trim(), use_model: ct["use-model"].checked };
  body.request_id = ctId("diagnose", body);
  return ctSubmit(`/lectures/${ctLecture.id}/tutor`, body);
}
function ctAnswer(value) {
  if (ctBusy || ctPending || !ctLecture || !ctSession || !value.trim()) { if (!value.trim()) ctStatus("请先写出自己的解释；可以说明哪一步仍不确定。"); return; }
  const body = { answer: value.trim(), use_model: ct["use-model"].checked }; body.request_id = ctId(ctSession.id, body);
  return ctSubmit(`/lectures/${ctLecture.id}/tutor/${ctSession.id}/answer`, body);
}
async function ctDelete(id) {
  if (ctBusy || ctPending || !ctLecture) return;
  const version = ctVersion; ctBusy = true; ctControls();
  try {
    await requestJSON(`/lectures/${ctLecture.id}/tutor/${id}`, { method: "DELETE" });
    if (version !== ctVersion) return;
    ctRecords = ctRecords.filter(item => item.id !== id); ctSession = null; ct.result.replaceChildren(); ctHistoryOptions(); ctStatus("已删除此条诊断及其作答，课堂笔记保留。");
  } catch (error) { if (version === ctVersion) ctStatus(error.message); }
  finally { if (version === ctVersion) { ctBusy = false; ctControls(); } }
}
window.MathPathTutor = {
  onPending(pending) {
    ctPending = pending;
    if (pending) { ++ctVersion; ctController?.abort(); ctBusy = false; ctStatus("正在切换课堂，暂时停止当前操作。"); }
    ctControls();
    if (!pending) ctRefresh();
  },
  onLecture(lecture) {
    const changed = ctLecture?.id !== lecture?.id;
    if (changed) ctRememberDraft();
    if (!lecture && ctLecture) for (const key of ctDrafts.keys()) if (key.startsWith(ctLecture.id + ":")) ctDrafts.delete(key);
    ctLecture = lecture;
    if (changed) { ++ctVersion; ctController?.abort(); ctBusy = false; ctRecords = []; ctSession = null; ct.result.replaceChildren(); ct.question.value = ""; ct.context.value = ""; ctHistoryOptions(); }
    const selected = ct.item.value;
    const entries = ctElements();
    const key = JSON.stringify(entries.map(item => [item.id, item.title]));
    if (ct.item.getAttribute("data-options") !== key) {
      ct.item.replaceChildren();
      for (const item of entries) { const option = node("option", "", `${clock(item.start_seconds)} · ${item.title}`); option.value = item.id; ct.item.append(option); }
      ct.item.setAttribute("data-options", key);
      if (entries.some(item => item.id === selected)) ct.item.value = selected;
      else ct.item.value = entries[0]?.id || "";
    }
    if (changed) { ctStatus(entries.length ? "选一个片段，说出你没跟上的地方。" : "有课堂解析后即可选择内容。"); ctRefresh(); }
    ctControls();
  },
  selectItem(clip, index) {
    if (ctBusy || ctPending) return;
    const questions = document.getElementById("watch-questions"); if (questions) questions.open = true;
    if (ct.item.value !== `c${clip}_i${index}`) ctSelectSource();
    ct.item.value = `c${clip}_i${index}`; ct.panel.scrollIntoView({ block: "center", behavior: "smooth" }); ct.question.focus();
    ctStatus("已定位这个片段。请说明具体卡点，再点击诊断。"); ctControls();
  }
};
ct.question.addEventListener("input", ctControls);
ct.item.addEventListener("change", ctSelectSource);
ct.diagnose.addEventListener("click", ctDiagnose);
ct.refresh.addEventListener("click", ctRefresh);
ct.cancel.addEventListener("click", () => { ++ctVersion; ctController?.abort(); ctController = null; ctBusy = false; ctStatus("已停止本页等待；后台可能仍会保存结果，可稍后刷新诊断记录。没有自动重试。"); ctControls(); });
ct.history.addEventListener("change", () => { const record = ctRecords.find(item => item.id === ct.history.value); if (record) { ctShow(record); ct.question.value = record.question; ct.context.value = record.learner_context; ct.item.value = record.item_id; ctControls(); } });
if (typeof currentLecture !== "undefined" && currentLecture) window.MathPathTutor.onLecture(currentLecture);
ctControls();
