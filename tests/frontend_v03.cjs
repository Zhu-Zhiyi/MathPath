"use strict";

// Offline behavior checks. The DOM below models only the APIs used by app.js;
// real-browser layout and assistive-technology checks remain separate.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const project = path.resolve(__dirname, "..");
const script = fs.readFileSync(path.join(project, "static", "app.js"), "utf8");
const html = fs.readFileSync(path.join(project, "static", "index.html"), "utf8");

class Element {
  constructor(tag, document) {
    this.tagName = tag.toUpperCase();
    this.ownerDocument = document;
    this.attributes = new Map();
    this.children = [];
    this.parentElement = null;
    this.listeners = new Map();
    this.style = { setProperty: (key, value) => { this.style[key] = value; } };
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.inert = false;
    this.open = false;
    this.clientWidth = 900;
    this.clientHeight = 700;
    this.scrollLeft = 0;
    this.scrollTop = 0;
    this.classList = {
      add: (...items) => { this.className = [...new Set([...this.classes(), ...items])].join(" "); },
      remove: (...items) => { this.className = this.classes().filter(item => !items.includes(item)).join(" "); },
      contains: item => this.classes().includes(item),
      toggle: (item, value) => {
        const enabled = value === undefined ? !this.classes().includes(item) : value;
        this.classList[enabled ? "add" : "remove"](item);
        return enabled;
      },
    };
  }
  set innerHTML(_value) { throw new Error("HTML strings must never be inserted"); }
  classes() { return this.className.split(/\s+/).filter(Boolean); }
  get className() { return this.attributes.get("class") || ""; }
  set className(value) { this.attributes.set("class", value); }
  setAttribute(key, value) {
    this.attributes.set(key, String(value));
    if (key === "hidden" || key === "disabled" || key === "inert" || key === "open") this[key] = true;
  }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  removeAttribute(key) {
    this.attributes.delete(key);
    if (key === "hidden" || key === "disabled" || key === "inert" || key === "open") this[key] = false;
  }
  append(...elements) {
    for (const element of elements) {
      element.remove();
      element.parentElement = this;
      this.children.push(element);
    }
  }
  replaceChildren(...elements) {
    const hadFocus = this.contains(this.ownerDocument.activeElement);
    for (const child of this.children) child.parentElement = null;
    this.children = [];
    if (hadFocus) this.ownerDocument.activeElement = this.ownerDocument.body;
    this.append(...elements);
  }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    this.parentElement = null;
  }
  contains(element) {
    for (let current = element; current; current = current.parentElement) if (current === this) return true;
    return false;
  }
  matches(selector) {
    if (selector === "[hidden]") return this.hidden;
    if (selector === "[inert]") return this.inert;
    if (selector === "details:not([open])") return this.tagName === "DETAILS" && !this.open;
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    if (selector === '[tabindex]:not([tabindex="-1"])') return this.attributes.has("tabindex") && this.getAttribute("tabindex") !== "-1";
    if (/^\[[-\w]+\]$/.test(selector)) return this.attributes.has(selector.slice(1, -1));
    return this.tagName === selector.toUpperCase();
  }
  closest(selector) {
    for (let current = this; current; current = current.parentElement) if (current.matches(selector)) return current;
    return null;
  }
  querySelectorAll(selector) {
    const alternatives = selector.split(",").map(value => value.trim());
    const results = [];
    function walk(parent) {
      for (const child of parent.children) {
        if (alternatives.some(value => child.matches(value))) results.push(child);
        walk(child);
      }
    }
    walk(this);
    return results;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  dispatch(type, values = {}) {
    const event = { type, target: this, currentTarget: this, preventDefault() { this.defaultPrevented = true; }, ...values };
    for (const listener of this.listeners.get(type) || []) listener(event);
    return event;
  }
  click() { this.dispatch("click"); }
  focus() {
    if (!this.closest("[hidden]") && !this.closest("[inert]")) this.ownerDocument.activeElement = this;
  }
  get isConnected() { return this.ownerDocument.root.contains(this); }
  getClientRects() { return this.closest("[hidden]") ? [] : [{}]; }
  getContext() { return { font: "", measureText: value => ({ width: Array.from(value).length * 16 }) }; }
  scrollIntoView() {}
  scrollTo(values) { this.scrollTop = values.top || 0; this.scrollLeft = values.left || 0; }
}

function makeEnvironment({ narrow = false, saved = null } = {}) {
  const document = {
    ids: new Map(), listeners: new Map(),
    createElement(tag) { return new Element(tag, this); },
    createElementNS(namespace, tag) { const element = this.createElement(tag); element.namespaceURI = namespace; return element; },
    getElementById(id) { return this.ids.get(id) || null; },
    querySelector(selector) { return this.root.querySelector(selector); },
    addEventListener(type, listener) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(listener);
    },
    dispatch(type, values = {}) {
      const event = { type, preventDefault() { this.defaultPrevented = true; }, ...values };
      for (const listener of this.listeners.get(type) || []) listener(event);
      return event;
    },
  };
  document.root = new Element("html", document);
  const stack = [document.root];
  for (const token of html.match(/<[^>]+>/g)) {
    if (token.startsWith("<!") || token.startsWith("<html") || token.startsWith("</html")) continue;
    const closing = token.match(/^<\/([\w-]+)/);
    if (closing) {
      if (stack.length > 1 && stack[stack.length - 1].tagName === closing[1].toUpperCase()) stack.pop();
      continue;
    }
    const tag = token.match(/^<([\w-]+)/)?.[1];
    if (!tag) continue;
    const element = document.createElement(tag);
    const attributes = token.slice(tag.length + 1, -1);
    for (const match of attributes.matchAll(/([\w-]+)(?:="([^"]*)")?/g)) element.setAttribute(match[1], match[2] ?? "");
    stack[stack.length - 1].append(element);
    if (element.getAttribute("id")) document.ids.set(element.getAttribute("id"), element);
    if (tag === "body") document.body = element;
    if (!["meta", "link", "input", "br", "hr", "img"].includes(tag)) stack.push(element);
  }
  document.activeElement = document.body;
  const media = { matches: narrow, listeners: [], addEventListener(_event, listener) { this.listeners.push(listener); } };
  const storage = new Map(saved ? [["mathpath.v1.workspace", JSON.stringify(saved)]] : []);
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  const downloads = [];
  const revoked = [];
  const context = vm.createContext({
    document,
    window: { matchMedia: () => media, addEventListener() {} },
    localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    AbortController, Blob,
    URL: { createObjectURL: blob => { downloads.push(blob); return `blob:offline-${downloads.length}`; }, revokeObjectURL: url => revoked.push(url) },
    setTimeout: (callback, delay) => { timers.set(++timerId, { callback, delay }); return timerId; },
    clearTimeout: id => timers.delete(id),
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })),
    ResizeObserver: class { observe() {} },
    console,
  });
  vm.runInContext(script, context, { filename: "app.js" });
  const evaluate = code => vm.runInContext(code, context);
  return {
    context, document, media, storage, requests, timers, downloads, revoked, evaluate,
    get: id => document.getElementById(id),
    snapshot: () => JSON.parse(evaluate("JSON.stringify({ graph, mastery: Object.fromEntries(mastery), draft: ui.input.value, known: [...knownIds], viewMode, activeLessonId })")),
    setNarrow(value) { media.matches = value; for (const listener of media.listeners) listener(); },
  };
}

