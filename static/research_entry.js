(() => {
  "use strict";
  const select = document.getElementById("research-workspace");
  const note = document.getElementById("research-entry-note");
  if (!select) return;
  window.MathPathResearch = { selected: () => select.value };
  let profiles = [];
  select.addEventListener("change", () => {
    const p = profiles.find(w => w.id === select.value);
    note.textContent = p ? `${p.intent === "question" ? "围绕研究问题选择先修" : p.intent === "explore" ? "先完成学习，课后可查看近期文献线索" : "专注系统学习"}。仅用于下一次生成，现有历史不受影响。` : "本次只学习。研究背景只用于下一次构图。";
    try { localStorage.setItem("mathpath-research-workspace", select.value); } catch {}
  });
  fetch("/research/workspaces", { cache: "no-store" }).then(r => { if (!r.ok) throw Error(); return r.json(); }).then(rows => {
    profiles = rows;
    for (const p of rows) { const o = document.createElement("option"); o.value = p.id; o.textContent = p.title; select.append(o); }
    try { const id = localStorage.getItem("mathpath-research-workspace"); if (rows.some(w => w.id === id)) select.value = id; } catch {}
    if (select.value) select.dispatchEvent(new Event("change"));
  }).catch(() => { note.textContent = "研究背景暂未载入，可继续学习。"; });
  const section = document.createElement("section"); section.className = "review-panel";
  const h = document.createElement("h2"); h.textContent = "学完以后，下一步研究什么？";
  const p = document.createElement("p"); p.textContent = "已有问题可梳理下一步；尚未选题可用公开关键词查看近两年文献，再整理可检验的小课题。每条线索保留日期与出处。";
  const a = document.createElement("a"); a.href = "/research-workbench#directions"; a.textContent = "探索近期方向 →";
  section.append(h, p, a); document.querySelector("main").append(section);
})();
