"use strict";
const $ = id => document.getElementById(id);
async function send(body) { const r = await chrome.runtime.sendMessage(body); if (!r?.ok) throw Error(r?.error || "扩展连接未完成"); return r; }
async function run(id,task) { $(id).disabled = true; try { await task(); } catch(e) { $("status").textContent = e.message; } finally { $(id).disabled = false; } }
$("connect").onclick = () => run("connect",async () => { await send({kind:"preparePair",origin:$("origin").value.trim()}); $("status").textContent = "请在新打开的本机页面点击允许连接。"; });
$("workbench").onclick = () => run("workbench", () => send({kind:"openWorkbench"}));
$("forget").onclick = () => run("forget",async () => { await send({kind:"forget"}); $("status").textContent = "扩展已忘记连接。如需撤销服务端授权，请在 MathPath 的接入设置中撤销。"; });
send({kind:"status"}).then(v => { if (v.origin) $("origin").value = v.origin; $("status").textContent = v.connected ? "已保存连接。服务端是否运行将在回放页检查。" : "尚未连接。"; }).catch(e => { $("status").textContent = e.message; });