const fixture = {
  target_id: "goal",
  nodes: [
    { id: "goal", label: "Goal theorem", prerequisite_sets: [["chain"], ["alternative"]] },
    { id: "chain", label: "Chain complex", prerequisite_sets: [["base", "vector"]] },
    { id: "base", label: "Base definition", prerequisite_sets: [] },
    { id: "vector", label: "Vector space", prerequisite_sets: [] },
    { id: "alternative", label: "Alternative method", prerequisite_sets: [["base"]] },
  ],
};
const flags = { definition: true, intuition: true, application: true };
const envelope = (overrides = {}) => ({ format: "mathpath-workspace", version: 1, graph: fixture, mastery: { base: flags }, draft: "Restored goal", source: "generated", ...overrides });
const file = payload => ({ size: Buffer.byteLength(typeof payload === "string" ? payload : JSON.stringify(payload)), text: async () => typeof payload === "string" ? payload : JSON.stringify(payload) });
const flush = async () => { for (let index = 0; index < 8; index++) await Promise.resolve(); };
const response = value => ({ ok: true, json: async () => value });
const lessonFixture = (nodeId = "vector", overrides = {}) => ({
  node_id: nodeId, source: "curated_example", title: "Vector space", definition: "A definition.",
  intuition: "An intuition.", example: "A concrete example.", proof_idea: "A proof idea.",
  exercise: { question: "Which answer?", options: ["Correct", "Second", "Third", "Fourth"], correct_index: 0, explanation: "The reason.", dimension: "application" },
  followup_exercises: [
    { level: "basic", question: "Try an example first.", hint: "Start from the definition.", answer: "Basic reference answer." },
    { level: "challenge", question: "Explain why the pattern holds.", hint: "Compare the two descriptions.", answer: "Challenge reference answer." },
  ],
  illustration: {
    title: "Vector diagram", caption: "A schematic example, with readable labels.", alt: "Two vectors and their span.",
    elements: [
      { type: "line", x1: 100, y1: 280, x2: 280, y2: 100, tone: "blue", arrow: true, dashed: true },
      { type: "circle", cx: 400, cy: 200, r: 50, tone: "green", fill: false },
      { type: "polygon", points: [[100, 280], [280, 100], [340, 280]], tone: "muted", fill: true },
      { type: "text", x: 160, y: 70, text: "<img src=x onerror=alert(1)>", tone: "ink", anchor: "middle" },
    ],
  },
  ...overrides,
});

function checkLessonValidation(environment) {
  const legacy = lessonFixture();
  delete legacy.followup_exercises;
  delete legacy.illustration;
  environment.context.lessonCandidate = legacy;
  const normalized = environment.evaluate('validateLesson(lessonCandidate, "vector")');
  assert.equal(normalized.illustration, null, "older lesson cards may omit an illustration");
  assert.equal(normalized.followup_exercises.length, 0, "older lesson cards may omit follow-up exercises");
  const invalidChanges = [
    value => { value.extra = "not part of a lesson"; },
    value => { value.exercise.href = "javascript:alert(1)"; },
    value => { value.followup_exercises = null; },
    value => { value.followup_exercises.push(value.followup_exercises[0], value.followup_exercises[0]); },
    value => { value.followup_exercises[0].level = "expert"; },
    value => { value.followup_exercises[0].question = "q".repeat(601); },
    value => { value.followup_exercises[0].hint = " "; },
    value => { value.followup_exercises[0].answer = "a".repeat(1401); },
    value => { value.followup_exercises[0].html = "<script>alert(1)</script>"; },
    value => { value.illustration = "<svg onload=alert(1)>"; },
    value => { value.illustration.viewBox = "0 0 640 360"; },
    value => { value.illustration.alt = " "; },
    value => { value.illustration.elements = []; },
    value => { value.illustration.elements = Array.from({ length: 61 }, () => value.illustration.elements[0]); },
    value => { value.illustration.elements[0].type = "script"; },
    value => { value.illustration.elements[0].type = "constructor"; },
    value => { value.illustration.elements[0].type = { toString: "invalid" }; },
    value => { value.illustration.elements[0].onload = "alert(1)"; },
    value => { value.illustration.elements[0].href = "javascript:alert(1)"; },
    value => { value.illustration.elements[0].tone = "url(https://example.test/image)"; },
    value => { value.illustration.elements[0].x1 = -1; },
    value => { value.illustration.elements[0].x2 = 641; },
    value => { value.illustration.elements[0].y1 = 361; },
    value => { value.illustration.elements[0].y2 = Infinity; },
    value => { value.illustration.elements[0].x1 = NaN; },
    value => { value.illustration.elements[0].x1 = "100"; },
    value => { value.illustration.elements[0].arrow = 1; },
    value => { delete value.illustration.elements[0].dashed; },
    value => { value.illustration.elements[1].r = 0; },
    value => { value.illustration.elements[1].r = 151; },
    value => { value.illustration.elements[1].r = NaN; },
    value => { value.illustration.elements[1].fill = "false"; },
    value => { value.illustration.elements[2].points = [[0, 0], [20, 20]]; },
    value => { value.illustration.elements[2].points = Array.from({ length: 13 }, () => [0, 0]); },
    value => { value.illustration.elements[2].points[0] = [0, 0, 0]; },
    value => { value.illustration.elements[2].points[0] = [Infinity, 0]; },
    value => { value.illustration.elements[3].text = "x".repeat(51); },
    value => { value.illustration.elements[3].anchor = "auto"; },
  ];
  for (const change of invalidChanges) {
    const invalid = lessonFixture();
    change(invalid);
    environment.context.lessonCandidate = invalid;
    assert.throws(() => environment.evaluate('validateLesson(lessonCandidate, "vector")'), /invalid-lesson/, "malformed lesson enrichment is rejected before rendering");
  }
  environment.context.lessonCandidate = lessonFixture();
  assert.doesNotThrow(() => environment.evaluate('validateLesson(lessonCandidate, "vector")'), "safe primitives and literal markup-looking text are valid data");
}

