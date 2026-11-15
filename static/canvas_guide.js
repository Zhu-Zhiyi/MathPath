(() => {
  "use strict";
  const section=document.getElementById("pair-section");if(!section)return;
  const el=(tag,text,parent)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n;};
  const box=el("div");box.className="canvas-guide";section.prepend(box);
  el("h2","第一次连接 Canvas：按这 5 步完成",box);
  const list=el("ol",undefined,box);list.style.paddingLeft="22px";
  const one=el("li",undefined,list);el("strong","保持 MathPath 主程序运行",one);el("p","桌面程序菜单选择“Canvas 伴学设置（在浏览器打开）”，在安装扩展的 Chrome / Edge 中打开此页。",one);
  const address=el("code",location.origin,one),copy=el("button","复制本机地址",one);copy.type="button";copy.className="quiet";copy.onclick=async()=>{try{await navigator.clipboard.writeText(location.origin);copy.textContent="已复制";}catch{copy.textContent="请手动复制左边地址";}};
  const two=el("li",undefined,list);el("strong","安装分享包中的浏览器扩展（只需一次）",two);el("p","Chrome 地址栏输入 chrome://extensions；Edge 输入 edge://extensions。开启“开发者模式”→“加载已解压的扩展程序”→选择分享包里的“Canvas伴学扩展”文件夹。看到 MathPath 卡片且没有报错，再做下一步。",two);
  const three=el("li",undefined,list);el("strong","让扩展连接这台电脑的 MathPath",three);el("p","点击浏览器工具栏的拼图图标 → MathPath。把上面复制的本机地址填进去 → 点击“连接 MathPath”→ 在新打开的本机页面点击“允许这个扩展连接”。此步骤不需要 Canvas 密钥，也不需要把密码交给扩展。",three);
  const four=el("li",undefined,list);el("strong","确认数学模型连接",four);const p=el("p","沿用 MathPath 首页已选择的数学模型。点击生成后自动在本机转写声音、识别抽样板书，再由数学模型整理。无需 Gemini 账号或视频密钥；首次下载约 238 MB 的识别组件。",four);const a=el("a","查看本机识别设置 →",four);a.href="/video-settings";
  const five=el("li",undefined,list);el("strong","回到当前回放，点击“生成解析”",five);el("p","刷新交大 Canvas / 课堂实录回放页 → 右下角“MathPath 伴学”→“生成解析”。默认读取当前主画面的完整视频，从 00:00 到结尾，自动关联、自动显示笔记。不需要另传文件或选时间段。全屏请用“伴学全屏”。",five);
  const status=el("p","正在检查连接…",box);status.setAttribute("role","status");
  const refresh=el("button","检查是否连好",box);refresh.type="button";refresh.className="quiet";
  async function check(){refresh.disabled=true;try{const r=await fetch("/canvas/pair/status",{cache:"no-store"});if(!r.ok)throw Error();const v=await r.json();status.textContent=v.connected?"本机已配对扩展。接下来到回放页刷新，并选择同一节课堂；配对成功不代表已经读到了播放器。":"尚未配对：完成上面的第 2、3 步后，再点击检查。";}catch{status.textContent="无法确认连接，请检查主程序是否保持运行，并使用当前本机地址。";}finally{refresh.disabled=false;}}
  refresh.onclick=check;window.addEventListener("mathpath-paired",check);check();
  const detail=el("details",undefined,box);el("summary","常见情况：我看不到侧栏 / 没有当前内容 / 全屏后消失",detail);
  el("p","看不到侧栏：确认扩展已启用并允许访问 oc.sjtu.edu.cn 和 v.sjtu.edu.cn，然后刷新回放。没有笔记：先点“生成解析”，查看是否缺少视频模型配置或视频读取失败。当前支持可读取的完整 MP4 / WebM；其他播放器会明确提示。全屏后消失：按 Esc，再用“伴学全屏”。已有手动导入的课堂可在侧栏“更多选项”中关联。",detail);
  const demo=el("a","先用本地合成回放试一遍 →",box);demo.href="/canvas-demo";
})();
