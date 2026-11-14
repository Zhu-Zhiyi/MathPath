"use strict";
const trustedStorage = chrome.storage.local.setAccessLevel({accessLevel:"TRUSTED_CONTEXTS"});
const routes = Object.freeze({lectures:["GET","lectures"],workspaces:["GET","workspaces"],createWorkspace:["POST","workspaces"],context:["POST","context"],explain:["POST","explain"],ask:["POST","ask"],saveTheorem:["POST","theorems"],explore:["POST","explore"],guidance:["POST","guidance"],notesSettings:["GET","notes/settings"],generateNotes:["POST","notes/generate"]});
const clocks = new Map();
function localOrigin(value) {
  const u = new URL(value);
  if (u.protocol !== "http:" || u.hostname !== "127.0.0.1" || u.username || u.password || u.pathname !== "/" || u.search || u.hash) throw Error("地址须为 http://127.0.0.1:端口");
  return u.origin;
}
function pageSender(sender) {
  if (!sender.tab || typeof sender.frameId !== "number") return false;
  try { const u = new URL(sender.url); return (u.protocol === "https:" && ["oc.sjtu.edu.cn","v.sjtu.edu.cn"].includes(u.hostname)) || (u.protocol === "http:" && u.hostname === "127.0.0.1" && u.pathname === "/canvas-demo"); } catch { return false; }
}
function popupSender(sender) { return sender.url === chrome.runtime.getURL("popup.html"); }
function cleanBody(value) {
  const raw = JSON.stringify(value ?? {}); if (raw.length > 60000) throw Error("片段或问题过长，请缩短。"); return raw;
}
async function connection() {
  await trustedStorage;
  const {connection:c} = await chrome.storage.local.get("connection");
  if (!c || c.expires_at * 1000 <= Date.now()) throw Error("尚未连接 MathPath，请点击浏览器扩展图标连接。");
  return {...c,origin:localOrigin(c.origin)};
}
async function bridge(message) {
  const route = routes[message.action]; if (!route) throw Error("不支持的伴学操作。");
  const c = await connection(), controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 150000);
  try {
    const response = await fetch(c.origin + "/canvas-bridge/" + route[1], {
      method:route[0],credentials:"omit",redirect:"error",signal:controller.signal,
      headers:{"Authorization":"Bearer " + c.token,"X-MathPath-Extension":chrome.runtime.id,...(route[0] === "POST" ? {"Content-Type":"application/json"} : {})},
      ...(route[0] === "POST" ? {body:cleanBody(message.body)} : {})
    });
    if (!response.headers.get("content-type")?.includes("application/json")) throw Error("MathPath 没有返回有效数据，请检查端口。");
    const raw = await response.text(); if (raw.length > 600000) throw Error("返回片段过长。");
    const data = JSON.parse(raw); if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "请求内容有缺项，请核对。"); return data;
  } finally { clearTimeout(timer); }
}
function selectClock(message, sender) {
  const v = message.clock;
  if (!v || typeof v.video_id !== "string" || !/^[\da-f-]{36}$/.test(v.video_id) || !Number.isFinite(v.time) || v.time < 0 || v.time > 10800 || !Number.isFinite(v.area) || v.area < 0 || v.area > 1e9 || typeof v.playing !== "boolean" || typeof v.caption !== "string" || v.caption.length > 8000) throw Error("无效播放状态");
  const id = sender.tab.id, frames = clocks.get(id) || new Map();
  frames.set(sender.frameId,{...v,frame:sender.frameId,seen:Date.now()});
  for (const [key,row] of frames) if (Date.now()-row.seen > 5000) frames.delete(key);
  clocks.set(id,frames); if (clocks.size > 100) clocks.delete(clocks.keys().next().value);
  const candidates = [...frames.values()].filter(r => r.area > 0).sort((a,b) => Number(b.playing)-Number(a.playing) || b.area-a.area);
  const primary = candidates[0] || null;
  chrome.tabs.sendMessage(id,{kind:"primaryClock",clock:primary}).catch(() => {});
  return {primary};
}
chrome.runtime.onMessage.addListener((message,sender,respond) => {
  (async () => {
    if (!popupSender(sender) && !pageSender(sender)) throw Error("伴学消息来源不匹配。");
    if (message.kind === "clock" && pageSender(sender)) return selectClock(message,sender);
    if (message.kind === "bridge" && pageSender(sender)) return {data:await bridge(message)};
    if (message.kind === "status") { try { const c = await connection(); return {connected:true,origin:c.origin,expires_at:c.expires_at}; } catch { return {connected:false}; } }
    if (message.kind === "preparePair" && popupSender(sender)) {
      const origin = localOrigin(message.origin), nonce = crypto.randomUUID();
      await chrome.storage.session.set({pending:{origin,nonce,created:Date.now()}});
      await chrome.tabs.create({url:origin + "/canvas-setup?extension_id=" + chrome.runtime.id + "&nonce=" + nonce});
      return {started:true};
    }
    if (message.kind === "forget" && popupSender(sender)) { await chrome.storage.local.remove("connection"); return {forgotten:true}; }
    if (message.kind === "openWorkbench") { const c = await connection(); await chrome.tabs.create({url:c.origin+"/research-workbench"+(message.section==="notes"?"#notes":"")}); return {opened:true}; }
    throw Error("不支持的伴学操作。");
  })().then(value => respond({ok:true,...value})).catch(error => respond({ok:false,error:error.name === "AbortError" ? "请求超时，请稍后重试。" : error.message === "Failed to fetch" ? "无法连接本机 MathPath，请检查软件与端口。" : error.message}));
  return true;
});
chrome.runtime.onMessageExternal.addListener((message,sender,respond) => {
  (async () => {
    await trustedStorage;
    const {pending:p} = await chrome.storage.session.get("pending");
    if (!p || Date.now()-p.created > 300000 || message.kind !== "pair" || message.nonce !== p.nonce || message.origin !== p.origin) throw Error();
    const u = new URL(sender.url);
    if (u.origin !== p.origin || u.pathname !== "/canvas-setup" || u.searchParams.get("nonce") !== p.nonce || u.searchParams.get("extension_id") !== chrome.runtime.id || sender.frameId !== 0) throw Error();
    if (typeof message.token !== "string" || !/^[\w-]{40,100}$/.test(message.token) || !Number.isFinite(message.expires_at) || message.expires_at*1000 <= Date.now() || message.expires_at*1000 > Date.now()+31*86400000) throw Error();
    await chrome.storage.local.set({connection:{origin:p.origin,token:message.token,expires_at:message.expires_at}});
    await chrome.storage.session.remove("pending"); return {ok:true};
  })().then(respond).catch(() => respond({ok:false,error:"配对已过期或来源不匹配，请重新发起连接。"})); return true;
});
