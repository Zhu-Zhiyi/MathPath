/* Read saved analysis alongside the video; no model calls or file writes here. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const player = $("lecture-player"), content = $("watch-note-content");
  const type = $("watch-note-type"), follow = $("watch-note-follow"), segment = $("watch-note-segment");
  const status = $("watch-note-status"), layout = document.querySelector(".lecture-reading-layout");
  let lecture = null, selected = null, pending = false, rendered = "", mode = false, native = false, fullVersion = 0;
  type.value = "A";
  const text = (tag, value, cls = "") => mathText(node(tag, cls), value);
  function paragraph(parent, heading, value) {
    if (!value) return;
    if (heading) parent.append(node("h5", "", heading));
    parent.append(text("p", value));
  }
  function question(parent, task, index) {
    const box = node("article", "watch-practice");
    box.append(node("span", "item-kind", task.origin === "from_video" ? "课堂原题（模型识别）" : "辅助补充题"));
    box.append(text("h4", `${index + 1}. ${task.question}`));
    for (const [label, value] of [["提示", task.hint], ["参考答案（待核对）", task.answer]]) {
      const detail = node("details"); detail.append(node("summary", "", label), text("p", value)); box.append(detail);
    }
    parent.append(box);
  }
  function chooseAt(time) {
    if (lecture?.status === "completed" && player.ended && Math.abs(time - lecture.duration_seconds) < .05) return lecture.clips.at(-1) || null;
    return lecture?.clips.find(c => c.start_seconds <= time && time < c.end_seconds) || null;
  }
  function currentClip() { return lecture?.clips.find(c => c.index === selected) || null; }
  function section(parent, heading, id) {
    const box = node("section", "watch-note-section"); if (id) box.id = id;
    box.append(node("h4", "", heading)); parent.append(box); return box;
  }
  function item(parent, entry, clip, index, showSteps = true) {
    const box = node("article", "watch-note-item");
    box.setAttribute("data-item-index", String(index));
    const active = Number(player.currentTime) >= entry.start_seconds && Number(player.currentTime) < entry.end_seconds;
    box.classList.toggle("watch-item-current", active);
    box.append(node("span", "item-kind", KIND_LABELS[entry.kind]), text("h4", entry.title), seekButton(entry.start_seconds, entry.end_seconds));
    paragraph(box, "课堂内容（模型识别）", entry.source_summary);
    paragraph(box, "辅助解释 / 直观", entry.explanation);
    addList(box, "公式与符号", entry.formulas);
    if (showSteps) addList(box, "推导步骤（模型整理，需核对完整性）", entry.steps);
    addList(box, "待核对", entry.uncertainties, true);
    if (entry.evidence === "unclear") box.append(node("p", "uncertain-note", "声音或画面不清晰，请回看后再采用此内容。"));
    const ask = node("button", "text-button", "问问这一步"); ask.type = "button";
    ask.addEventListener("click", () => askItem(clip.index, index)); box.append(ask); parent.append(box);
  }
  function askItem(clip, index) {
    $("watch-questions").open = true;
    window.MathPathTutor?.selectItem(clip, index);
  }
  function highlight() {
    const clip = currentClip(); if (!clip) return;
    for (const box of content.querySelectorAll("[data-item-index]")) {
      const entry = clip.analysis.items[Number(box.getAttribute("data-item-index"))], time = Number(player.currentTime) || 0;
      box.classList.toggle("watch-item-current", follow.checked && time >= entry.start_seconds && time < entry.end_seconds);
    }
  }
  function render(force = false) {
    const time = Number(player.currentTime) || 0;
    $("watch-note-clock").textContent = clock(time);
    type.disabled = pending; segment.disabled = pending; follow.disabled = pending;
    if (pending) {
      content.replaceChildren(node("p", "timeline-empty", "正在打开所选课堂，笔记加载后显示。"));
      status.textContent = "正在切换课堂…"; rendered = "";
      $("watch-note-ask").disabled = true; $("watch-note-save").disabled = true; return;
    }
    if (follow.checked) selected = chooseAt(time)?.index ?? null;
    const clip = currentClip(); segment.value = clip ? String(clip.index) : "";
    const key = JSON.stringify([lecture?.id, clip, type.value, follow.checked]);
    $("watch-note-ask").disabled = !clip?.analysis.items.length;
    $("watch-note-save").disabled = !clip;
    if (!force && key === rendered) { highlight(); return; }
    rendered = key; content.replaceChildren();
    if (!clip) {
      status.textContent = lecture?.clips.length ? `当前 ${clock(time)} 没有已解析片段，不显示其他时间的笔记。` : "这堂课尚无解析笔记。";
      content.append(node("p", "timeline-empty", lecture?.clips.length ? "可以从上方选择已解析片段阅读，或继续解析后面的课堂。" : "先在视频下方完成解析设置；每解析完一段，这里就能显示，无需等整堂课结束。"));
      return;
    }
    const a = clip.analysis;
    status.textContent = `${follow.checked ? "跟随播放" : "正在固定阅读，播放不会切换"} · 第 ${clip.index + 1} 段 · ${clock(clip.start_seconds)}—${clock(clip.end_seconds)}`;
    content.append(text("h3", a.title), seekButton(clip.start_seconds, clip.end_seconds));
    if (type.value === "B") {
      if (!a.practice.length) content.append(node("p", "timeline-empty", "本段解析没有提供问题与参考答案。可点击“问问这一段”请求补充习题。"));
      a.practice.forEach((task, i) => question(content, task, i));
    } else {
      paragraph(content, "本段概览", a.overview);
      addList(content, "学习目标", a.learning_goals);
      if (type.value === "A") {
        const conclusions = section(content, "先看定义与结论", "watch-conclusions");
        const known = a.items.map((entry, i) => [entry, i]).filter(([entry]) => ["definition", "theorem"].includes(entry.kind));
        if (!known.length) conclusions.append(node("p", "small-note", "本段没有单独识别出的定义或定理，按下面的课堂内容阅读。"));
        known.forEach(([entry, i]) => item(conclusions, entry, clip, i, false));
        const toProof = node("a", "watch-proof-link", "查看本段证明与推导 ↓"); toProof.href = "#watch-proofs"; conclusions.append(toProof);
        const exposition = section(content, "解释与例子");
        a.items.forEach((entry, i) => { if (!["definition", "theorem", "proof"].includes(entry.kind)) item(exposition, entry, clip, i); });
        if (exposition.children.length === 1) exposition.append(node("p", "small-note", "本段没有单独的例子；已有辅助解释保留在对应结论下。"));
        const proofs = section(content, "附录 · 本段证明与推导", "watch-proofs");
        a.items.forEach((entry, i) => { if (entry.kind === "proof") item(proofs, entry, clip, i); else if (entry.steps.length) { paragraph(proofs, entry.title, "以下是模型整理的步骤，不表示已核对完整证明。"); addList(proofs, "推导", entry.steps); } });
        if (proofs.children.length === 1) proofs.append(node("p", "small-note", "本段没有识别到证明或推导，不能据此补出完整证明。"));
        const back = node("a", "watch-proof-link", "返回定义与结论 ↑"); back.href = "#watch-conclusions"; proofs.append(back);
      } else {
        const ordered = section(content, "按课堂讲授顺序阅读");
        a.items.forEach((entry, i) => item(ordered, entry, clip, i));
      }
      if (a.practice.length) { const practice = section(content, "用习题检查理解"); a.practice.forEach((task, i) => question(practice, task, i)); }
      addList(content, "识别范围与缺口", a.coverage_notes);
      addList(content, "本段仍需核对", a.uncertainties, true);
    }
    content.scrollTop = 0; highlight();
  }
  function onLecture(value) {
    if (lecture?.id !== value?.id) { selected = null; follow.checked = true; rendered = ""; }
    lecture = value; segment.replaceChildren();
    const empty = node("option", "", "选择片段阅读…"); empty.value = ""; segment.append(empty);
    for (const clip of lecture?.clips || []) { const opt = node("option", "", `${clip.index + 1}. ${clock(clip.start_seconds)} · ${clip.analysis.title}`); opt.value = String(clip.index); segment.append(opt); }
    render();
  }
  segment.addEventListener("change", () => { follow.checked = false; selected = segment.value === "" ? null : Number(segment.value); render(true); });
  type.addEventListener("change", () => render(true));
  follow.addEventListener("change", () => render(true));
  for (const event of ["timeupdate", "seeked", "loadedmetadata", "ended"]) player.addEventListener(event, () => render());
  $("watch-note-ask").addEventListener("click", () => { const c = currentClip(); if (!c || pending) return; const time = Number(player.currentTime) || 0; const i = c.analysis.items.findIndex(v => v.start_seconds <= time && time < v.end_seconds); askItem(c.index, Math.max(0, i)); });
  $("watch-note-save").addEventListener("click", () => {
    const c = currentClip(); if (!c || pending) return;
    $("classroom-local-save").open = true;
    window.dispatchEvent(new CustomEvent("mathpath-note-preview", {detail:{note_type:type.value,source_kind:"text",source_title:`${lecture.filename} · 第 ${c.index + 1} 段 · ${c.analysis.title}`,source_text:JSON.stringify({lecture:lecture.filename,start_seconds:c.start_seconds,end_seconds:c.end_seconds,analysis:c.analysis})}}));
  });
  async function exitMode() {
    ++fullVersion; mode = false; native = false; layout.classList.remove("classroom-watch-mode");
    $("watch-fullscreen").textContent = "伴学全屏 · 视频 + 笔记";
    if (document.fullscreenElement === layout) try { await document.exitFullscreen(); } catch {}
  }
  $("watch-fullscreen").addEventListener("click", async () => {
    if (mode) { await exitMode(); return; }
    const version = ++fullVersion; mode = true; layout.classList.add("classroom-watch-mode");
    $("watch-fullscreen").textContent = "退出伴学全屏";
    $("watch-fullscreen-status").textContent = "视频与笔记一起显示，按 Esc 或点击退出。";
    try {
      if (!layout.requestFullscreen) throw Error("unavailable");
      await layout.requestFullscreen();
      if (version !== fullVersion) { if (document.fullscreenElement === layout) await document.exitFullscreen(); return; }
      native = true;
    } catch { if (version === fullVersion) $("watch-fullscreen-status").textContent = "当前窗口未允许系统全屏，已使用专注视图；点击上方按钮退出。"; }
  });
  document.addEventListener("fullscreenchange", () => { if (native && document.fullscreenElement !== layout) exitMode(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && mode) exitMode(); });
  window.MathPathClassroomNotes = {onLecture, onPending(value) { pending = value; render(true); }};
  onLecture(typeof currentLecture !== "undefined" ? currentLecture : null);
})();
