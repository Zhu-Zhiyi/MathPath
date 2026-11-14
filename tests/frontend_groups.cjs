"use strict";

// Real planner -> UI checks. Uses a bounded DOM harness, no credentials or models.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const oldSupport = fs.readFileSync(path.join(__dirname, "frontend_v03.cjs"), "utf8");
const source = oldSupport.slice(0, oldSupport.indexOf("function checkLessonValidation"))
  .replace("AbortController, Blob,", 'AbortController, Blob, URLSearchParams, crypto: require("node:crypto").webcrypto,')
  .replace('if (element.getAttribute("id"))', 'if (element.attributes.has("checked")) element.checked = true;\n    if (element.getAttribute("id"))')
  .replace('window: { matchMedia: () => media, addEventListener() {} },', 'window: { innerWidth: 1200, innerHeight: 850, matchMedia: () => media, addEventListener() {} },');
const { makeEnvironment, fixture, lessonFixture, flush, response } = new Function("require", "__dirname", `${source}\nreturn {makeEnvironment,fixture,lessonFixture,flush,response};`)(require, __dirname);
const copy = value => JSON.parse(JSON.stringify(value));
const text = element => [element.textContent, ...element.children.map(text)].join(" ");

function plannerCases(cases) {
  const project = path.resolve(__dirname, "..");
  const python = process.env.MATHPATH_TEST_PYTHON || path.join(project, ".venv", "Scripts", "python.exe");
  const code = `import json,sys,tempfile,os
with tempfile.TemporaryDirectory(prefix='mathpath-group-ui-') as data:
 os.environ['MATHPATH_DATA_DIR']=data
 from graph_builder import KnowledgeGraph
 from planner import current_learning_status
 cases=json.load(sys.stdin)
 print(json.dumps([current_learning_status(KnowledgeGraph.model_validate(c['graph']),c.get('known_ids',[]),mode=c.get('mode'),mastery=c.get('mastery',{})).model_dump() for c in cases]))`;
  const result = spawnSync(python, ["-B", "-c", code], { cwd: project, input: JSON.stringify(cases), encoding: "utf8",
    env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONDONTWRITEBYTECODE: "1" }, maxBuffer: 2 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

async function applyPlan(env, value) {
  const request = [...env.requests].reverse().find(item => item.url === "/plan" && !item.answered);
  assert(request, "expected pending plan"); request.answered = true; request.resolve(response(value)); await flush();
  assert.equal(env.get("error-message").hidden, true, text(env.get("error-message")));
}

function install(env, graph, mastery = {}) {
  env.context.graphCandidate = copy(graph); env.context.masteryCandidate = copy(mastery);
  env.evaluate('ui.studyMode.value="intuition";installGraph(graphCandidate,new Map(Object.entries(masteryCandidate)),"generated")');
}

function openCached(env, id) {
  env.context.cardCandidate = lessonFixture(id);
  env.context.nodeToOpen = id;
  env.evaluate('lessonCache.set(nodeToOpen,{lesson:validateLesson(cardCandidate,nodeToOpen),choice:null,answer:null});openLesson(nodeToOpen)');
}

async function main() {
  const partial = { base: { definition: true, intuition: true, application: false } };
  const plans = plannerCases([
    { graph: fixture, mode: "intuition", mastery: partial },
    { graph: fixture, mode: "intuition", mastery: { ...partial, vector: { definition: true, intuition: true, application: false } } },
    { graph: fixture, mode: "proof", mastery: partial },
    { graph: fixture, mode: "intuition", known_ids: ["goal"] },
    { graph: fixture, mode: "proof", mastery: { base: { definition: true, intuition: true, application: true } } },
  ]);
  assert(plans[0].prerequisite_groups?.length, "planner group diagnostics must be present");
  assert.deepEqual(plans[0].unlock_previews.find(item => item.node_id === "vector").newly_ready_ids, ["chain"]);
  assert.deepEqual(plans[0].unlock_previews.find(item => item.node_id === "alternative").newly_ready_ids, ["goal"], "one complete OR route suffices");
  assert.deepEqual(plans[2].unlock_previews.find(item => item.node_id === "base").newly_ready_ids, ["alternative"], "one member cannot unlock the two-member AND group");
  const env = makeEnvironment(); install(env, fixture, partial); await applyPlan(env, plans[0]);
  assert.deepEqual(env.snapshot().known, [], "mode sufficiency does not grant full mastery");
  const labels = env.get("graph-canvas").querySelectorAll(".gate-label").map(item => item.textContent);
  assert(labels.includes("全部 1/2"), "gate counts use mode-specific planning state");
  assert(labels.includes("全部 1/1"), "a sufficient partial capability satisfies a whole group");

  const previews = env.get("ready-list").querySelectorAll(".unlock-preview");
  assert(previews.length, "ready candidates explain the direct effect of learning them");
  const recordBefore = JSON.stringify(env.snapshot().mastery); const requestCount = env.requests.length;
  previews[0].open = true; previews[0].querySelector("summary").click();
  assert.equal(env.requests.length, requestCount, "expanding a hypothetical preview sends no request");
  assert.equal(JSON.stringify(env.snapshot().mastery), recordBefore, "preview never changes learner state");
  assert.match(text(previews[0]), /不修改掌握记录/);

  openCached(env, "chain");
  let group = env.get("prerequisite-groups").querySelector(".prerequisite-group");
  assert.match(text(group.querySelector(".prerequisite-group-status")), /已满足 1\/2/);
  assert.match(text(group.querySelector(".prerequisite-group-status")), /尚缺：知识点/);
  const base = group.querySelectorAll(".prerequisite-item").find(item => item.getAttribute("data-prerequisite-id") === "base");
  assert.match(base.querySelector(".prerequisite-state").textContent, /已满足当前目的/);
  assert.match(base.querySelector(".prerequisite-state").textContent, /2\/3/);
  env.context.cardCandidate = lessonFixture("base");
  env.evaluate('lessonCache.set("base",{lesson:validateLesson(cardCandidate,"base"),choice:null,answer:null})');
  const toggle = base.querySelector(".prerequisite-toggle"); toggle.click();
  const expanded = base.querySelector(".prerequisite-preview"); assert.equal(expanded.hidden, false);
  env.evaluate('updateMastery("vector",{definition:true,intuition:true})');
  assert.match(group.querySelector(".prerequisite-group-status").textContent, /正在计算/);
  await applyPlan(env, plans[1]);
  assert.equal(env.get("prerequisite-groups").querySelector(".prerequisite-group"), group, "refresh does not replace inline previews");
  assert.equal(expanded.hidden, false, "expanded material remains open after a new plan");
  assert.match(group.querySelector(".prerequisite-group-status").textContent, /已满足 2\/2/);
  assert.match(group.querySelector(".prerequisite-group-status").textContent, /先修要求已满足/);

  env.evaluate('ui.studyMode.value="proof";mastery.delete("vector");requestPlan()');
  await applyPlan(env, plans[2]);
  assert.match(group.querySelector(".prerequisite-group-status").textContent, /已满足 0\/2/);
  assert.match(base.querySelector(".prerequisite-state").textContent, /所需的能力尚未补齐/);
  assert.equal(expanded.hidden, false, "switching purpose also preserves inline material");

  env.evaluate('ui.studyMode.value="intuition";requestPlan()');
  const stale = [...env.requests].reverse().find(item => item.url === "/plan" && !item.answered);
  env.evaluate('ui.studyMode.value="proof";requestPlan()');
  await applyPlan(env, plans[2]);
  stale.answered = true; stale.resolve(response(plans[0])); await flush();
  assert.match(group.querySelector(".prerequisite-group-status").textContent, /已满足 0\/2/, "late responses cannot restore obsolete sufficiency");

  openCached(env, "goal");
  const groups = env.get("prerequisite-groups").querySelectorAll(".prerequisite-group");
  const selected = plans[2].selected_groups.find(item => item.node_id === "goal").group_index;
  assert(groups[selected].classList.contains("recommended-prerequisite-group"));
  assert.match(groups[selected].querySelector(".prerequisite-group-status").textContent, /当前推荐组/);

  // Reject wrong group membership, invented satisfaction, lost OR branches and transitive unlocks.
  const invalid = [
    plan => plan.prerequisite_groups[0].prerequisite_ids.push("base"),
    plan => { plan.prerequisite_groups[0].satisfied = !plan.prerequisite_groups[0].satisfied; },
    plan => plan.prerequisite_groups.pop(),
    plan => { plan.prerequisite_groups[0].selected = !plan.prerequisite_groups[0].selected; },
    plan => { plan.unlock_previews[0].newly_ready_ids = ["goal"]; },
    plan => plan.unlock_previews.pop(),
    plan => { plan.planning_known_ids = ["absent"]; },
  ];
  for (const mutate of invalid) {
    const value = copy(plans[0]); mutate(value); env.context.planCandidate = value;
    assert.throws(() => env.evaluate('validatePlan(planCandidate,[],graphCandidate)'), /invalid-plan/);
  }
  const legacy = copy(plans[0]); delete legacy.prerequisite_groups; delete legacy.unlock_previews;
  env.context.planCandidate = legacy;
  assert.doesNotThrow(() => env.evaluate('validatePlan(planCandidate,[],graphCandidate)'), "older servers remain supported");

  env.context.submittedContext = { mode: "proof", mastery: partial };
  env.context.planCandidate = plans[0];
  assert.throws(() => env.evaluate('validatePlan(planCandidate,[],graphCandidate,submittedContext)'), /invalid-plan/, "proof purpose rejects an intuition result");
  const wrongState = copy(plans[4]);
  env.context.planCandidate = wrongState;
  assert.throws(() => env.evaluate('validatePlan(planCandidate,[],graphCandidate,submittedContext)'), /invalid-plan/, "internally consistent group and unlock data cannot invent sufficient capabilities");
  const withoutMode = copy(plans[0]); delete withoutMode.mode;
  env.context.planCandidate = withoutMode;
  assert.throws(() => env.evaluate('validatePlan(planCandidate,[],graphCandidate,submittedContext)'), /invalid-plan/, "omitting mode cannot conceal an incorrect purpose-specific boundary");
  const oldServer = copy(plans[0]); delete oldServer.mode; delete oldServer.planning_known_ids;
  delete oldServer.prerequisite_groups; delete oldServer.unlock_previews;
  env.context.planCandidate = oldServer;
  assert.doesNotThrow(() => env.evaluate('validatePlan(planCandidate,[],graphCandidate,submittedContext)'), "legacy responses without optional purpose fields remain supported");

  const wrongPurpose = makeEnvironment(); install(wrongPurpose, fixture, partial);
  wrongPurpose.evaluate('ui.studyMode.value="proof";requestPlan()');
  const wrongRequest = [...wrongPurpose.requests].reverse().find(item => item.url === "/plan");
  wrongRequest.answered = true; wrongRequest.resolve(response(plans[0])); await flush();
  assert.equal(wrongPurpose.get("error-message").hidden, false, "the request path validates its captured purpose");
  assert.equal(wrongPurpose.evaluate("plan"), null);
  wrongPurpose.evaluate('requestPlan();mastery.set("base",{definition:true,intuition:true,application:true})');
  await applyPlan(wrongPurpose, plans[2]);
  assert.equal(wrongPurpose.evaluate('plan.planning_known_ids.length'), 0, "validation uses the submitted mastery snapshot rather than mutable current state");

  const complete = makeEnvironment({ narrow: true }); install(complete, fixture, { goal: { definition: true, intuition: true, application: true } });
  await applyPlan(complete, plans[3]);
  assert.equal(complete.get("ready-list").querySelectorAll(".unlock-preview").length, 0);
  openCached(complete, "goal"); assert.equal(complete.get("lesson-unlock-preview").hidden, true);
  assert.equal(complete.snapshot().viewMode, "list", "narrow screens retain the list view");
  assert(!env.requests.some(item => item.url === "/analyze" || item.url === "/study/chat" || item.url === "/settings/chatgpt/login"));
  console.log("PASS grouped prerequisite UI: real planner roundtrip, AND/OR states, mode-specific gates, direct hypothetical unlocks, no state/network side effects, preserved previews, stale-safe refresh, malformed response rejection and narrow view.");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
