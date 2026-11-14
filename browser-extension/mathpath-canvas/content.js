(() => {
  "use strict";
  if (location.protocol === "http:" && (location.hostname !== "127.0.0.1" || location.pathname !== "/canvas-demo")) return;
  const videoIds = new WeakMap();
  const state = {video:null,videoId:null,clock:null,frame:null,open:false,epoch:0,contextVersion:0,contextKey:"",context:null,explanation:null,memoryDraft:null,turns:[],workspaces:[],captionRing:[],lastTime:0,lastSync:0,syncing:false,full:null};
  const host = document.createElement("div"); host.setAttribute("data-mathpath-companion", "");
  host.style.setProperty("position","fixed","important"); host.style.setProperty("z-index","2147483647","important");
  document.documentElement.append(host);
  const root = host.attachShadow({mode:"closed"});
  root.innerHTML = `<link rel="stylesheet" href="${chrome.runtime.getURL("panel.css")}"><link rel="stylesheet" href="${chrome.runtime.getURL("vendor/katex/katex.min.css")}">
  <button class="launcher" id="launch">MathPath 伴学</button>
  <aside class="panel" id="panel" aria-label="MathPath 回放伴学" hidden>
    <div class="head"><strong>MathPath 伴学</strong><button id="fullscreen">伴学全屏</button><button id="close" class="close" aria-label="收起侧栏">×</button></div>
    <div class="body"><p class="meta">按回放时间定位已有解析；补充解释与提问使用本机 MathPath 模型。</p><p id="status" role="status" class="status"></p>
    <details open><summary>开始：研究起点与课堂</summary>
      <label>研究背景（可选）<select id="workspace"><option value="">本次只学习</option></select></label>
      <button id="guidance" class="quiet">研究指引（调用模型）</button><button id="workbench" class="quiet">定理 / 科研工作台</button>
      <div id="guidance-result" class="result"></div>
      <details><summary>先说明我的问题 / 学习意向</summary><form id="workspace-form"><label>名称<input name="title" maxlength="180" required></label><label>意向<select name="intent"><option value="question">已有研究问题</option><option value="explore">学习后探索选题</option><option value="study">只学习</option></select></label><label>具体问题<textarea name="question" rows="3" maxlength="4000"></textarea></label><label>已有基础<textarea name="background" rows="2" maxlength="3000"></textarea></label><label>公开文献关键词（英文）<input name="search_terms" maxlength="200"></label><button>保存起点</button><p class="meta">仅在你点击模型指引、解释或提问时，所选背景随请求发送给当前模型。</p></form></details>
      <label>关联对应的课堂解析<select id="lecture"><option value="">未关联，用当前字幕 / 手动文字</option></select></label><button id="refresh" class="quiet">刷新课堂与工作区</button>
      <p class="meta">请确认是同一节回放。解析含缺段时会明确显示；首次需在 MathPath 的课堂解析页上传并解析对应视频。</p>
      <div class="row"><label>时间偏移（秒）<input id="offset" type="number" value="0" min="-10800" max="10800" step="1"></label><label>手动时间（无视频时）<input id="manual-time" type="number" value="0" min="0" max="10800" step="1"></label></div>
    </details>
    <div class="clock"><span id="clock" class="meta">正在检测视频…</span><h2 id="current-title">等待选择课堂或字幕</h2><div id="current-source" class="result"></div></div>
    <details><summary>补充当前字幕 / 题目文字</summary><textarea id="caption" maxlength="8000" rows="4" placeholder="没有标准字幕轨道时，可粘贴当前片段。不会读取登录信息或视频地址。"></textarea><p class="meta">自动字幕仅来自播放器标准字幕轨道，网站自定义字幕可能无法读取。文字可能有数学错误，请核对。</p></details>
    <button id="explain">解释当前片段（调用模型）</button><span class="badge">AI 辅助 · 需核对</span><p class="meta">AI 会主动整理并保存定理记忆，无需你逐条选择。待核对内容保留标记。</p><div id="explanation" class="result"></div>
    <details><summary>同时保存对应笔记（可选）</summary><label class="check"><input id="note-enabled" type="checkbox">解释完成后生成笔记（另调用当前模型）</label><label>类型<select id="note-type"><option value="A">Type A · 系统学习 / 证明附录双链</option><option value="B">Type B · 问题与答案</option><option value="C">Type C · 讲课笔记</option></select></label><label>内容日期<input id="note-date" type="date"></label><p id="note-directory" class="meta">保存目录在本机工作台设置。</p><button id="note-settings" type="button" class="quiet">选择保存位置 / 分类</button><p id="note-status" class="status" role="status"></p></details>
    <details id="memory-editor"><summary>把这个定理记成 Markdown</summary><form id="theorem-form"><label>定理名称<input name="name" maxlength="180" required></label><label>类别<select name="category"><option value="nonstandard">非标准 / 暂不能确定</option><option value="common">常见教材定理</option></select></label><label>完整陈述与版本<textarea name="statement" maxlength="16000" rows="5" required></textarea></label><label>假设（每行一个）<textarea name="assumptions" rows="3"></textarea></label><label>来源（课堂与时间 / 书籍章节）<input name="source" maxlength="4000" required></label><label>尚需核对（每行一个）<textarea name="uncertainties" rows="2"></textarea></label><label class="check"><input type="checkbox" name="statement_complete">已检查陈述完整</label><label class="check"><input type="checkbox" name="verified_by_user">我已对照来源核对，且没有疑问</label><button>保存定理记忆</button><p id="memory-status" class="status" role="status"></p></form></details>
    <h2>围绕这一段提问</h2><p class="meta">随问题发送所选研究背景、当前片段和此窗口最近 6 轮问答。切换课堂或背景会清空近期问答。</p><div id="turns"></div><form id="ask-form"><label>你的问题<textarea id="question" rows="3" maxlength="4000" required placeholder="这一步为什么成立？这个条件可不可以去掉？"></textarea></label><button>发送问题（调用模型）</button></form>
    <details class="end" id="end-section"><summary>学完之后：近期方向 / 小课题</summary><p class="meta">检索近两年新提交的 arXiv 论文，只发送下面的公开关键词。模型可再根据标题摘要给出初步线索，仍需阅读全文与查新。</p><form id="explore-form"><label>公开检索词<input id="terms" maxlength="200" required placeholder="persistent homology"></label><label class="check"><input id="use-model" type="checkbox">请模型结合所选背景整理研究线索</label><button>查看近期方向</button></form><div id="directions" class="result"></div></details>
    </div></aside>`;
  const $ = id => root.getElementById(id);
  const dateNow=new Date();$("note-date").value=[dateNow.getFullYear(),String(dateNow.getMonth()+1).padStart(2,"0"),String(dateNow.getDate()).padStart(2,"0")].join("-");
  $("memory-editor").querySelector("summary").textContent="查看或更正 AI 记忆（无需逐条保存）";
  const el = (tag,text,parent) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (parent) parent.append(n); return n; };
  const math = node => { if (typeof renderMathInElement === "function") renderMathInElement(node,{delimiters:[{left:"$$",right:"$$",display:true},{left:"\\[",right:"\\]",display:true},{left:"\\(",right:"\\)",display:false},{left:"$",right:"$",display:false}],throwOnError:false,trust:false,strict:"warn"}); };
  const timestamp = value => { const s = Math.max(0,Math.floor(value || 0)); return `${Math.floor(s/60).toString().padStart(2,"0")}:${(s%60).toString().padStart(2,"0")}`; };
  const splitLines = s => s.split(/\r?\n/).map(t => t.trim()).filter(Boolean);
  async function send(message) { const r = await chrome.runtime.sendMessage(message); if (!r?.ok) throw Error(r?.error || "伴学请求未完成。"); return r; }
  const api = (action,body) => send({kind:"bridge",action,body}).then(r => r.data);
  function status(text) { $("status").textContent = text; }
  function frame() {
    const time = state.video ? state.video.currentTime : Number($("manual-time").value);
    const offset = Number($("offset").value);
    if (!Number.isFinite(time) || !Number.isFinite(offset) || time < 0 || time > 10800 || Math.abs(offset) > 10800) throw Error("时间或偏移超出范围，请检查。");
    return {time,offset,lecture_id:$("lecture").value || null,workspace_id:$("workspace").value || null,caption:$("caption").value || state.clock?.caption || ""};
  }
  function resetContext() {
    state.epoch++; state.contextVersion++; state.contextKey = ""; state.context = null; state.explanation = null; state.memoryDraft=null; state.turns = [];
    $("explanation").replaceChildren(); $("turns").replaceChildren(); $("guidance-result").replaceChildren(); $("directions").replaceChildren();
    $("theorem-form").reset(); $("memory-status").textContent = ""; state.lastSync = 0;
  }
  function renderSource(value) {
    $("clock").textContent = `回放 ${timestamp(state.video?.currentTime ?? Number($("manual-time").value))} → 解析 ${timestamp(value.source_time)}${value.source_time < 0 ? "（偏移后为负）" : ""}`;
    $("current-title").textContent = value.items.length ? value.items.map(r => r.title).join(" / ") : value.caption ? "当前字幕 / 手动片段" : "此处没有已解析内容";
    const out = $("current-source"); out.replaceChildren();
    for (const item of value.items) { el("p",`${timestamp(item.start_seconds)}—${timestamp(item.end_seconds)} · ${item.kind}`,out).className = "meta"; el("p",item.source_summary,out); if (item.uncertainties?.length) el("p","课堂解析疑问："+item.uncertainties.join("；"),out).className="status"; }
    if (!value.items.length) el("p",value.caption || "请关联已解析课堂、校准时间，或补充当前字幕。空缺时不会将相邻片段冒充为当前内容。",out);
    math(out);
  }
  async function sync() {
    if (!state.open || state.syncing || Date.now()-state.lastSync < 1800) return;
    state.syncing = true; state.lastSync = Date.now(); const version = ++state.contextVersion, epoch = state.epoch;
    try { const payload = frame(), value = await api("context",payload);
      if (version !== state.contextVersion || epoch !== state.epoch) return;
      state.context = value; renderSource(value);
      const key = JSON.stringify({lecture:payload.lecture_id,workspace:payload.workspace_id,items:value.items.map(r => [r.id,r.start_seconds,r.end_seconds]),caption:value.items.length ? "" : value.caption});
      if (key !== state.contextKey) { state.contextKey = key; state.explanation = null; $("explanation").replaceChildren(); }
    } catch(e) { if (epoch === state.epoch) status(e.message); } finally { state.syncing = false; }
  }
  function diagram(value,parent) {
    if (!value || !Array.isArray(value.elements)) return;
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns,"svg"); svg.setAttribute("viewBox","0 0 640 360"); svg.setAttribute("role","img"); svg.setAttribute("aria-label",value.alt);
    const colors = {ink:"#254236",green:"#34875d",blue:"#427daf",muted:"#829087"};
    const markerId="mp-arrow-"+crypto.randomUUID(),defs=document.createElementNS(ns,"defs"),marker=document.createElementNS(ns,"marker"),tip=document.createElementNS(ns,"path");
    for(const [k,v]of Object.entries({id:markerId,viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:6,markerHeight:6,orient:"auto-start-reverse"}))marker.setAttribute(k,String(v));
    tip.setAttribute("d","M 0 0 L 10 5 L 0 10 z");tip.setAttribute("fill","context-stroke");marker.append(tip);defs.append(marker);svg.append(defs);
    for (const d of value.elements.slice(0,60)) {
      let shape; const attrs = {}, color = colors[d.tone] || colors.ink;
      if (d.type === "line") { shape="line"; for (const k of ["x1","y1","x2","y2"]) attrs[k]=d[k]; attrs["stroke-dasharray"] = d.dashed ? "7 5" : "none"; if(d.arrow)attrs["marker-end"]="url(#"+markerId+")"; }
      else if (d.type === "circle") { shape="circle"; for (const k of ["cx","cy","r"]) attrs[k]=d[k]; }
      else if (d.type === "polygon" && Array.isArray(d.points) && d.points.every(p => Array.isArray(p) && p.length===2 && p.every(Number.isFinite))) { shape="polygon"; attrs.points=d.points.map(p => p.join(",")).join(" "); }
      else if (d.type === "text") { shape="text"; attrs.x=d.x; attrs.y=d.y; attrs["text-anchor"]=["start","middle","end"].includes(d.anchor)?d.anchor:"start"; attrs["font-size"]=18; }
      else continue;
      if (Object.values(attrs).some(v => typeof v === "number" && !Number.isFinite(v))) continue;
      const n = document.createElementNS(ns,shape); for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,String(v));
      n.setAttribute("stroke",shape === "text" ? "none" : color); n.setAttribute("stroke-width","2.5"); n.setAttribute("fill",shape === "text" || d.fill ? color : "none"); if (d.fill && shape!=="text") n.setAttribute("fill-opacity","0.12"); if (shape === "text") n.textContent=d.text; svg.append(n);
    }
    el("h3",value.title,parent); parent.append(svg); el("p","辅助示意（非原板书）："+value.caption,parent).className="meta";
  }
  function renderExplanation(value) {
    state.memoryDraft=value;
    const out = $("explanation"); out.replaceChildren(); el("p",`在 ${timestamp(value.source_time)} 的 AI 辅助解释 · 需核对`,out).className="meta";
    el("h2",value.name,out); el("p",value.statement,out); el("h3","采用的条件",out); const list = el("ul",undefined,out); value.assumptions.forEach(s=>el("li",s,list));
    el("h3","几何 / 结构直观",out); el("p",value.intuition,out); diagram(value.diagram,out);
    el("h3","证明思路（待核对）",out); const steps = el("ol",undefined,out); value.proof_steps.forEach(s=>el("li",s,steps));
    el("p","先修："+value.prerequisites.join("；"),out); el("p","可以检验："+value.questions.join("；"),out);
    if (value.uncertainties.length) el("p","仍需核对："+value.uncertainties.join("；"),out).className="status"; math(out);
    const f = $("theorem-form"); f.reset(); f.elements.name.value=value.name; f.elements.statement.value=value.statement; f.elements.assumptions.value=value.assumptions.join("\n"); f.elements.uncertainties.value=value.uncertainties.join("\n"); f.elements.source.value=`${state.context?.lecture_name || "当前字幕 / 手动片段"}，${timestamp(value.source_time)}；MathPath 辅助解释，需核对原文`;
  }
  async function run(button,task,area=$("status")) { button.disabled=true; area.textContent="正在处理…"; try { await task(); } catch(e) { area.textContent=e.message; } finally { button.disabled=false; } }
  $("explain").onclick = () => { const epoch=state.epoch,key=state.contextKey,payload=frame();
    const notes={enabled:$("note-enabled").checked,type:$("note-type").value,date:$("note-date").value,revision:state.noteConfig?.revision||null};
    run($("explain"),async () => { const value = await api("explain",payload); if(epoch!==state.epoch || key!==state.contextKey) { status("片段已变化，旧解释未放入当前内容。可暂停后重新解释。"); return; } state.explanation=value; renderExplanation(value); status("解释完成，请核对条件与来源。"+(value.memory?.message||"")); if(notes.enabled)await saveNotes(value,payload,notes); });
  };
  async function saveNotes(value,payload,options){
    $("note-status").textContent="正在生成并保存对应笔记…";
    try{const body={enabled:true,note_type:options.type,content_date:options.date,category:"auto",source_kind:"text",source_title:value.name,source_text:JSON.stringify({explanation:value,caption:payload.caption,source_time:value.source_time}),workspace_id:payload.workspace_id,make_pdf:true,sync:false,settings_revision:options.revision};state.noteRequests??=new Map();const key=JSON.stringify(body);if(!state.noteRequests.has(key)){if(state.noteRequests.size>=20)state.noteRequests.delete(state.noteRequests.keys().next().value);state.noteRequests.set(key,crypto.randomUUID());}const r=await api("generateNotes",{...body,request_id:state.noteRequests.get(key)});$("note-status").textContent=Object.values(r.paths).join("\n")+"\n"+(r.pdf.message||"PDF 已生成并检查链接。")+"\n"+r.memory.message;}catch(e){$("note-status").textContent="解释已保留，笔记未完成："+e.message;}
  }
  $("ask-form").onsubmit = e => { e.preventDefault(); const epoch=state.epoch,payload=frame(),question=$("question").value;
    run(e.currentTarget.querySelector("button"),async () => { const result=await api("ask",{...payload,question,turns:state.turns.slice(-6)}); if(epoch!==state.epoch) return;
      const box=el("article",undefined,$("turns")); box.className="turn"; el("p",`${timestamp(result.source_time)} · ${question}`,box).className="question"; el("p",result.answer,box); if(result.uncertainties.length)el("p","待核对："+result.uncertainties.join("；"),box).className="status"; math(box);
      state.turns.push({question,answer:result.answer.slice(0,6000)}); state.turns=state.turns.slice(-6); while($("turns").children.length>6)$("turns").firstElementChild.remove(); if($("question").value===question)$("question").value=""; status("已回答。AI 辅助内容需核对，问答暂存在此窗口，刷新会清空。"); });
  };
  $("theorem-form").onsubmit = e => { e.preventDefault(); const f=e.currentTarget,epoch=state.epoch,value=state.memoryDraft;
    const body={name:f.elements.name.value,category:f.elements.category.value,statement:f.elements.statement.value,assumptions:splitLines(f.elements.assumptions.value),source:f.elements.source.value,uncertainties:splitLines(f.elements.uncertainties.value),statement_complete:f.elements.statement_complete.checked,verified_by_user:f.elements.verified_by_user.checked,workspace_id:$("workspace").value||null,intuition:value?.intuition||"",proof_idea:value?.proof_steps.join("\n")||""};
    run(f.querySelector("button"),async () => { const r=await api("saveTheorem",body); if(epoch===state.epoch)$("memory-status").textContent=`已存为 ${r.name} 的 Markdown 记忆。${r.verified_by_user?"已由用户核对":"候选，需继续核对"}。`; },$("memory-status"));
  };
  async function options() {
    const epoch=state.epoch,lecture=$("lecture").value,workspace=$("workspace").value;
    const results=await Promise.allSettled([api("lectures"),api("workspaces"),api("notesSettings")]);
    if(epoch!==state.epoch)return;
    if(results[0].status==="fulfilled"){const s=$("lecture");s.replaceChildren();const o=el("option","未关联，用字幕 / 手动文字",s);o.value="";for(const j of results[0].value){const n=el("option",`${j.filename} · ${j.completed_chunks} 段已解析`,s);n.value=j.id;}if([...s.options].some(o=>o.value===lecture))s.value=lecture;}
    if(results[1].status==="fulfilled"){state.workspaces=results[1].value;const s=$("workspace");s.replaceChildren();const o=el("option","本次只学习",s);o.value="";for(const w of state.workspaces){const n=el("option",w.title,s);n.value=w.id;}if(state.workspaces.some(w=>w.id===workspace))s.value=workspace;}
    if(results[2].status==="fulfilled"){state.noteConfig=results[2].value;$("note-directory").textContent="笔记根目录："+results[2].value.directory+"；AI 按内容分类，Type C 单独存放。";}
    const failed=results.slice(0,2).find(r=>r.status==="rejected");if(failed)status(failed.reason.message);else status("已连接。请选择对应课堂，核对时间偏移。定理记忆会自动整理。");
  }
  $("refresh").onclick=()=>run($("refresh"),options);
  $("workspace").onchange=()=>{resetContext();const w=state.workspaces.find(w=>w.id===$("workspace").value);$("terms").value=w?.search_terms||"";$("end-section").open=w?.intent==="explore";sync();};
  $("lecture").onchange=()=>{resetContext();sync();};$("offset").onchange=()=>{resetContext();sync();};$("manual-time").onchange=()=>{state.epoch++;state.lastSync=0;sync();};
  let captionTimer;$("caption").addEventListener("input",()=>{state.epoch++;clearTimeout(captionTimer);captionTimer=setTimeout(()=>{state.lastSync=0;sync();},400);});
  $("workspace-form").onsubmit=e=>{e.preventDefault();const f=e.currentTarget;run(f.querySelector("button"),async()=>{const w=await api("createWorkspace",Object.fromEntries(new FormData(f)));await options();$("workspace").value=w.id;$("workspace").dispatchEvent(new Event("change"));status("研究起点已保存；点击研究指引才会调用模型。");});};
  $("guidance").onclick=()=>{const payload=frame(),epoch=state.epoch;if(!payload.workspace_id){status("请先选择或创建研究工作区。");return;}run($("guidance"),async()=>{const r=await api("guidance",payload);if(epoch!==state.epoch)return;$("guidance-result").textContent=r.answer+"\n待核对："+r.uncertainties.join("；");math($("guidance-result"));status("初步研究指引已返回，尚需查新与核对。");});};
  $("workbench").onclick=()=>send({kind:"openWorkbench"}).catch(e=>status(e.message));
  $("note-settings").onclick=()=>send({kind:"openWorkbench",section:"notes"}).catch(e=>status(e.message));
  $("explore-form").onsubmit=e=>{e.preventDefault();const epoch=state.epoch;run(e.currentTarget.querySelector("button"),async()=>{const result=await api("explore",{terms:$("terms").value,workspace_id:$("workspace").value||null,use_model:$("use-model").checked});if(epoch!==state.epoch)return;const out=$("directions");out.replaceChildren();
    for(const d of result.directions){el("h3",d.title,out);el("p",d.why,out);el("p","第一步："+d.first_step,out);el("p","先修："+d.prerequisites.join("；"),out);el("p","论文："+d.paper_ids.join("、"),out);}
    for(const paper of result.papers){const box=el("article",undefined,out);box.className="paper";if(/^https:\/\/arxiv\.org\/abs\/[a-zA-Z\d./-]+$/.test(paper.url)){const a=el("a",paper.title,box);a.href=paper.url;a.target="_blank";a.rel="noopener noreferrer";}el("p",`首次提交 ${paper.published.slice(0,10)} · ${paper.id}`,box).className="meta";const detail=el("details",undefined,box);el("summary","摘要",detail);el("p",paper.abstract,detail);}
    el("p",result.papers.length?`检索于 ${result.retrieved_at.slice(0,10)}`:"没有匹配的近两年论文，请换用更短的英文关键词。",out);el("p",result.caveats.join("；"),out);math(out);status("近期线索已返回；不是已经验证的新课题。");});};
  function restoreFull() {
    const full=state.full;if(!full)return;state.full=null;
    const {video,parent,next,wrapper,style,controls}=full,time=video.currentTime,playing=!video.paused;
    state.movingUntil=Date.now()+500;
    if(parent.isConnected)parent.insertBefore(video,next?.parentNode===parent?next:null);else document.body.append(video);
    if(style===null)video.removeAttribute("style");else video.setAttribute("style",style);
    video.controls=controls;try{if(Math.abs(video.currentTime-time)>1)video.currentTime=time;}catch{}if(playing)video.play().catch(()=>{});
    document.documentElement.append(host);wrapper.remove();$("panel").classList.remove("full");$("fullscreen").textContent="伴学全屏";
  }
  $("fullscreen").onclick=()=>{
    if(document.fullscreenElement){document.exitFullscreen().catch(e=>status("请按 Esc 退出当前全屏后，再点伴学全屏。"));return;}
    if(!state.video){status("尚未检测到可控制的视频。可以使用浏览器 F11 全屏或手动时间。");return;}
    const video=state.video,parent=video.parentNode,next=video.nextSibling,style=video.getAttribute("style"),controls=video.controls,time=video.currentTime,playing=!video.paused;
    const wrapper=document.createElement("div");wrapper.style.cssText="position:fixed;inset:0;background:#101b15;z-index:2147483647";document.documentElement.append(wrapper);
    state.full={video,parent,next,style,controls,time,playing,wrapper};state.movingUntil=Date.now()+500;wrapper.append(video,host);video.controls=true;try{if(Math.abs(video.currentTime-time)>1)video.currentTime=time;}catch{}if(playing)video.play().catch(()=>{});
    video.style.cssText="position:absolute!important;left:0!important;top:0!important;width:calc(100% - min(404px, 46vw))!important;height:100%!important;object-fit:contain!important;max-width:none!important;max-height:none!important;margin:0!important;transform:none!important";
    $("panel").classList.add("full");
    wrapper.requestFullscreen().then(()=>{$("fullscreen").textContent="退出全屏";status("伴学全屏已开启，使用视频下方控制条播放或跳转。按 Esc 恢复原播放器。");}).catch(()=>{restoreFull();status("此播放器框架未允许网页全屏。请使用浏览器 F11，或在独立课堂实录页打开；视频原生全屏不能显示网页侧栏。");});
  };
  document.addEventListener("fullscreenchange",()=>{if(!document.fullscreenElement)restoreFull();else if(document.fullscreenElement.tagName==="VIDEO")status("这是视频原生全屏。请按 Esc 后使用 MathPath 的伴学全屏，才能显示侧栏。");});
  $("launch").onclick=()=>{state.open=true;$("panel").hidden=false;$("launch").hidden=true;options();state.lastSync=0;sync();};
  $("close").onclick=()=>{if(state.full)document.exitFullscreen().catch(()=>restoreFull());state.open=false;$("panel").hidden=true;$("launch").hidden=false;};
  function captions(video) {
    const time=video.currentTime;
    if(Math.abs(time-state.lastTime)>5)state.captionRing=[];
    try{for(const track of video.textTracks)for(const cue of track.activeCues||[]){const text=String(cue.text||"").slice(0,4000);if(text&&!state.captionRing.some(c=>c.text===text&&c.start===cue.startTime))state.captionRing.push({text,start:cue.startTime,end:cue.endTime});}}catch{}
    state.captionRing=state.captionRing.filter(c=>c.start<=time+1&&c.end>=time-45).slice(-25);state.lastTime=time;return state.captionRing.map(c=>c.text).join("\n").slice(-8000);
  }
  const fallbackId=crypto.randomUUID();
  function seeked(){state.epoch++;state.contextVersion++;state.captionRing=[];state.lastSync=0;state.explanation=null;$("explanation").replaceChildren();sync();}
  function mediaChanged(){
    if(Date.now()<(state.movingUntil||0)||!state.video)return;
    state.videoId=crypto.randomUUID();videoIds.set(state.video,state.videoId);state.clock=null;state.captionRing=[];state.lastTime=0;
    $("lecture").value="";resetContext();status("播放器载入了新媒体。请确认是哪节回放，再重新关联课堂；已清空旧问答。");sync();
  }
  async function tick() {
    const videos=[...document.querySelectorAll("video")].map(v=>{const r=v.getBoundingClientRect(),s=getComputedStyle(v);return{v,area:s.display!=="none"&&s.visibility!=="hidden"?Math.max(0,Math.min(r.right,innerWidth)-Math.max(r.left,0))*Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,0)):0};}).filter(x=>x.area>0).sort((a,b)=>Number(!b.v.paused)-Number(!a.v.paused)||b.area-a.area);
    const chosen=videos[0];
    if((chosen?.v||null)!==state.video){if(state.video){state.video.removeEventListener("seeked",seeked);state.video.removeEventListener("loadstart",mediaChanged);}state.video=chosen?.v||null;state.clock=null;state.captionRing=[];state.lastTime=0;resetContext();if(state.video&&!videoIds.has(state.video))videoIds.set(state.video,crypto.randomUUID());state.videoId=state.video?videoIds.get(state.video):null;if(state.video){state.video.addEventListener("seeked",seeked);state.video.addEventListener("loadstart",mediaChanged);}}
    $("manual-time").disabled=!!state.video;
    if(state.video&&Number.isFinite(state.video.currentTime)&&state.video.currentTime<=10800){const time=state.video.currentTime;if(Math.abs(time-state.lastTime)>5){state.epoch++;state.lastSync=0;}state.clock={video_id:state.videoId,time,area:chosen.area,playing:!state.video.paused,caption:captions(state.video)};
      try{const r=await send({kind:"clock",clock:state.clock});applyPrimary(r.primary);}catch(e){if(state.open)status(e.message);}}
    else {$("clock").textContent="未检测到可访问的视频。可手动设时间；播放器可能位于未授权的跨域框架。";try{const r=await send({kind:"clock",clock:{video_id:fallbackId,time:0,area:0,playing:false,caption:""}});applyPrimary(r.primary);}catch{}}
    sync();
  }
  function applyPrimary(clock){host.hidden=clock?clock.video_id!==state.videoId:!state.video&&window.top!==window;}
  chrome.runtime.onMessage.addListener(message=>{if(message?.kind==="primaryClock")applyPrimary(message.clock);});
  setInterval(tick,1000);tick();
})();
