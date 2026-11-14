"use strict";
document.getElementById("make").onclick = async () => {
  const button=document.getElementById("make"),status=document.getElementById("status"),canvas=document.getElementById("canvas"),video=document.getElementById("video");
  button.disabled=true;status.textContent="正在生成本地合成片段，约 6 秒…";
  if(!canvas.captureStream||!window.MediaRecorder){status.textContent="此浏览器不支持生成合成视频。可使用 Chrome / Edge。";button.disabled=false;return;}
  let stream,loop;
  try {
    const ctx=canvas.getContext("2d"),started=performance.now();
    const draw=()=>{const t=(performance.now()-started)/1000;ctx.fillStyle="#183c2d";ctx.fillRect(0,0,960,540);ctx.fillStyle="#e8edcd";ctx.font="32px sans-serif";ctx.fillText("MathPath 合成课堂 · 仅测试",65,90);ctx.font="28px serif";ctx.fillText("T : V → W    dim V = dim ker T + dim im T",65,230);ctx.font="22px sans-serif";ctx.fillText(`合成时间 ${t.toFixed(1)} 秒`,65,360);loop=requestAnimationFrame(draw);};draw();
    stream=canvas.captureStream(12);const chunks=[];const recorder=new MediaRecorder(stream,{mimeType:"video/webm;codecs=vp8"});
    const finished=new Promise((resolve,reject)=>{recorder.ondataavailable=e=>chunks.push(e.data);recorder.onstop=resolve;recorder.onerror=reject;});recorder.start();setTimeout(()=>recorder.stop(),6000);await finished;
    const url=URL.createObjectURL(new Blob(chunks,{type:"video/webm"}));video.src=url;video.addEventListener("emptied",()=>URL.revokeObjectURL(url),{once:true});
    const track=video.addTextTrack("captions","合成字幕","zh");track.mode="showing";track.addCue(new VTTCue(0,3,"设 V 是有限维向量空间，T: V → W 是线性映射。"));track.addCue(new VTTCue(3,7,"秩—零度定理：dim V = dim ker T + dim im T。"));
    status.textContent="合成片段已准备。点视频播放，再点 MathPath 伴学。未关联课堂时可用标准字幕手动测试解释（该按钮会调用模型）。";
  } catch {status.textContent="合成片段未生成，请在 Chrome / Edge 重试。";} finally {cancelAnimationFrame(loop);if(stream)stream.getTracks().forEach(t=>t.stop());button.disabled=false;}
};
