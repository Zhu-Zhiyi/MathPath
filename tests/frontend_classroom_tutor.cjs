"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const base = fs.readFileSync(path.join(__dirname, "frontend_classroom.cjs"), "utf8");
const support = base.slice(0, base.indexOf("async function main()"));
const { environment, opened, job, clip, firstId, secondId, flush, allText } = new Function("require", "__dirname", support + "\nreturn {environment,opened,job,clip,firstId,secondId,flush,allText};")(require, __dirname);
const source = fs.readFileSync(path.join(__dirname, "..", "static", "classroom_tutor.js"), "utf8");
const copy = value => JSON.parse(JSON.stringify(value));
const sessionId = "33333333-3333-4333-8333-333333333333";
const makeRecord = (overrides = {}) => ({ id: sessionId, created_at: "2026-11-12T12:00:00Z", item_id: "c0_i0",
  question: "为什么要取商？", learner_context: "知道循环的定义。", source: "model_candidate", review_required: true, model: "synthetic",
  evidence: [{ id: "c0_i0", start_seconds: 10, end_seconds: 45, title: "同调群", source_summary: "课堂中写出 Z/B。" }],
  diagnosis: { status: "candidate", difficulty_kind: "prerequisite", hypothesis: "可能需要区分循环与边界。<script>unsafe()</script>",
    evidence_quotes: [{ evidence_id: "c0_i0", quote: "Z/B" }], prerequisites: [{ concept: "边界", why_needed: "解释为什么相差边界视为等价。", quick_check: "边界是否总是循环？" }],
    repair_steps: ["检查边界的边界。"], checkpoint: { question: "相差一个边界的两个循环如何比较？", hint: "考虑它们的差。", reference_answer: "它们代表同一同调类。", rubric: ["核对等价关系。"] },
    next_action: "try_check", uncertainties: ["仍需核对课堂的系数约定。"] }, attempts: [], ...overrides });

async function ready(records = []) {
  const lecture = job({ status: "completed", duration_seconds: 300, completed_chunks: 1, total_chunks: 1, processed_seconds: 300, coverage_ratio: 1, clips: [clip()] });
  const env = await opened(lecture);
  env.context.crypto = require("node:crypto").webcrypto;
  vm.runInContext(source, env.context, { filename: "classroom_tutor.js" });
  env.respond(`/lectures/${firstId}/tutor`, records); await flush();
  return env;
}

