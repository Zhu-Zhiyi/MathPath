"use strict";
(() => {
  const $=id=>document.getElementById(id);
  // Reading settings never downloads tools or starts a model request.
  async function refresh(){
    try{
      const response=await fetch('/settings/video',{cache:'no-store',credentials:'same-origin'});
      const value=await response.json();
      if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'暂时无法读取识别设置。');
      $('video-status').textContent=value.configured?'已选择数学模型。回到回放，点击“生成解析”即可。':'请先在 MathPath 首页连接数学模型，然后直接生成整课解析。';
      $('video-runtime').textContent=value.runtime.ready?'本机识别组件已下载；开始任务时会再次校验完整性。':`首次生成将准备 ${Math.ceil(value.runtime.download_bytes/1000000)} MB 的识别组件，过程中显示下载进度。`;
      $('video-model').textContent=`笔记整理使用：${value.provider==='chatgpt'?'ChatGPT 登录连接':'自定义 API'} · ${value.model}。本页不会更换你的模型或读取视频服务密钥。`;
    }catch(error){$('video-status').textContent=error.message;}
  }
  refresh();
})();
