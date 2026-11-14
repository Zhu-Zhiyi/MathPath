(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const form = $("theorem-form"), wf = $("workspace-form");
  form.hidden=true;
  form.parentElement.style.gridTemplateColumns="minmax(0,1fr)";
  const state = { workspaces: [], theorems: [], listVersion: 0, modelVersion: 0, editWorkspace: null };
  const element = (tag, text, parent) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (parent) parent.append(e); return e; };
  const math = el => { if (window.renderMathInElement) window.renderMathInElement(el, { delimiters: [{ left:"$$",right:"$$",display:true },{ left:"\\[",right:"\\]",display:true },{ left:"\\(",right:"\\)",display:false },{ left:"$",right:"$",display:false }],throwOnError:false,trust:false,strict:"warn" }); };
  async function api(path, body, method) {
    const r = await fetch(path, { method: method || (body ? "POST" : "GET"), cache:"no-store", headers:body ? {"Content-Type":"application/json"} : {}, ...(body ? { body:JSON.stringify(body) } : {}) });
    const v = await r.json(); if (!r.ok) throw Error(typeof v.detail === "string" ? v.detail : "填写内容有缺项或格式不合适，请检查后重试。"); return v;
  }
  async function action(button, status, task) { button.disabled = true; status.textContent = "正在处理…"; try { await task(); } catch(e) { status.textContent = e.message || "请求未完成，请重试。"; } finally { button.disabled = false; } }
  const workspace = () => $("workspace").value || null;
  const lines = value => value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  function selected() {
    state.modelVersion++;
    const w = state.workspaces.find(r => r.id === workspace());
    $("workspace-detail").textContent = w ? `${w.intent === "question" ? "已有研究问题" : w.intent === "explore" ? "学习后探索" : "只学习"}：${w.question || w.title}` : "可直接学习，也可以先创建研究起点。";
    $("paper-terms").value = w?.search_terms || "";
    $("guidance-result").replaceChildren(); $("papers-result").replaceChildren();
    $("guidance").disabled = !w;
    try { localStorage.setItem("mathpath-research-workspace", workspace() || ""); } catch {}
    $("theorem-scope").textContent = `新记录归入：${w?.title || "未分类"}。编辑旧记录时保留其原工作区。`;
    refreshTheorems();
  }
  async function loadWorkspaces(id) {
    state.workspaces = await api("/research/workspaces");
    const s = $("workspace"); s.replaceChildren(); const empty = element("option", "未选择", s); empty.value = "";
    for (const w of state.workspaces) { const o = element("option", w.title, s); o.value = w.id; }
    if (id && state.workspaces.some(w => w.id === id)) s.value = id;
    selected();
  }
  $("workspace").addEventListener("change", selected);
  wf.addEventListener("submit", e => { e.preventDefault(); action(wf.querySelector("button"), $("workspace-status"), async () => {
    const data = Object.fromEntries(new FormData(wf));
    const value = await api("/research/workspaces", data); await loadWorkspaces(value.id); $("workspace-status").textContent = "起点已保存到本机。可以回到学习地图，或点击下面的模型指引。";
  }); });
  $("guidance").addEventListener("click", () => {
    const version = state.modelVersion, id = workspace(); if (!id) return;
    action($("guidance"), $("workspace-status"), async () => {
      const result = await api("/research/guidance", {time:0,workspace_id:id});
      if (version !== state.modelVersion) return;
      $("guidance-result").textContent = result.answer + "\n\n待核对：" + result.uncertainties.join("；"); math($("guidance-result")); $("workspace-status").textContent = "模型给出的初步指引，尚未完成查新或证明。";
    });
  });
  $("papers-form").addEventListener("submit", e => { e.preventDefault(); const version = state.modelVersion;
    action(e.currentTarget.querySelector("button"), $("papers-status"), async () => {
      const result = await api("/research/explore", { terms:$("paper-terms").value, workspace_id:workspace(), use_model:$("paper-model").checked });
      if (version !== state.modelVersion) return;
      const out = $("papers-result"); out.replaceChildren();
      for (const d of result.directions) { const box = element("article", undefined, out); box.className = "record"; element("h3", d.title, box); element("p", d.why, box); element("p", "第一步：" + d.first_step, box); element("p", "先修：" + d.prerequisites.join("、"), box); element("p", "依据论文：" + d.paper_ids.join("、"), box); }
      for (const paper of result.papers) { const box = element("article", undefined, out); box.className = "record"; if (/^https:\/\/arxiv\.org\/abs\/[a-zA-Z\d./-]+$/.test(paper.url)) { const a = element("a", paper.title, box); a.href = paper.url; a.target = "_blank"; a.rel = "noopener noreferrer"; } element("p", `首次提交 ${paper.published.slice(0,10)} · ${paper.id}`, box); const detail = element("details", undefined, box); element("summary", "查看摘要", detail); element("p", paper.abstract, detail); }
      element("p", result.caveats.join("；"), out); math(out);
      $("papers-status").textContent = `${result.papers.length ? `找到 ${result.papers.length} 篇近期论文` : "没有找到匹配的近期论文，可缩短或更换英文关键词"}。检索于 ${result.retrieved_at.slice(0,10)}，近 ${result.window_days} 天。`;
    });
  });
  function edit(record) {
    form.hidden=false;
    for (const [key, value] of Object.entries(record)) if (form.elements.namedItem(key)) { const field = form.elements.namedItem(key); if (field.type === "checkbox") field.checked = !!value; else field.value = Array.isArray(value) ? value.join("\n") : value ?? ""; }
    form.elements.record_id.value = record.id; form.elements.expected_revision.value = record.revision; state.editWorkspace = record.workspace_id;
    $("theorem-status").textContent = `正在编辑第 ${record.revision} 版；保存后旧版将保留。`; form.elements.name.focus();
  }
  async function refreshTheorems() {
    const version = ++state.listVersion;
    try {
      const params = new URLSearchParams({q:$("theorem-search").value}); if (workspace()) params.set("workspace_id",workspace());
      const rows = await api("/research/theorems?" + params); if (version !== state.listVersion) return;
      state.theorems = rows; const list = $("theorem-list"); list.replaceChildren();
      if (!rows.length) element("p", "还没有匹配记录。可以手动保存，也可以从回放侧栏带入定理。", list);
      for (const r of rows) { const box = element("article", undefined, list); box.className = "record"; element("h3", r.name, box); const tag = element("span", r.verified_by_user ? "已由用户核对" : "候选，需核对", box); tag.className = "badge" + (r.verified_by_user ? "" : " candidate"); element("span", `第 ${r.revision} 版 · ${r.category === "common" ? "常见定理" : "非标准 / 待确定"}`, box); if (!r.statement_complete) element("p", "陈述待补全，不能直接引用", box); const details = element("details", undefined, box); element("summary", "查看陈述与出处", details); element("p", r.statement, details); element("p", "条件：" + r.assumptions.join("；"), details); element("p", "来源：" + r.source, details); const b = element("button", "编辑 / 核对", box); b.className = "quiet"; b.onclick = () => edit(r); const a = element("a", "下载 Markdown", box); a.href = `/research/theorems/${r.id}/markdown`; }
      math(list);
    } catch(e) { if (version === state.listVersion) $("theorem-list").textContent = e.message; }
  }
  form.addEventListener("submit", e => { e.preventDefault(); action(form.querySelector("button"), $("theorem-status"), async () => {
    const d = Object.fromEntries(new FormData(form)); for (const key of ["aliases","assumptions","uncertainties"]) d[key] = lines(d[key]);
    for (const key of ["statement_complete","verified_by_user"]) d[key] = form.elements.namedItem(key).checked;
    d.record_id = d.record_id || null; d.expected_revision = d.expected_revision ? Number(d.expected_revision) : null; d.workspace_id = d.record_id ? state.editWorkspace : workspace();
    const result = await api("/research/theorems", d); edit(result); $("theorem-status").textContent = `已保存 Markdown，第 ${result.revision} 版。${result.verified_by_user ? "可在此工作区作为已核对记忆使用。" : "候选不会自动成为 AI 的研究前提。"}`; await refreshTheorems();
  }); });
  $("theorem-new").textContent="关闭更正表单";
  $("theorem-new").onclick = () => { form.reset();form.hidden=true; form.elements.record_id.value = ""; form.elements.expected_revision.value = ""; state.editWorkspace = null; $("theorem-status").textContent = "AI 会继续自动维护记忆。"; };
  $("theorem-refresh").onclick = refreshTheorems;
  let searchTimer; $("theorem-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(refreshTheorems,250); });
  const params = new URLSearchParams(location.search), extension = params.get("extension_id"), nonce = params.get("nonce");
  const setup = location.pathname === "/canvas-setup" && /^[a-p]{32}$/.test(extension || "") && /^[\da-f-]{36}$/.test(nonce || "");
  if (setup) { $("pair-allow").hidden = false; $("pair-scope").hidden = false; $("pair-info").textContent = "扩展申请连接本机 MathPath。点击允许后才会授权。"; }
  async function pairStatus() { const v = await api("/canvas/pair/status"); if (!setup) $("pair-info").textContent = v.connected ? "已与一个伴学扩展配对。" : "尚未配对。"; }
  $("pair-allow").onclick = () => action($("pair-allow"), $("pair-info"), async () => {
    if (!window.chrome?.runtime?.sendMessage) throw Error("请在安装了扩展的 Chrome / Edge 中打开此页，从扩展图标重新发起连接。");
    const value = await api("/canvas/pair", {extension_id:extension});
    const reply = await chrome.runtime.sendMessage(extension, {kind:"pair",nonce,origin:location.origin,token:value.token,expires_at:value.expires_at});
    if (!reply?.ok) throw Error("扩展没有确认连接，请从扩展图标重新发起配对。");
    $("pair-info").textContent = "连接成功。回到回放页，点击 MathPath 伴学即可。"; $("pair-allow").hidden = true;
    window.dispatchEvent(new CustomEvent("mathpath-paired"));
  });
  $("pair-revoke").onclick = () => action($("pair-revoke"), $("pair-info"), async () => { await api("/canvas/pair", null, "DELETE"); $("pair-info").textContent = "已撤销，扩展需重新配对才能使用。"; });
  let saved; try { saved = localStorage.getItem("mathpath-research-workspace"); } catch {}
  loadWorkspaces(saved).catch(() => { $("workspace-status").textContent = "工作区未载入，请检查本机 MathPath 是否运行。"; });
  pairStatus().catch(e => { $("pair-info").textContent = e.message; });
})();
