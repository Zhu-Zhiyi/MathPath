"use strict";

// Bounded DOM checks for classroom behavior. Real video inference and browser
// media codecs are separate checks; no credentials or external models are used.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const project = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(project, "static", "classroom.html"), "utf8");
const script = fs.readFileSync(path.join(project, "static", "classroom.js"), "utf8");
const oldSupport = fs.readFileSync(path.join(__dirname, "frontend_v03.cjs"), "utf8");
const Element = new Function(oldSupport.slice(oldSupport.indexOf("class Element"), oldSupport.indexOf("function makeEnvironment")) + "\nreturn Element;")();
Element.prototype.load = function () {};
Element.prototype.pause = function () { this.paused = true; };
Element.prototype.replaceWith = function (replacement) { const parent = this.parentElement; if (!parent) return; const index = parent.children.indexOf(this); this.parentElement = null; replacement.parentElement = parent; parent.children[index] = replacement; };
const copy = value => JSON.parse(JSON.stringify(value));
const allText = element => [element.textContent, ...element.children.map(allText)].join(" ");
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const response = (value, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => copy(value) });
const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const clip = (index = 0, start = 0, end = 300) => ({ index, start_seconds: start, end_seconds: end, analysis: {
  title: "同调的定义 <img src=x onerror=alert(1)>", overview: "Compare $Z_n/B_n$ and the original lecture.",
  items: [{ start_seconds: start + 10, end_seconds: start + 45, kind: "definition", title: "同调群", evidence: "audio_visual",
    source_summary: "课堂给出 $H_n=Z_n/B_n$ <script>unsafe()</script>", explanation: "辅助说明：相差一个边界的循环视为同类。",
    formulas: ["$H_n=Z_n/B_n$"], steps: ["先找循环", "再看边界"], uncertainties: ["下标需回看板书"] }],
  learning_goals: ["理解同调类"], practice: [{ question: "两个循环何时同调？", hint: "考虑它们的差", answer: "差为一个边界。", origin: "supplement" }],
  coverage_notes: ["已处理该时间区间；并非逐帧验证"], uncertainties: [],
} });
const job = (overrides = {}) => ({ id: firstId, filename: "课堂.mp4", mime_type: "video/mp4", size_bytes: 1048576,
  created_at: "2026-11-12T12:00:00+08:00", updated_at: "2026-11-12T12:00:00+08:00", status: "uploaded",
  estimated_duration_seconds: 600, duration_seconds: null, model: null, chunk_seconds: null, completed_chunks: 0, total_chunks: 0,
  processed_seconds: 0, coverage_ratio: 0, error: null, cleanup_failed: false, clips: [], source: "model_candidate", review_required: true, ...overrides });
const summary = value => { const out = copy(value); delete out.clips; return out; };