async function main() {
  const env = await ready();
  assert.equal(env.requests.filter(r => r.options?.method === "POST").length, 0, "opening tutor never calls a model");
  assert(env.get("tutor-item").value, "the existing lecture supplies the available evidence");
  env.context.window.MathPathTutor.selectItem(0, 0);
  env.get("tutor-question").value = "为什么要取商？"; env.get("tutor-question").dispatch("input");
  env.get("tutor-context").value = "知道循环的定义。";
  env.get("tutor-use-model").checked = false;
  const lectureBefore = env.evaluate("JSON.stringify(currentLecture)");
  const creating = env.evaluate("ctDiagnose()");
  const post = env.requests.find(r => r.url.endsWith("/tutor") && r.options?.method === "POST");
  const submitted = JSON.parse(post.options.body);
  assert.equal(submitted.item_id, "c0_i0"); assert.equal(submitted.use_model, false);
  assert.equal(env.get("tutor-diagnose").disabled, true);
  const record = makeRecord({ id: submitted.request_id, source: "local_reference" });
  env.respond(`/lectures/${firstId}/tutor`, record); await creating;
  assert.match(allText(env.get("tutor-result")), /本地对照/);
  assert.equal(env.get("tutor-result").querySelectorAll("script,img,iframe").length, 0);
  assert.equal(env.evaluate("JSON.stringify(currentLecture)"), lectureBefore, "diagnosis never modifies lecture/mastery state");
  const input = env.get("tutor-result").querySelector("textarea"); input.value = "相差边界表示同一个类。";
  const answering = env.evaluate('ctAnswer("相差边界表示同一个类。")');
  const answerPost = env.requests.find(r => r.url.endsWith("/answer"));
  assert(answerPost.url.includes(record.id));
  const updated = copy(record);
  updated.attempts.push({ id: "44444444-4444-4444-8444-444444444444", answer: "相差边界表示同一个类。", source: "local_reference", review_required: true,
    feedback: { assessment: "needs_review", feedback: "请对照条件核查，不代表已掌握。", remaining_gap: "需要说明系数约定。", next_action: "try_again", next_prompt: "为什么是等价关系？" } });
  env.respond(answerPost.url, updated); await answering;
  assert.match(allText(env.get("tutor-result")), /第 1 次解释/);
  assert.match(allText(env.get("tutor-result")), /候选意见/);
  assert.equal(env.get("tutor-result").querySelector("textarea").value, input.value, "refreshing the same record preserves the student's draft");
  assert.equal(env.evaluate("JSON.stringify(currentLecture)"), lectureBefore);
  env.context.moreLecture = JSON.parse(lectureBefore);
  env.context.moreLecture.clips[0].analysis.items.push({ ...env.context.moreLecture.clips[0].analysis.items[0], start_seconds: 100, end_seconds: 150, title: "第二个课堂内容" });
  env.evaluate("renderLecture(validateLecture(moreLecture))");
  env.get("tutor-item").value = "c0_i1"; env.get("tutor-item").dispatch("change");
  assert.equal(env.get("tutor-result").children.length, 0, "changing evidence cannot reuse the old checkpoint");
  const beforeAnswer = env.requests.length; env.evaluate('ctAnswer("不能串到旧检查题")');
  assert.equal(env.requests.length, beforeAnswer);
  env.get("tutor-history").value = record.id; env.get("tutor-history").dispatch("change");
  assert.equal(env.get("tutor-result").querySelector("textarea").value, input.value, "source switching preserves unsubmitted work in the matching history");
  env.context.badRecord = copy(updated); env.context.badRecord.diagnosis.evidence_quotes[0].quote = "不存在的引用";
  assert.throws(() => env.evaluate("ctValidate(badRecord)"), /引文/);
  env.context.badRecord = copy(updated); env.context.badRecord.review_required = false;
  assert.throws(() => env.evaluate("ctValidate(badRecord)"), /格式/);

  const retry = await ready();
  retry.get("tutor-question").value = "再检查这一步";
  const failing = retry.evaluate("ctDiagnose()");
  const firstRequest = retry.requests.at(-1);
  const requestId = JSON.parse(firstRequest.options.body).request_id;
  retry.respond(`/lectures/${firstId}/tutor`, { detail: "合成的模型请求失败。" }, 502); await failing;
  const secondTry = retry.evaluate("ctDiagnose()");
  assert.equal(JSON.parse(retry.requests.at(-1).options.body).request_id, requestId, "manual retry reuses the idempotency key for the same question");
  retry.respond(`/lectures/${firstId}/tutor`, makeRecord({ id: requestId })); await secondTry;

  const stale = await ready(); stale.get("tutor-question").value = "A 课堂的旧问题";
  const old = stale.evaluate("ctDiagnose()");
  stale.context.nextLecture = job({ id: secondId });
  stale.evaluate("window.MathPathTutor.onPending(true);window.MathPathTutor.onLecture(nextLecture);window.MathPathTutor.onPending(false)");
  stale.respond(`/lectures/${secondId}/tutor`, []); await flush();
  stale.respond(`/lectures/${firstId}/tutor`, makeRecord({ question: "A 课堂的旧问题" })); await old;
  assert.equal(stale.get("tutor-result").children.length, 0, "late results cannot enter a different classroom");
  assert.equal(stale.get("tutor-question").value, "");

  const restored = await ready([updated]);
  assert.match(allText(restored.get("tutor-result")), /第 1 次解释/);
  assert.equal(restored.get("tutor-context").value, updated.learner_context);
  assert.equal(restored.requests.filter(r => r.options?.method === "POST").length, 0);
  const count = restored.requests.length;
  restored.get("tutor-result").querySelector(".tutor-reference").open = true;
  assert.equal(restored.requests.length, count, "opening hints/reference never requests a model");
  console.log("PASS classroom tutor: grounded evidence, explicit model choice, learner explanations, persistent attempts, idempotent retries, draft preservation, safe rendering, snapshot isolation and no mastery mutation.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