function checkEnrichedLessonRendering(environment) {
  assert(!environment.get("lesson-illustration-section").hidden);
  assert(!environment.get("followup-section").hidden);
  const svg = environment.get("lesson-illustration-viewport").querySelector("svg");
  assert.equal(svg.namespaceURI, "http://www.w3.org/2000/svg");
  assert.equal(svg.getAttribute("viewBox"), "0 0 640 360");
  assert.equal(svg.getAttribute("role"), "img");
  assert.equal(svg.querySelector("title").textContent, "Vector diagram");
  assert.equal(svg.querySelector("desc").textContent, "Two vectors and their span.");
  assert.equal(environment.get("lesson-illustration-caption").textContent, "A schematic example, with readable labels.");
  assert.equal(svg.querySelector("text").textContent, "<img src=x onerror=alert(1)>", "markup-looking text remains literal SVG text");
  assert.equal(svg.querySelector("text").getAttribute("font-size"), "24");
  assert.equal(svg.querySelectorAll("img, script, image, foreignObject").length, 0, "no executable or external image nodes are created");
  const allowedAttributes = {
    SVG: ["viewBox", "width", "height", "class", "role", "aria-labelledby", "aria-describedby", "preserveAspectRatio"],
    TITLE: ["id"], DESC: ["id"],
    LINE: ["x1", "y1", "x2", "y2", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray"],
    CIRCLE: ["cx", "cy", "r", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill", "fill-opacity"],
    POLYGON: ["points", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill", "fill-opacity"],
    TEXT: ["x", "y", "fill", "text-anchor", "font-size"],
  };
  for (const element of [svg, ...svg.querySelectorAll("title, desc, line, circle, polygon, text")]) {
    assert.equal(element.namespaceURI, "http://www.w3.org/2000/svg");
    for (const [key, value] of element.attributes) {
      assert(allowedAttributes[element.tagName].includes(key), `only fixed SVG attributes are rendered: ${key}`);
      assert(!/javascript:|https?:|url\(/i.test(value), "SVG attributes contain no remote or executable URL");
    }
  }
  const items = environment.get("followup-list").querySelectorAll("li");
  assert.equal(items.length, 2);
  assert.equal(items[0].querySelector("h4").textContent, "第 1 题 · 基础");
  assert.equal(items[1].querySelector("h4").textContent, "第 2 题 · 进阶");
  assert.equal(items[0].querySelector("p").textContent, "Try an example first.");
  const supports = environment.get("followup-list").querySelectorAll("details");
  assert.equal(supports.length, 4);
  assert(supports.every(details => !details.open), "hints and reference answers start collapsed separately");
  const summaryLabels = supports.map(details => details.querySelector("summary").textContent);
  assert.deepEqual(summaryLabels, ["提示", "参考答案", "提示", "参考答案"]);
  const focusable = environment.evaluate("lessonFocusableElements()");
  assert(supports.every(details => focusable.includes(details.querySelector("summary"))), "new collapsed summaries participate in the mobile focus trap");
  const masteryBefore = environment.snapshot().mastery;
  supports[1].open = true;
  supports[1].dispatch("toggle");
  assert.equal(environment.get("lesson-illustration-zoom").textContent, "放大查看");
  environment.get("lesson-illustration-zoom").click();
  assert(environment.get("lesson-illustration-viewport").classList.contains("enlarged"));
  assert.equal(environment.get("lesson-illustration-zoom").getAttribute("aria-pressed"), "true");
  assert.equal(environment.get("lesson-illustration-zoom").textContent, "适配卡片");
  environment.get("lesson-illustration-viewport").scrollLeft = 200;
  environment.get("lesson-illustration-zoom").click();
  assert.equal(environment.get("lesson-illustration-zoom").getAttribute("aria-pressed"), "false");
  assert.equal(environment.get("lesson-illustration-zoom").textContent, "放大查看");
  assert.equal(environment.get("lesson-illustration-viewport").scrollLeft, 0, "fitting the card restores the start of the full diagram");
  const correctChoice = environment.get("exercise-options").querySelectorAll("input")[0];
  correctChoice.checked = true;
  correctChoice.dispatch("change");
  environment.get("exercise-form").dispatch("submit");
  assert(!environment.get("exercise-mark").hidden, "the original micro exercise still allows a separate manual mastery action");
  assert.deepEqual(environment.snapshot().mastery, masteryBefore, "viewing a reference answer, zooming or answering correctly never marks mastery");
  environment.get("mastery-intuition").checked = true;
  environment.get("mastery-intuition").dispatch("change");
  assert(supports[1].open, "manual mastery changes preserve an open reference answer");
  assert(!environment.get("exercise-feedback").hidden, "manual mastery changes preserve micro exercise feedback");
  assert(correctChoice.checked, "manual mastery changes preserve the chosen micro exercise answer");
}
function settlePlan(environment, value = {}) {
  const request = [...environment.requests].reverse().find(item => item.url === "/plan");
  const known = environment.snapshot().known;
  request.resolve(response({ target_id: "goal", completed: false, known_ids: known, ready_ids: ["vector", "alternative"], blocked_ids: ["chain", "goal"], recommended_ids: ["vector"], required_ids: ["vector", "chain", "goal"], selected_ids: ["base", "vector", "chain", "goal"], focus_id: "vector", ...value }));
}

const lessonRequests = environment => environment.requests.filter(request => request.url === "/lesson");
const latestLesson = (environment, id) => [...lessonRequests(environment)].reverse()
  .find(request => JSON.parse(request.options.body).node_id === id);
const prerequisiteRow = (environment, id) => environment.get("prerequisite-groups")
  .querySelectorAll(".prerequisite-item").find(row => row.getAttribute("data-prerequisite-id") === id);
const treeText = element => [element.textContent, ...element.children.map(treeText)].join(" ");

function checkNumbering(environment) {
  const numbers = { base: 1, vector: 2, chain: 3, alternative: 4, goal: 5 };
  assert.deepEqual(JSON.parse(environment.evaluate("JSON.stringify(layout.orderedIds)")), Object.keys(numbers));
  for (const [id, number] of Object.entries(numbers)) {
    const expected = `知识点 ${number} · ${fixture.nodes.find(node => node.id === id).label}`;
    const graphNode = environment.get("graph-canvas").querySelectorAll(".graph-node")
      .find(node => node.getAttribute("data-node-id") === id);
    assert.equal(graphNode.getAttribute("data-node-number"), String(number));
    assert.equal(graphNode.querySelector("title").textContent, expected);
    assert.match(treeText(graphNode.querySelector(".node-label")), new RegExp(`知识点 ${number}`));
    const listNode = environment.get("node-list").querySelectorAll("button")
      .find(node => node.getAttribute("data-node-id") === id);
    assert.equal(listNode.querySelector(".node-browser-label").textContent, expected);
  }
  for (const listId of ["ready-list", "path-list", "all-ready-list"]) {
    for (const button of environment.get(listId).querySelectorAll("button")) {
      const id = button.getAttribute("data-node-id");
      assert.equal(button.textContent, `知识点 ${numbers[id]} · ${fixture.nodes.find(node => node.id === id).label}`);
    }
  }
  assert.deepEqual(environment.get("path-list").querySelectorAll("button").map(button => button.textContent.split(" · ")[0]),
    ["知识点 2", "知识点 3", "知识点 5"], "route step order never renumbers knowledge points");
}

async function prerequisiteEnvironment(graphValue = fixture) {
  const environment = makeEnvironment({ narrow: true });
  await flush();
  environment.context.nextFile = file(envelope({ graph: graphValue }));
  await environment.evaluate("importWorkspace(nextFile)");
  await flush();
  return environment;
}

async function checkPrerequisites() {
  const environment = await prerequisiteEnvironment();
  const originalMastery = environment.snapshot().mastery;
  assert.equal(lessonRequests(environment).length, 0);
  environment.evaluate('openLesson("goal")');
  assert.equal(lessonRequests(environment).length, 1, "opening a card requests only its main lesson");
  assert.match(environment.get("lesson-title").textContent, /^知识点 5 ·/);
  assert.match(environment.get("prerequisite-rule").textContent, /任选一组（OR）.*都需掌握（AND）/);
  assert.deepEqual(environment.get("prerequisite-groups").querySelectorAll(".prerequisite-group")
    .map(group => group.querySelectorAll(".prerequisite-item").map(row => row.getAttribute("data-prerequisite-id"))),
    [["chain"], ["alternative"]]);
  assert.equal(prerequisiteRow(environment, "chain").querySelector(".prerequisite-label").textContent, "知识点 3 · Chain complex");
  assert.equal(prerequisiteRow(environment, "alternative").querySelector(".prerequisite-label").textContent, "知识点 4 · Alternative method");
  assert(environment.get("prerequisite-groups").querySelectorAll(".prerequisite-preview").every(preview => preview.hidden));
  latestLesson(environment, "goal").resolve({ ok: false, status: 503, json: async () => ({ detail: "Main lesson unavailable" }) });
  await flush();
  const mainError = environment.get("lesson-error-text").textContent;
  assert(environment.get("lesson-content").hidden);
  assert(!environment.get("lesson-prerequisites").hidden, "prerequisites remain available when the main card fails");
  const chain = prerequisiteRow(environment, "chain");
  chain.querySelector(".prerequisite-toggle").click();
  assert.equal(lessonRequests(environment).length, 2, "only an explicit expansion requests a prerequisite");
  assert.equal(environment.snapshot().activeLessonId, "goal", "inline expansion keeps the current card open");
  const chainLesson = lessonFixture("chain", { title: "Chain complex", definition: "<img src=x onerror=alert(1)>" });
  latestLesson(environment, "chain").resolve(response(chainLesson));
  await flush();
  const chainContent = chain.querySelector(".prerequisite-preview-content");
  assert.deepEqual(chainContent.querySelectorAll("p").map(paragraph => paragraph.textContent),
    [chainLesson.definition, chainLesson.intuition, chainLesson.example]);
  assert.equal(chainContent.querySelectorAll("svg, img, iframe, details, button, input").length, 0,
    "inline summaries contain only safe text, without recursive prerequisites, SVG or exercises");
  assert.equal(environment.get("lesson-error-text").textContent, mainError, "prerequisite success never clears a main-card error");
  chain.querySelector(".prerequisite-toggle").click();
  chain.querySelector(".prerequisite-toggle").click();
  assert.equal(lessonRequests(environment).length, 2, "collapse and reopen reuse the lesson cache");
  chain.querySelector(".prerequisite-open").click();
  assert.equal(environment.snapshot().activeLessonId, "chain");
  assert.equal(lessonRequests(environment).length, 2, "a complete card reuses an inline lesson cached after validation");
  assert.match(environment.get("lesson-title").textContent, /^知识点 3 ·/);
  assert.match(environment.get("prerequisite-rule").textContent, /全部掌握（AND）/);
  assert.deepEqual(environment.get("prerequisite-groups").querySelectorAll(".prerequisite-item")
    .map(row => row.getAttribute("data-prerequisite-id")), ["base", "vector"]);
  const base = prerequisiteRow(environment, "base");
  assert.equal(base.querySelector(".prerequisite-label").textContent, "知识点 1 · Base definition");
  assert.match(base.querySelector(".prerequisite-state").textContent, /自行标记全部掌握（3\/3）/);
  assert.match(prerequisiteRow(environment, "vector").querySelector(".prerequisite-state").textContent, /尚未标记掌握（0\/3）/);
  base.querySelector(".prerequisite-toggle").click();
  latestLesson(environment, "base").reject(new Error("offline"));
  await flush();
  assert(!base.querySelector(".prerequisite-error").hidden);
  assert(!base.querySelector(".prerequisite-retry").hidden);
  assert(environment.evaluate("lessonFocusableElements()").includes(base.querySelector(".prerequisite-retry")),
    "a visible inline retry joins the current modal focus sequence");
  assert(!environment.get("lesson-content").hidden && environment.get("lesson-error").hidden,
    "a prerequisite network error stays local and leaves the main card visible");
  const countAfterFailure = lessonRequests(environment).length;
  base.querySelector(".prerequisite-toggle").click();
  base.querySelector(".prerequisite-toggle").click();
  assert.equal(lessonRequests(environment).length, countAfterFailure, "a failed summary waits for an explicit retry");
  base.querySelector(".prerequisite-retry").click();
  latestLesson(environment, "base").resolve(response({ ...lessonFixture("base"), definition: null }));
  await flush();
  assert.match(base.querySelector(".prerequisite-error").textContent, /格式没有通过检查/);
  assert(!environment.evaluate('lessonCache.has("base")'), "invalid summaries never enter the shared cache");
  base.querySelector(".prerequisite-retry").click();
  latestLesson(environment, "base").resolve(response(lessonFixture("base")));
  await flush();
  assert(base.querySelector(".prerequisite-error").hidden);
  assert(!base.querySelector(".prerequisite-preview-content").hidden);
  const focusable = environment.evaluate("lessonFocusableElements()");
  assert(focusable.includes(base.querySelector(".prerequisite-toggle")));
  assert(focusable.includes(base.querySelector(".prerequisite-open")));
  assert.equal(focusable[focusable.length - 1].tagName, "SUMMARY", "the last collapsed follow-up answer is included dynamically");
  focusable[focusable.length - 1].focus();
  assert(environment.document.dispatch("keydown", { key: "Tab", shiftKey: false }).defaultPrevented);
  assert.equal(environment.document.activeElement, focusable[0]);
  assert(environment.document.dispatch("keydown", { key: "Tab", shiftKey: true }).defaultPrevented);
  assert.equal(environment.document.activeElement, focusable[focusable.length - 1]);
  assert.deepEqual(environment.snapshot().mastery, originalMastery, "expansion, caching, failures and navigation never alter mastery");
  environment.evaluate('updateMastery("vector", { definition: true })');
  assert.match(prerequisiteRow(environment, "vector").querySelector(".prerequisite-state").textContent, /知道定义（1\/3）/);
  assert(!base.querySelector(".prerequisite-preview-content").hidden, "self-reported status refresh preserves open summaries");
  environment.evaluate('updateMastery("vector", { definition: true, intuition: true, application: true })');
  assert.match(environment.get("prerequisite-groups").querySelector(".prerequisite-group-status").textContent, /已全部自行标记掌握/);

  const repeatedGraph = { ...fixture, nodes: fixture.nodes.map(node => node.id === "goal"
    ? { ...node, prerequisite_sets: [["chain", "base"], ["alternative", "base"]] } : node) };
  const repeated = await prerequisiteEnvironment(repeatedGraph);
  repeated.evaluate('openLesson("goal")');
  const repeatedBase = repeated.get("prerequisite-groups").querySelectorAll(".prerequisite-item")
    .filter(row => row.getAttribute("data-prerequisite-id") === "base");
  repeatedBase.forEach(row => row.querySelector(".prerequisite-toggle").click());
  assert.equal(lessonRequests(repeated).length, 2, "two OR groups share one pending request for the same prerequisite");
  latestLesson(repeated, "base").resolve(response(lessonFixture("base")));
  await flush();
  assert(repeatedBase.every(row => !row.querySelector(".prerequisite-preview-content").hidden));

  for (const transition of ["node", "close", "graph"]) {
    for (const result of ["success", "failure"]) {
      const stale = await prerequisiteEnvironment();
      stale.evaluate('openLesson("chain")');
      latestLesson(stale, "chain").resolve(response(lessonFixture("chain")));
      await flush();
      const oldBase = prerequisiteRow(stale, "base");
      oldBase.querySelector(".prerequisite-toggle").click();
      const late = latestLesson(stale, "base");
      oldBase.querySelector(".prerequisite-toggle").click();
      oldBase.querySelector(".prerequisite-toggle").click();
      assert.equal(lessonRequests(stale).length, 2, "reopening a pending summary never duplicates its request");
      if (transition === "node") stale.evaluate('openLesson("goal")');
      else if (transition === "close") stale.evaluate("closeLesson()");
      else {
        stale.context.nextFile = file(envelope({ draft: "Replacement graph" }));
        await stale.evaluate("importWorkspace(nextFile)");
        stale.evaluate('openLesson("chain")');
        prerequisiteRow(stale, "base").querySelector(".prerequisite-toggle").click();
      }
      assert(late.options.signal.aborted, `${transition} aborts the old summary request`);
      const surface = () => ({
        title: stale.get("lesson-title").textContent, status: stale.get("lesson-status").textContent,
        error: stale.get("lesson-error-text").textContent, errorHidden: stale.get("lesson-error").hidden,
        prerequisites: treeText(stale.get("prerequisite-groups")), active: stale.snapshot().activeLessonId,
        detachedStatus: oldBase.querySelector(".prerequisite-preview-status").textContent,
        detachedError: oldBase.querySelector(".prerequisite-error").textContent,
      });
      const before = surface();
      late.resolve(result === "success" ? response(lessonFixture("base"))
        : { ok: false, status: 503, json: async () => ({ detail: "Stale failure" }) });
      await flush();
      assert.deepEqual(surface(), before, `late ${result} after ${transition} cannot write current or detached DOM`);
      assert(!stale.evaluate('lessonCache.has("base")'), `late ${result} after ${transition} never seeds a replacement cache`);
    }
  }
}

const settingsFixture = (overrides = {}) => ({
  provider: "chatgpt", base_url: "https://api.openai.com/v1", model: "",
  api_format: "chat_completions", output_mode: "json_object", has_api_key: false,
  revision: "default", ...overrides,
});
const settingsRequests = (environment, method = "GET") => environment.requests
  .filter(request => request.url === "/settings/model" && (request.options.method || "GET") === method);
const latestSettings = (environment, method = "GET") => settingsRequests(environment, method).at(-1);
const testRequests = environment => environment.requests.filter(request => request.url === "/settings/model/test");
const loginRequests = environment => environment.requests.filter(request => request.url === "/settings/chatgpt/login");
const statusRequests = environment => environment.requests.filter(request => request.url === "/settings/chatgpt/status");
const latestStatus = environment => statusRequests(environment).at(-1);
const chatgptFixture = (status = "idle", attempt = 0, message = {
  idle: "本次运行尚未发起登录。",
  pending: "正在连接 ChatGPT，请在打开的浏览器中完成登录。",
  connected: "ChatGPT 已连接，可以返回生成学习内容。",
  error: "连接 ChatGPT 未完成，请稍后重试。",
}[status]) => ({ status, attempt, message });
const fireLoginPoll = environment => {
  const entry = [...environment.timers].find(([, timer]) => timer.delay === 2000);
  assert(entry, "a pending login schedules a two-second status read");
  environment.timers.delete(entry[0]);
  entry[1].callback();
};

async function checkChatgptLogin() {
  const saved = { version: 2, graph: fixture, mastery: { base: flags }, draft: "Offline goal", source: "generated" };
  const environment = makeEnvironment({ saved });
  await flush();
  settlePlan(environment);
  await flush();
  assert.equal(loginRequests(environment).length, 0);
  assert.equal(statusRequests(environment).length, 0, "offline restoration never checks or opens authorization");
  assert(html.includes("打开设置后读取本次登录进度。"), "initial login copy describes this runtime attempt only");
  environment.get("model-settings-button").click();
  latestSettings(environment).resolve(response(settingsFixture({ provider: "api", model: "saved-api", has_api_key: true, revision: "api" })));
  await flush();
  assert(environment.get("chatgpt-login-button").closest("[hidden]"), "API selection hides the login entry");
  assert(!environment.evaluate("modelSettingsFocusableElements()").includes(environment.get("chatgpt-login-button")));
  assert.equal(statusRequests(environment).length, 0, "opening saved API settings does not query ChatGPT");
  const before = environment.snapshot();
  const modelCalls = () => environment.requests.filter(request => ["/analyze", "/lesson", "/settings/model/test"].includes(request.url)).length;
  const modelCallsBefore = modelCalls();
  environment.get("model-api-key").value = "synthetic-unsaved-key";
  environment.get("model-provider").value = "chatgpt";
  environment.get("model-provider").dispatch("change");
  assert.equal(environment.get("model-api-key").value, "");
  assert(!environment.get("chatgpt-login-button").closest("[hidden]"));
  assert.equal(environment.get("chatgpt-login-button").getAttribute("type"), "button");
  assert.equal(environment.get("chatgpt-login-status").getAttribute("role"), "status");
  assert.equal(environment.get("chatgpt-login-status").getAttribute("aria-live"), "polite");
  assert.equal(loginRequests(environment).length, 0, "provider selection only reads local state, never starts login");
  assert.equal(environment.get("chatgpt-login-status").textContent, "正在读取本次登录进度，不会调用模型…");
  assert.equal(latestStatus(environment).options.cache, "no-store");
  latestStatus(environment).resolve(response({ ...chatgptFixture(), account: "discard-this-account-field" }));
  await flush();
  assert.equal(environment.get("chatgpt-login-status").textContent, "本次运行尚未发起新的登录。点击上方按钮登录或重新连接。", "idle makes no claim about previously cached authorization");
  assert.doesNotMatch(environment.get("chatgpt-login-status").textContent, /尚未连接|未登录/);
  assert(!environment.get("chatgpt-login-button").disabled);
  assert(environment.evaluate("modelSettingsFocusableElements()").includes(environment.get("chatgpt-login-button")), "the visible login entry participates in the focus trap");
  assert(!environment.evaluate("JSON.stringify(chatgptConnection)").includes("discard-this-account"));
  assert.equal(settingsRequests(environment, "POST").length, 0);

  environment.get("model-api-key").value = "synthetic-key-does-not-affect-login";
  environment.get("chatgpt-login-button").click();
  assert.equal(loginRequests(environment).length, 1);
  assert.equal(loginRequests(environment)[0].options.method, "POST");
  assert.equal(loginRequests(environment)[0].options.body, undefined, "login sends neither unsaved settings nor secrets");
  assert(environment.get("chatgpt-login-button").disabled);
  environment.get("chatgpt-login-button").click();
  assert.equal(loginRequests(environment).length, 1, "double clicks cannot open two authorizations");
  loginRequests(environment)[0].resolve(response(chatgptFixture("pending", 1)));
  await flush();
  assert.match(environment.get("chatgpt-login-status").textContent, /关闭设置不会取消后台登录/);
  environment.get("chatgpt-login-button").click();
  assert.equal(loginRequests(environment).length, 1, "server-pending state prevents another login click");
  fireLoginPoll(environment);
  latestStatus(environment).resolve(response(chatgptFixture("connected", 1)));
  await flush();
  assert.match(environment.get("chatgpt-login-status").textContent, /ChatGPT 已连接，可以返回生成学习内容。.*如需使用 ChatGPT.*保存并使用/);
  assert.equal(environment.evaluate("modelSettings.provider"), "api", "login success never switches the saved provider");
  assert.equal(settingsRequests(environment, "POST").length, 0, "login success never autosaves the provider choice");
  assert.equal(modelCalls(), modelCallsBefore, "login success never tests or generates content");
  assert.deepEqual(environment.snapshot(), before, "login retains graph, progress and lesson state");
  assert(!environment.get("chatgpt-login-button").disabled);
  environment.evaluate("readChatgptStatus()");
  const noModelPermission = "登录已完成，当前未启用模型调用权限。";
  latestStatus(environment).resolve(response(chatgptFixture("connected", 1, noModelPermission)));
  await flush();
  assert(environment.get("chatgpt-login-status").textContent.startsWith(noModelPermission), "saved API settings retain the backend's permission result");
  assert.doesNotMatch(environment.get("chatgpt-login-status").textContent, /可以返回生成|可返回生成/);
  assert.equal(environment.evaluate("modelSettings.provider"), "api");
  assert.equal(settingsRequests(environment, "POST").length, 0);

  environment.get("model-provider").value = "api";
  environment.get("model-provider").dispatch("change");
  environment.get("chatgpt-login-button").click();
  assert.equal(loginRequests(environment).length, 1, "a hidden API login entry cannot submit");
  environment.get("model-provider").value = "chatgpt";
  environment.get("model-provider").dispatch("change");
  latestStatus(environment).resolve({ ok: false, json: async () => ({ detail: "never-echo-private-diagnostic" }) });
  await flush();
  assert.equal(environment.get("chatgpt-login-status").textContent, "暂时无法读取 ChatGPT 登录状态，请关闭设置后重新打开。");
  assert(environment.get("chatgpt-login-status").classList.contains("error"));
  environment.get("chatgpt-login-button").click();
  loginRequests(environment).at(-1).reject(new Error("never-echo-private-diagnostic"));
  await flush();
  assert.equal(environment.get("chatgpt-login-status").textContent, "未能开始 ChatGPT 登录，请稍后重试。");
  environment.get("model-settings-close").click();
  assert.equal(environment.get("model-api-key").value, "", "closing the login dialog preserves secret cleanup");

  const reconnect = makeEnvironment({ saved });
  await flush();
  reconnect.get("model-settings-button").click();
  latestSettings(reconnect).resolve(response(settingsFixture()));
  await flush();
  assert.equal(statusRequests(reconnect).length, 1, "opening ChatGPT settings reads its local status");
  assert.equal(loginRequests(reconnect).length, 0, "opening settings never starts authorization");
  latestStatus(reconnect).resolve(response(chatgptFixture()));
  await flush();
  reconnect.get("chatgpt-login-button").click();
  loginRequests(reconnect)[0].resolve(response(chatgptFixture("pending", 1)));
  await flush();
  fireLoginPoll(reconnect);
  const staleStatus = latestStatus(reconnect);
  reconnect.get("model-settings-close").click();
  assert(staleStatus.options.signal.aborted, "closing aborts the local status request");
  assert(![...reconnect.timers.values()].some(timer => timer.delay === 2000), "closing stops status polling");
  reconnect.get("model-settings-button").click();
  const reopenedStatus = latestStatus(reconnect);
  assert.notEqual(reopenedStatus, staleStatus, "reopening reads status again without starting login");
  reopenedStatus.resolve(response(chatgptFixture("pending", 1)));
  await flush();
  const reopenedText = reconnect.get("chatgpt-login-status").textContent;
  staleStatus.resolve(response(chatgptFixture("connected", 1)));
  await flush();
  assert.equal(reconnect.get("chatgpt-login-status").textContent, reopenedText, "a stale closed-dialog read cannot replace the reopened state");
  assert.equal(loginRequests(reconnect).length, 1);
  fireLoginPoll(reconnect);
  latestStatus(reconnect).resolve(response(chatgptFixture("connected", 1)));
  await flush();
  assert.equal(reconnect.get("chatgpt-login-status").textContent, "ChatGPT 已连接，可以返回生成学习内容。", "authorized success displays the backend's safe result");
  assert(![...reconnect.timers.values()].some(timer => timer.delay === 2000), "connected state stops polling");
  reconnect.evaluate("readChatgptStatus()");
  latestStatus(reconnect).resolve(response(chatgptFixture("connected", 1, noModelPermission)));
  await flush();
  assert.equal(reconnect.get("chatgpt-login-status").textContent, noModelPermission, "ChatGPT settings cannot replace an ungranted-permission result with a generation promise");
  assert.doesNotMatch(reconnect.get("chatgpt-login-status").textContent, /可以返回生成|可返回生成/);

  reconnect.get("chatgpt-login-button").click();
  const staleLogin = loginRequests(reconnect).at(-1);
  reconnect.get("model-settings-close").click();
  reconnect.get("model-settings-button").click();
  latestStatus(reconnect).resolve(response(chatgptFixture("connected", 2)));
  await flush();
  staleLogin.resolve(response(chatgptFixture("error", 1, "Old login error")));
  await flush();
  assert.match(reconnect.get("chatgpt-login-status").textContent, /ChatGPT 已连接/, "an old login completion cannot clobber a newer status read");
  assert(!reconnect.get("chatgpt-login-button").disabled, "a late login response releases its click guard after reopening");

  reconnect.get("chatgpt-login-button").click();
  loginRequests(reconnect).at(-1).resolve(response(chatgptFixture("pending", 3)));
  await flush();
  let polls = 0;
  while ([...reconnect.timers.values()].some(timer => timer.delay === 2000)) {
    fireLoginPoll(reconnect);
    latestStatus(reconnect).resolve(response(chatgptFixture("pending", 3)));
    await flush();
    assert(++polls <= 150, "authorization polling is bounded");
  }
  assert.equal(polls, 150);
  assert.match(reconnect.get("chatgpt-login-status").textContent, /查询已暂停/);
  assert(reconnect.get("chatgpt-login-button").disabled, "a pending backend attempt remains protected when local polling stops");
  reconnect.get("model-settings-close").click();
  reconnect.get("model-settings-button").click();
  latestStatus(reconnect).resolve(response(chatgptFixture("pending", 3)));
  await flush();
  assert([...reconnect.timers.values()].some(timer => timer.delay === 2000), "reopening resumes bounded polling for the same backend login");
  reconnect.get("model-settings-close").click();
}

async function checkModelSettings() {
  const saved = { version: 2, graph: fixture, mastery: { base: flags }, draft: "Offline goal", source: "generated" };
  const environment = makeEnvironment({ narrow: true, saved });
  await flush();
  settlePlan(environment);
  await flush();
  assert.equal(settingsRequests(environment).length, 0, "offline restoration never reads settings or waits for a model connection");
  assert.equal(environment.get("model-api-key").getAttribute("type"), "password");
  assert.equal(environment.get("model-api-key").getAttribute("autocomplete"), "off");
  assert(environment.get("model-settings-panel").hidden);
  environment.get("model-settings-button").click();
  const staleRead = latestSettings(environment);
  assert(!environment.get("model-settings-panel").hidden);
  assert.equal(environment.get("model-settings-panel").getAttribute("role"), "dialog");
  assert.equal(environment.get("model-settings-panel").getAttribute("aria-modal"), "true");
  assert(environment.get("goal-form").closest("[inert]"));
  assert.equal(environment.document.activeElement, environment.get("model-settings-close"));
  environment.get("model-settings-close").click();
  assert(staleRead.options.signal.aborted);
  assert.equal(environment.document.activeElement, environment.get("model-settings-button"));
  environment.get("model-settings-button").click();
  const currentRead = latestSettings(environment);
  staleRead.resolve(response(settingsFixture({ provider: "api", model: "stale-model", has_api_key: true, revision: "stale" })));
  await flush();
  assert.equal(environment.evaluate("modelSettings"), null, "a closed dialog's late read cannot replace the new read");
  currentRead.resolve(response(settingsFixture({ api_key: "server-extra-secret-must-be-discarded" })));
  await flush();
  assert.equal(environment.get("model-provider").value, "chatgpt");
  assert(environment.get("model-api-fields").hidden);
  assert(environment.get("model-settings-clear").disabled);
  assert(!environment.evaluate("JSON.stringify(modelSettings)").includes("server-extra-secret"), "public state only retains the settings whitelist");
  assert.equal(testRequests(environment).length, 0, "opening and reading settings never tests the connection");
  const focusable = environment.evaluate("modelSettingsFocusableElements()");
  focusable.at(-1).focus();
  assert(environment.document.dispatch("keydown", { key: "Tab" }).defaultPrevented);
  assert.equal(environment.document.activeElement, focusable[0]);
  assert(environment.document.dispatch("keydown", { key: "Tab", shiftKey: true }).defaultPrevented);
  assert.equal(environment.document.activeElement, focusable.at(-1));
  environment.document.dispatch("focusin", { target: environment.get("goal-input") });
  assert.equal(environment.document.activeElement, environment.get("model-settings-close"));
  environment.document.dispatch("keydown", { key: "Escape" });
  assert(environment.get("model-settings-panel").hidden);
  assert.equal(environment.get("goal-form").closest("[inert]"), null);

  environment.evaluate('openLesson("vector")');
  latestLesson(environment, "vector").resolve(response(lessonFixture("vector")));
  await flush();
  environment.evaluate('openLesson("chain")');
  const lateCard = latestLesson(environment, "chain");
  prerequisiteRow(environment, "base").querySelector(".prerequisite-toggle").click();
  const lateSummary = latestLesson(environment, "base");
  const beforeSettings = environment.snapshot();
  environment.evaluate('loadRequestedGraph("generated", "Pending goal")');
  const lateGraph = environment.requests.find(request => request.url === "/analyze");
  environment.get("model-settings-button").click();
  assert(lateCard.options.signal.aborted && lateSummary.options.signal.aborted,
    "opening settings closes the mobile lesson and aborts both main and inline requests");
  assert.equal(environment.snapshot().activeLessonId, null, "there is only one modal at a time");
  assert.equal(settingsRequests(environment).length, 2, "reopening loaded settings reuses public settings");
  assert.deepEqual(environment.snapshot().mastery, beforeSettings.mastery);
  lateCard.resolve(response(lessonFixture("chain")));
  lateSummary.resolve(response(lessonFixture("base")));
  await flush();
  assert(!environment.evaluate('lessonCache.has("chain") || lessonCache.has("base")'), "late lesson results cannot seed the cache after settings opens");
  assert(environment.evaluate('lessonCache.has("vector")'), "opening settings alone retains valid cached cards");

  environment.get("model-provider").value = "api";
  environment.get("model-provider").dispatch("change");
  assert(!environment.get("model-api-fields").hidden);
  assert.match(environment.get("model-provider-status").textContent, /ChatGPT 授权/, "an unsaved selection never claims to be active");
  environment.get("model-base-url").value = "https://models.example.test/v1";
  environment.get("model-model").value = "example-model";
  const syntheticKey = "synthetic-test-key-never-a-real-credential";
  environment.get("model-api-key").value = syntheticKey;
  for (const [id, limit] of [["model-base-url", 2048], ["model-model", 200], ["model-api-key", 4096]]) {
    const previous = environment.get(id).value;
    environment.get(id).value = "x".repeat(limit + 1);
    environment.get("model-settings-form").dispatch("submit");
    assert.equal(settingsRequests(environment, "POST").length, 0, "oversized settings are rejected before transmission");
    environment.get(id).value = previous;
  }
  const modelRequestsBeforeSave = environment.requests.filter(request => ["/analyze", "/lesson"].includes(request.url)).length;
  environment.get("model-settings-form").dispatch("submit");
  const saving = latestSettings(environment, "POST");
  assert.equal(JSON.parse(saving.options.body).api_key, syntheticKey);
  assert.equal(environment.get("model-api-key").value, "", "submission immediately clears the key input");
  assert(environment.get("model-settings-save").disabled);
  assert.match(environment.get("model-settings-message").textContent, /关闭设置不会取消/);
  environment.get("model-settings-close").click();
  environment.get("model-settings-button").click();
  assert(environment.get("model-settings-save").disabled, "reopening during a save prevents editing stale values");
  assert.match(environment.get("model-settings-message").textContent, /仍在保存/);
  const apiSettings = settingsFixture({ provider: "api", base_url: "https://models.example.test/v1", model: "example-model", has_api_key: true, revision: "saved-api" });
  saving.resolve(response(apiSettings));
  await flush();
  assert.equal(environment.get("model-api-key").value, "");
  assert.match(environment.get("model-api-key").getAttribute("placeholder"), /已保存密钥/);
  assert.match(environment.get("model-provider-status").textContent, /example-model.*models\.example\.test/);
  assert(!environment.get("model-settings-clear").disabled);
  assert.equal(environment.evaluate("lessonCache.size"), 0, "a saved provider change invalidates all frontend cards");
  assert(lateGraph.options.signal.aborted, "saving aborts graph generation from the previous provider");
  assert.equal(environment.requests.filter(request => ["/analyze", "/lesson"].includes(request.url)).length, modelRequestsBeforeSave,
    "saving settings never starts generation or a lesson request");
  assert.equal(testRequests(environment).length, 0, "saving never starts a billable test");
  assert.equal(environment.document.activeElement, environment.get("model-settings-close"), "save completion never steals focus");
  const unchanged = environment.snapshot();
  lateGraph.resolve(response({ target_id: "late", nodes: [{ id: "late", label: "Old provider result", prerequisite_sets: [] }] }));
  await flush();
  assert.deepEqual(environment.snapshot(), unchanged, "a late graph response cannot replace the retained graph after saving");
  assert.deepEqual(environment.snapshot().mastery, beforeSettings.mastery);
  environment.evaluate("saveWorkspace()");
  environment.get("export-button").click();
  const exported = await environment.downloads[0].text();
  assert(!exported.includes(syntheticKey) && !exported.includes("api_key") && !exported.includes("base_url"));
  assert(![...environment.storage.values()].join(" ").includes(syntheticKey));
  assert(!environment.evaluate("JSON.stringify(modelSettings)").includes(syntheticKey));

  environment.get("model-model").value = "changed-but-unsaved";
  environment.get("model-settings-test").click();
  assert.equal(testRequests(environment).length, 0, "dirty settings must be saved before a connection test");
  assert.match(environment.get("model-settings-message").textContent, /请先保存/);
  environment.get("model-model").value = "example-model";
  environment.get("model-settings-test").click();
  assert.equal(testRequests(environment).length, 1, "only an explicit clean-form test click sends a test");
  assert.equal(testRequests(environment)[0].options.body, undefined, "tests only use the saved backend configuration");
  environment.get("model-settings-close").click();
  environment.get("model-settings-button").click();
  assert.match(environment.get("model-settings-message").textContent, /可能计费/);
  testRequests(environment)[0].resolve(response({ ok: true, message: "Do not echo arbitrary returned model content" }));
  await flush();
  assert.equal(environment.get("model-settings-message").textContent, "测试完成：收到有效模型回答。");

  environment.get("model-model").value = "invalid-platform-model";
  environment.get("model-api-key").value = "synthetic-replacement-key";
  environment.get("model-settings-form").dispatch("submit");
  latestSettings(environment, "POST").resolve({ ok: false, status: 400, json: async () => ({ detail: "安全错误：模型配置未保存。" }) });
  await flush();
  assert.equal(environment.evaluate("modelSettings.revision"), "saved-api", "a rejected save preserves the active saved settings");
  assert.match(environment.get("model-provider-status").textContent, /example-model/);
  assert.equal(environment.get("model-api-key").value, "");
  assert.equal(environment.get("model-settings-error").textContent, "安全错误：模型配置未保存。");

  environment.get("model-model").value = "example-model";
  environment.get("model-settings-form").dispatch("submit");
  const withoutReplacement = latestSettings(environment, "POST");
  assert(!Object.hasOwn(JSON.parse(withoutReplacement.options.body), "api_key"), "a blank key leaves the existing backend key intact");
  withoutReplacement.resolve(response({ ...apiSettings, revision: "blank-key-save" }));
  await flush();
  environment.get("model-model").value = "unsaved-does-not-affect-clearing";
  environment.get("model-settings-clear").click();
  const clearing = latestSettings(environment, "POST");
  assert.deepEqual(JSON.parse(clearing.options.body), {
    provider: "api", base_url: "https://models.example.test/v1", model: "example-model",
    api_format: "chat_completions", output_mode: "json_object", clear_api_key: true,
  }, "clearing uses saved public fields and never sends a replacement key or unsaved edits");
  clearing.resolve(response(settingsFixture({ ...apiSettings, has_api_key: false, revision: "cleared" })));
  await flush();
  assert.match(environment.get("model-settings-message").textContent, /已清除密钥，当前连接参数已保留/);
  assert(!environment.get("model-api-fields").hidden);
  assert.equal(environment.get("model-provider").value, "api", "clearing a key preserves the saved provider");
  assert(environment.get("model-api-key").required, "the retained API needs a replacement key");
  assert(environment.get("model-settings-test").disabled);
  assert(environment.get("model-settings-clear").disabled);
  environment.get("model-api-key").value = "synthetic-draft-key";
  environment.get("model-settings-close").click();
  assert.equal(environment.get("model-api-key").value, "", "closing always removes a draft key");
  assert.equal(environment.get("goal-form").closest("[inert]"), null);
  assert.deepEqual(environment.snapshot().graph, beforeSettings.graph);
  assert.deepEqual(environment.snapshot().mastery, beforeSettings.mastery);
}

async function main() {
  const environment = makeEnvironment({ narrow: true });
  await flush();
  checkLessonValidation(environment);
  assert.equal(environment.snapshot().viewMode, "list", "mobile defaults to a readable list");
  environment.context.nextFile = file(envelope());
  await environment.evaluate("importWorkspace(nextFile)");
  await flush();
  assert.deepEqual(environment.snapshot().known, ["base"]);
  assert.equal(JSON.parse(environment.storage.get("mathpath.v1.workspace")).version, 2, "browser storage stays version 2");
  settlePlan(environment);
  await flush();
  checkNumbering(environment);
  const validSnapshot = environment.snapshot();
  const malformed = [
    "{broken", envelope({ extra: true }), envelope({ version: 2 }), envelope({ source: "unknown" }),
    envelope({ graph: { ...fixture, injected: true } }),
    envelope({ graph: { ...fixture, nodes: fixture.nodes.map((node, index) => index === 0 ? { ...node, extra: true } : node) } }),
    envelope({ mastery: { base: { ...flags, extra: true } } }),
    envelope({ mastery: { base: { ...flags, definition: "true" } } }),
    envelope({ mastery: { foreign: flags } }), envelope({ draft: "x".repeat(5001) }),
    envelope({ graph: { ...fixture, nodes: fixture.nodes.map(node => node.id === "base" ? { ...node, prerequisite_sets: [["goal"]] } : node) } }),
  ];
  for (const invalid of malformed) {
    environment.context.nextFile = file(invalid);
    await environment.evaluate("importWorkspace(nextFile)");
    assert.deepEqual(environment.snapshot(), validSnapshot, "invalid import preserves graph, mastery, draft and view");
  }
  environment.context.nextFile = { size: 1024 * 1024 + 1, text: () => { throw new Error("must not read oversized files"); } };
  await environment.evaluate("importWorkspace(nextFile)");
  assert.deepEqual(environment.snapshot(), validSnapshot);

  environment.get("node-search").value = "CHAIN";
  environment.get("node-search").dispatch("input");
  assert.equal(environment.get("node-list").querySelectorAll("button").length, 1, "search matches node labels without case sensitivity");
  assert.match(environment.get("node-list").textContent || environment.get("node-list").querySelector(".node-browser-label").textContent, /Chain complex/);
  environment.get("node-search").value = "";
  environment.get("node-search").dispatch("input");
  const states = environment.get("node-list").querySelectorAll(".node-browser-state").map(element => element.textContent);
  assert(states.some(label => label.includes("建议先从这里学") && label.includes("当前可学")));
  assert(states.some(label => label.includes("学习目标") && label.includes("先修未满足")));
  environment.evaluate('updateMastery("vector", {definition:true})');
  assert.equal(environment.snapshot().known.length, 1, "one dimension does not count as complete");
  assert.equal(environment.get("progress-bar").getAttribute("aria-valuenow"), "1");
  assert.match(environment.get("progress-detail").textContent, /部分标记 1/);
  assert.match(environment.get("progress-summary").textContent, /自行标记/);
  const beforeViewSwitch = environment.snapshot();
  environment.get("graph-view-button").click();
  environment.get("list-view-button").click();
  assert.deepEqual(environment.snapshot().graph, beforeViewSwitch.graph);
  assert.deepEqual(environment.snapshot().mastery, beforeViewSwitch.mastery);

  const opener = environment.get("node-list").querySelectorAll("button").find(button => button.getAttribute("data-node-id") === "vector");
  opener.focus();
  opener.click();
  assert.equal(environment.snapshot().activeLessonId, "vector");
  assert.equal(environment.get("lesson-panel").getAttribute("aria-modal"), "true");
  assert(environment.get("workspace").classList.contains("lesson-open"));
  assert(environment.get("goal-form").closest("[inert]"), "mobile background is inert");
  const vectorRequest = [...environment.requests].reverse().find(request => request.url === "/lesson");
  vectorRequest.resolve(response(lessonFixture()));
  await flush();
  assert.match(environment.get("lesson-title").textContent, /^知识点 2 ·/);
  checkEnrichedLessonRendering(environment);
  const focusable = environment.evaluate("lessonFocusableElements()");
  focusable[focusable.length - 1].focus();
  const forwardTab = environment.document.dispatch("keydown", { key: "Tab", shiftKey: false });
  assert(forwardTab.defaultPrevented);
  assert.equal(environment.document.activeElement, focusable[0]);
  const backwardTab = environment.document.dispatch("keydown", { key: "Tab", shiftKey: true });
  assert(backwardTab.defaultPrevented);
  assert.equal(environment.document.activeElement, focusable[focusable.length - 1]);
  const masteryBeforeNavigation = environment.snapshot().mastery;
  environment.get("lesson-next").click();
  assert.equal(environment.snapshot().activeLessonId, "chain", "navigation follows topological layers rather than JSON node order");
  assert.deepEqual(environment.snapshot().mastery, masteryBeforeNavigation, "opening the next card never marks mastery");
  assert(environment.get("lesson-illustration-section").hidden);
  assert.equal(environment.get("lesson-illustration-viewport").children.length, 0, "switching nodes removes the previous SVG during loading");
  assert(environment.get("followup-section").hidden);
  assert.equal(environment.get("followup-list").children.length, 0, "switching nodes removes the previous follow-up answers during loading");
  const chainLegacy = lessonFixture("chain");
  delete chainLegacy.followup_exercises;
  delete chainLegacy.illustration;
  const chainRequest = [...environment.requests].reverse().find(request => request.url === "/lesson");
  chainRequest.resolve(response(chainLegacy));
  await flush();
  assert(!environment.get("lesson-content").hidden, "an older card still renders");
  assert(environment.get("lesson-illustration-section").hidden, "an older card leaves no empty illustration section");
  assert(environment.get("followup-section").hidden, "an older card leaves no empty follow-up section");
  assert.equal(environment.get("lesson-illustration-viewport").children.length, 0);
  assert.equal(environment.get("followup-list").children.length, 0);
  const cachedRequestCount = environment.requests.filter(request => request.url === "/lesson").length;
  environment.get("lesson-previous").click();
  assert.equal(environment.snapshot().activeLessonId, "vector");
  assert.equal(environment.requests.filter(request => request.url === "/lesson").length, cachedRequestCount, "returning to a cached enriched card does not request it again");
  assert(environment.get("followup-list").querySelectorAll("details").every(details => !details.open), "cached card opens with follow-up answers collapsed");
  assert(environment.get("exercise-options").querySelectorAll("input")[0].checked, "cached card restores the micro exercise choice");
  assert(!environment.get("exercise-feedback").hidden, "cached card restores micro exercise feedback");
  assert.deepEqual(environment.snapshot().mastery, masteryBeforeNavigation);
  environment.setNarrow(false);
  assert.equal(environment.get("lesson-panel").getAttribute("aria-modal"), null);
  assert.equal(environment.get("goal-form").closest("[inert]"), null);
  assert(!environment.document.dispatch("keydown", { key: "Tab", shiftKey: false }).defaultPrevented, "desktop cards are nonmodal");
  environment.setNarrow(true);
  assert.equal(environment.get("lesson-panel").getAttribute("aria-modal"), "true");
  environment.document.dispatch("keydown", { key: "Escape" });
  assert.equal(environment.snapshot().activeLessonId, null);
  assert.equal(environment.document.activeElement.getAttribute("data-node-id"), "vector", "Escape returns focus to the original list opener after navigation/rerenders");
  assert.equal(environment.get("goal-form").closest("[inert]"), null);

  environment.get("export-button").click();
  const exported = JSON.parse(await environment.downloads[0].text());
  assert.deepEqual(Object.keys(exported).sort(), ["draft", "format", "graph", "mastery", "source", "version"]);
  assert.equal(exported.format, "mathpath-workspace");
  assert.equal(exported.version, 1);
  for (const timer of environment.timers.values()) if (timer.delay === 1000) timer.callback();
  assert.equal(environment.revoked.length, 1, "download object URLs are revoked");

  environment.evaluate('loadRequestedGraph("generated", "New goal")');
  const lateModel = [...environment.requests].reverse().find(request => request.url === "/analyze");
  environment.context.nextFile = file(envelope({ draft: "Import wins" }));
  await environment.evaluate("importWorkspace(nextFile)");
  const afterImport = environment.snapshot();
  assert(lateModel.options.signal.aborted, "successful import aborts the pending model request");
  lateModel.resolve(response({ target_id: "replacement", nodes: [{ id: "replacement", label: "Stale result", prerequisite_sets: [] }] }));
  await flush();
  assert.deepEqual(environment.snapshot(), afterImport, "a late model result cannot overwrite imported data");

  let resolveFile;
  environment.context.nextFile = { size: 50, text: () => new Promise(resolve => { resolveFile = resolve; }) };
  const reading = environment.evaluate("importWorkspace(nextFile)");
  environment.evaluate('loadRequestedGraph("example")');
  const laterGraph = [...environment.requests].reverse().find(request => request.url === "/example");
  laterGraph.resolve(response({ target_id: "newest", nodes: [{ id: "newest", label: "Newest graph", prerequisite_sets: [] }] }));
  await flush();
  resolveFile(JSON.stringify(envelope({ draft: "Stale file" })));
  await reading;
  assert.equal(environment.snapshot().graph.target_id, "newest", "a file still being read cannot overwrite a newer graph request");

  const legacy = { target_id: "goal", nodes: [{ id: "goal", label: "理解同调群取商是为了排除本身能填成边界的循环，并让表示同一个洞的循环归为同一同调类", prerequisite_sets: [] }] };
  const restore = makeEnvironment({ saved: { version: 1, graph: legacy, known_ids: ["goal"], draft: "Saved draft", source: "example" } });
  assert.equal(restore.get("goal-input").value, "Saved draft", "draft is restored before awaiting example upgrade");
  restore.get("goal-input").value = "User edit during upgrade";
  const upgrade = restore.requests.find(request => request.url === "/example");
  upgrade.resolve(response({ target_id: "goal", nodes: [{ id: "goal", label: "Updated target", prerequisite_sets: [] }] }));
  await flush();
  assert.equal(restore.snapshot().draft, "User edit during upgrade", "example upgrade never overwrites a newer draft edit");
  assert.deepEqual(restore.snapshot().known, ["goal"], "v1 known_ids migrate into three mastery dimensions");
  assert.equal(JSON.parse(restore.storage.get("mathpath.v1.workspace")).version, 2);

  await checkPrerequisites();
  await checkModelSettings();
  await checkChatgptLogin();
  console.log("PASS frontend v0.3.2: existing learning flows, model settings, protected keys, explicit ChatGPT login, bounded polling, modal focus and stale response guards");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