function environment(location = "http://127.0.0.1:8000/classroom") {
  const document = { ids: new Map(), created: [], createElement(tag) { const e = new Element(tag, this); this.created.push(e); return e; },
    getElementById(id) { return this.ids.get(id) || null; }, querySelector(selector) { return this.root.querySelector(selector); } };
  document.root = new Element("html", document);
  const stack = [document.root];
  for (const token of html.match(/<[^>]+>/g)) {
    if (token.startsWith("<!") || /^<\/?html\b/.test(token)) continue;
    const closing = token.match(/^<\/([\w-]+)/);
    if (closing) { if (stack.length > 1 && stack.at(-1).tagName === closing[1].toUpperCase()) stack.pop(); continue; }
    const tag = token.match(/^<([\w-]+)/)?.[1]; if (!tag) continue;
    const element = document.createElement(tag);
    for (const match of token.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)")?/g)) element.setAttribute(match[1], match[2] ?? "");
    element.value = element.getAttribute("value") || "";
    if (element.attributes.has("checked")) element.checked = true;
    stack.at(-1).append(element);
    if (element.getAttribute("id")) document.ids.set(element.getAttribute("id"), element);
    if (tag === "body") document.body = element;
    if (!["meta", "link", "input", "br", "hr", "img"].includes(tag)) stack.push(element);
  }
  document.activeElement = document.body;
  document.getElementById("lecture-chunk-seconds").value = "300";
  const requests = []; const uploads = []; const timers = new Map(); let nextTimer = 0;
  const storeGuard = { getItem() { throw new Error("classroom must not read key storage"); }, setItem() { throw new Error("classroom must not store key"); } };
  const locationObject = { href: location };
  const windowListeners = new Map();
  const window = { location: locationObject, history: { replaceState(_a, _b, url) { locationObject.href = new URL(url, locationObject.href).href; } },
    addEventListener(type, listener) { windowListeners.set(type, listener); },
    katex: { render(tex, element, options) { assert.equal(options.trust, false); element.textContent = tex; element.className = "katex"; } } };
  class FakeURL extends URL { static createObjectURL() { return "blob:synthetic-video"; } static revokeObjectURL() {} }
  class FakeXHR {
    constructor() { this.listeners = new Map(); this.headers = {}; this.upload = new Element("upload", document); uploads.push(this); }
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader(key, value) { this.headers[key] = value; }
    addEventListener(type, listener) { this.listeners.set(type, listener); }
    send(body) { this.body = body; }
    abort() { this.listeners.get("abort")?.(); }
    resolve(value, status = 200) { this.status = status; this.responseText = JSON.stringify(value); this.listeners.get("load")?.(); }
  }
  const context = vm.createContext({ document, window, URL: FakeURL, URLSearchParams, XMLHttpRequest: FakeXHR,
    localStorage: storeGuard, sessionStorage: storeGuard, AbortController, console,
    setTimeout(callback, delay) { timers.set(++nextTimer, { callback, delay }); return nextTimer; }, clearTimeout(id) { timers.delete(id); },
    fetch(url, options) { return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject, answered: false })); } });
  vm.runInContext(script, context, { filename: "classroom.js" });
  const evaluate = code => vm.runInContext(code, context);
  const get = id => document.getElementById(id);
  function respond(url, value, status = 200) { const request = requests.find(r => !r.answered && r.url === url); assert(request, `missing request ${url}`); request.answered = true; request.resolve(response(value, status)); return request; }
  return { document, requests, uploads, timers, context, evaluate, get, respond, windowListeners };
}

async function opened(record = job()) {
  const env = environment(`http://127.0.0.1:8000/classroom?lecture=${record.id}`);
  env.respond("/lectures", [summary(record)]); await flush();
  env.respond(`/lectures/${record.id}`, record); await flush();
  return env;
}

