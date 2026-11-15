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
const oldSupport = fs.readFileSync(path.join(__dirname,"frontend_v03.cjs"),"utf8");
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

async function main(){
 const e=await opened(job());e.evaluate(fs.readFileSync(path.join(project,'static/classroom_local.js'),'utf8'));
 assert.equal(e.get('local-generate').disabled,false);assert.equal(e.requests.filter(r=>r.url.includes('analyze')).length,0);
 const pending=e.get('local-generate').onclick();await flush();
 const req=e.requests.find(r=>r.url.endsWith('/analyze-local'));assert(req);assert(!JSON.stringify(req).includes('api_key'));
 const active=job({status:'queued',model:'synthetic',local_processing:{message:'正在本机识别'}});e.respond(`/lectures/${firstId}/analyze-local`,active);await pending;
 assert.equal(e.get('local-generate').disabled,true);assert.equal(e.get('local-cancel').hidden,false);assert(e.get('local-status').textContent.includes('本机识别'));
 e.evaluate(`renderLecture(${JSON.stringify(job({status:'failed',error:'合成模型额度不足'}))})`);assert.equal(e.get('local-generate').disabled,false);
 const failed=e.get('local-generate').onclick();await flush();e.respond(`/lectures/${firstId}/analyze-local`,{detail:'请连接数学模型'},409);await failed;assert(e.get('local-status').textContent.includes('请连接'));
 e.evaluate('window.MathPathLocalVideo.onPending(true)');assert.equal(e.get('local-generate').disabled,true);
 console.log('PASS local classroom primary flow: passive opening, no video key, click-only generation, active guard, progress, model error and pending selection.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
