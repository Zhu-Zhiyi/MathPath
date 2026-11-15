"use strict";
(() => {
  const $=id=>document.getElementById(id);
  async function call(body){const r=await fetch('/settings/video',{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json'}:{},...(body?{body:JSON.stringify(body)}:{})});const v=await r.json();if(!r.ok)throw Error(typeof v.detail==='string'?v.detail:'视频模型设置未完成。');return v;}
  call().then(v=>{$('video-model').value=v.model;$('video-chunk').value=String(v.chunk_seconds);$('video-status').textContent=v.configured?'已配置视频连接。回到回放，点击“生成解析”即可；下方可更换连接。':'首次填写视频模型，保存后即可一键解析整段回放。';}).catch(e=>$('video-status').textContent=e.message);
  $('video-settings-form').onsubmit=async e=>{e.preventDefault();const b=$('video-save');b.disabled=true;try{await call({api_key:$('video-key').value,model:$('video-model').value,chunk_seconds:Number($('video-chunk').value),remote_upload_confirmed:$('video-consent').checked});$('video-key').value='';$('video-status').textContent='已加密保存。现在回到课堂网页，点击 MathPath 侧栏的“生成解析”。';}catch(e){$('video-status').textContent=e.message;}finally{b.disabled=false;}};
})();