async function main() {
  const empty = environment(); empty.respond("/lectures", []); await flush();
  assert.equal(empty.requests.length, 1, "opening classroom only reads the local list");
  assert(!empty.requests.some(r => /analyze|settings|login/.test(r.url)), "opening never invokes models or auth");
  assert.equal(empty.get("lecture-start").disabled, true);
  empty.context.syntheticFile = { name: "lecture.mp4", size: 1200000 };
  empty.evaluate("chooseVideo(syntheticFile)");
  assert.equal(empty.requests.length, 1, "choosing video has no server/model side effect");
  assert.equal(empty.get("lecture-upload").disabled, false);
  const uploading = empty.evaluate("uploadVideo()");
  assert.equal(empty.uploads.length, 1);
  assert.equal(empty.uploads[0].method, "POST");
  assert.match(empty.uploads[0].url, /^\/lectures\?filename=lecture.mp4/);
  assert.equal(empty.uploads[0].body, empty.context.syntheticFile, "send raw video, not multipart/JSON/base64");
  assert.equal(empty.uploads[0].headers["Content-Type"], "video/mp4");
  empty.uploads[0].upload.dispatch("progress", { lengthComputable: true, loaded: 600000, total: 1200000 });
  assert.equal(empty.get("lecture-upload-progress").value, 50);
  empty.uploads[0].resolve(job()); await flush();
  empty.respond("/lectures", [summary(job())]); await uploading;
  assert.equal(empty.get("lecture-player").src, `/lectures/${firstId}/video`);
  assert(!empty.requests.some(r => r.url.includes("/analyze")), "uploading video does not send it to a remote model");

  const env = await opened();
  await env.evaluate("startAnalysis()");
  assert(!env.requests.some(r => r.url.includes("/analyze")), "no consent means no model request");
  env.get("lecture-api-key").value = "synthetic-test-key-never-persist";
  env.get("lecture-remote-consent").checked = true;
  env.evaluate("updateControls()");
  assert.equal(env.get("lecture-start").disabled, false);
  const starting = env.evaluate("startAnalysis()");
  const request = env.requests.find(r => r.url.endsWith("/analyze"));
  assert.deepEqual(JSON.parse(request.options.body), { api_key: "synthetic-test-key-never-persist", model: "gemini-3.8-flash", chunk_seconds: 300, remote_upload_confirmed: true });
  env.respond(`/lectures/${firstId}/analyze`, job({ status: "queued", model: "gemini-3.8-flash", chunk_seconds: 300 })); await flush();
  env.respond("/lectures", [summary(job({ status: "queued" }))]); await starting;
  assert.equal(env.get("lecture-api-key").value, "", "clear accepted key from input; do not retain it for resumed jobs");
  assert.equal(env.get("lecture-delete").disabled, true);
  assert.equal(env.get("lecture-start").disabled, true);

  const partial = job({ status: "analyzing", duration_seconds: 600, total_chunks: 2, completed_chunks: 1, processed_seconds: 300, coverage_ratio: .5,
    model: "gemini-3.8-flash", chunk_seconds: 300, clips: [clip()] });
  env.context.polled = copy(partial); env.evaluate("renderLecture(validateLecture(polled))");
  assert.equal(env.get("lecture-coverage-value").textContent, "1 / 2 段");
  assert.match(env.get("lecture-partial-note").textContent, /未完成/);
  const firstCard = env.get("lecture-clips").children[0];
  firstCard.open = true;
  const hint = firstCard.querySelector(".lecture-exercise").querySelector("details"); hint.open = true;
  assert.equal(firstCard.querySelectorAll("img,script,iframe").length, 0, "model text cannot create HTML elements");
  assert.match(allText(firstCard), /<script>unsafe\(\)<\/script>/);
  assert.match(allText(firstCard), /课堂内容（模型识别）/);
  assert.match(allText(firstCard), /辅助解读/);
  assert.match(allText(firstCard), /辅助补充题/);
  const learnLink = firstCard.querySelector(".item-actions").querySelector("a");
  assert.equal(learnLink.href, "/?lecture_goal=%E5%90%8C%E8%B0%83%E7%BE%A4");
  firstCard.querySelector(".lecture-item").querySelector("button").click();
  assert.equal(env.get("lecture-player").currentTime, 10);
  env.evaluate("renderLecture(validateLecture(polled))");
  assert.equal(env.get("lecture-clips").children[0], firstCard, "polling unchanged content keeps existing card nodes");
  assert.equal(hint.open, true, "polling does not close opened hints");
  const cleanup = copy(partial); cleanup.status = "cleaning_remote";
  env.context.polled = cleanup; env.evaluate("renderLecture(validateLecture(polled));schedulePoll(selectionVersion)");
  assert.equal(env.get("lecture-delete").disabled, true, "remote cleanup remains an active state");
  assert([...env.timers.values()].some(t => t.delay === 1800), "continue polling during remote cleanup");

  const failed = copy(partial); failed.status = "failed"; failed.error = "下一段无法读取"; failed.cleanup_failed = true;
  env.context.polled = failed; env.evaluate("renderLecture(validateLecture(polled))");
  assert.equal(env.get("lecture-clips").children[0], firstCard, "partial failure preserves saved explanations");
  assert.equal(env.get("lecture-cleanup-warning").hidden, false);
  assert.equal(env.get("lecture-delete").disabled, false);
  assert.equal(env.get("lecture-video-model").disabled, true, "resuming partial notes keeps original model");
  assert.equal(env.get("lecture-chunk-seconds").disabled, true);
  env.get("lecture-player").dispatch("error");
  assert.match(env.get("lecture-player-note").textContent, /解析记录仍保留/);
  env.get("lecture-delete").click();
  assert.equal(env.get("lecture-delete-confirm").hidden, false);
  assert.match(env.get("lecture-delete-description").textContent, /1 段解析/);
  const countBeforeDelete = env.requests.length;
  env.get("lecture-delete-no").click();
  assert.equal(env.requests.length, countBeforeDelete, "cancel delete does not write server data");
  assert.equal(env.get("lecture-delete-confirm").hidden, true);

  const stale = await opened();
  const firstPoll = stale.evaluate("pollLecture(selectionVersion)");
  const oldRequest = [...stale.requests].reverse().find(r => !r.answered && r.url === `/lectures/${firstId}`);
  const selecting = stale.evaluate(`selectLecture('${secondId}')`);
  stale.respond(`/lectures/${secondId}`, job({ id: secondId, filename: "第二堂课.mp4" })); await selecting;
  oldRequest.answered = true; oldRequest.resolve(response(partial)); await firstPoll;
  assert.equal(stale.get("current-lecture-heading").textContent, "第二堂课.mp4", "late old response cannot replace current classroom");
  assert.equal(stale.get("lecture-clips").children.length, 0);

  const switching = await opened();
  switching.get("lecture-api-key").value = "synthetic-switching-key";
  switching.get("lecture-remote-consent").checked = true; switching.evaluate("updateControls()");
  assert.equal(switching.get("lecture-start").disabled, false);
  const selectingLater = switching.evaluate(`selectLecture('${secondId}')`);
  assert.equal(switching.get("lecture-start").disabled, true, "starting old lecture is disabled while a new selection loads");
  assert.equal(switching.get("lecture-cancel").disabled, true);
  assert.equal(switching.get("lecture-delete").disabled, true);
  assert.equal(switching.get("lecture-remote-consent").checked, false, "a new selection immediately resets sending consent");
  switching.get("lecture-remote-consent").checked = true;
  await switching.evaluate("startAnalysis();cancelAnalysis();deleteLecture()");
  assert(!switching.requests.some(r => /analyze|cancel/.test(r.url) || r.options?.method === "DELETE"), "direct action callbacks also guard a pending selection");
  switching.respond(`/lectures/${secondId}`, job({ id: secondId })); await selectingLater;
  assert.equal(switching.get("lecture-remote-consent").checked, false);
  assert.equal(switching.get("lecture-start").disabled, true);

  const recoveryJob = job({ status: "interrupted", size_bytes: 0, video_available: false, error: "上传未完成，请重新上传" });
  const recovery = await opened(recoveryJob);
  assert.match(recovery.get("lecture-player-note").textContent, /完整原视频不可用/);
  assert.equal(recovery.get("lecture-start").disabled, true);
  assert.equal(recovery.get("lecture-delete").disabled, false, "an incomplete recovered upload remains deletable");
  assert.equal(recovery.get("lecture-history").children.length, 1, "one incomplete upload does not invalidate the whole history list");
  recovery.context.uploadingRecord = job({ status: "uploading_local", size_bytes: 0, video_available: false });
  recovery.evaluate("renderLecture(validateLecture(uploadingRecord))");
  assert.equal(recovery.get("lecture-delete").disabled, true);
  assert.equal(recovery.get("lecture-cancel").hidden, true, "local uploads use their original upload cancellation control");

  const invalid = await opened();
  invalid.context.bad = copy(partial); invalid.context.bad.clips[0].analysis.items[0].end_seconds = 999;
  assert.throws(() => invalid.evaluate("validateLecture(bad)"), /时间|字段/);
  invalid.context.bad = copy(partial); invalid.context.bad.processed_seconds = 301;
  assert.throws(() => invalid.evaluate("validateLecture(bad)"), /进度/);
  invalid.context.bad = copy(partial); invalid.context.bad.review_required = false;
  assert.throws(() => invalid.evaluate("validateLecture(bad)"), /格式/);
  invalid.context.tooLarge = { name: "huge.mp4", size: 2 * 1024 ** 3 + 1 };
  invalid.evaluate("chooseVideo(tooLarge)");
  assert.equal(invalid.get("lecture-upload").disabled, true);
  assert.match(invalid.get("selected-video").textContent, /2 GiB/);
  invalid.context.pathOnly = { name: "secret.txt", size: 100 };
  invalid.evaluate("chooseVideo(pathOnly)");
  assert.equal(invalid.uploads.length, 0);

  const deleting = await opened(); deleting.get("lecture-delete").click();
  const deletion = deleting.evaluate("deleteLecture()");
  assert.equal(deleting.get("lecture-workspace").hidden, false, "keep current lecture until deletion confirmed");
  deleting.respond(`/lectures/${firstId}`, { ok: true }); await flush();
  deleting.respond("/lectures", []); await deletion;
  assert.equal(deleting.get("lecture-workspace").hidden, true);
  assert.equal(deleting.get("classroom-welcome").hidden, false);
  assert.equal(deleting.get("lecture-player").getAttribute("src"), null);
  assert(!allText(deleting.document.body).includes("synthetic-test-key-never-persist"));
  console.log("PASS classroom frontend: explicit local upload vs remote start, ephemeral key, raw upload progress, safe timestamped notes/math, source separation, partial results, cleanup polling, preserved hints, stale/pending selections, interrupted-upload recovery, malformed result rejection, confirmed delete and codec error.");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
