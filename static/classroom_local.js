/* The primary lecture flow uses local recognition and the selected text connection. */
(() => {
  "use strict";
  const $=id=>document.getElementById(id);let waiting=false,pending=false;
  function update(){
    const job=currentLecture,active=job&&ACTIVE_STATES.has(job.status);
    $('local-generate').disabled=pending||waiting||!job||active||job.video_available===false;
    $('local-generate').textContent=job?.status==='completed'?'已生成整课解析':job?.completed_chunks?'继续生成解析':'生成解析';
    if(job?.status==='completed')$('local-generate').disabled=true;
    $('local-cancel').hidden=!active;
    $('local-status').textContent=job?.local_processing?.message||job?.error||(active?'正在处理整课；每完成一段即可阅读。':'默认从 00:00 处理到结尾。点击生成后开始本机识别。');
  }
  $('local-generate').onclick=async()=>{
    if(waiting||pending||!currentLecture)return;
    const id=currentLecture.id,version=selectionVersion;waiting=true;let failure="";update();
    try{
      const job=validateLecture(await requestJSON(`/lectures/${id}/analyze-local`,{method:'POST'}));
      if(id===currentLecture?.id&&version===selectionVersion){renderLecture(job);schedulePoll(version);}
    }catch(error){if(id===currentLecture?.id)failure=error.message;}
    finally{waiting=false;update();if(failure)$('local-status').textContent=failure;}
  };
  $('local-cancel').onclick=async()=>{
    const id=currentLecture?.id,version=selectionVersion;if(!id)return;
    try{const job=validateLecture(await requestJSON(`/lectures/${id}/cancel`,{method:'POST'}));if(id===currentLecture?.id&&version===selectionVersion)renderLecture(job);}catch(error){$('local-status').textContent=error.message;}
  };
  window.MathPathLocalVideo={onLecture:update,onPending(value){pending=value;update();}};
  update();
})();
