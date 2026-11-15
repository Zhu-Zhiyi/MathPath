/* Read the full currently selected media only after the user's Generate click. */
(() => {
  'use strict';
  const MAX=2*1024**3,CHUNK=256*1024;
  const sourceOf=v=>v?.currentSrc||v?.src||'';
  async function describe(video,title='课堂回放'){
    if(!video||!Number.isFinite(video.duration)||video.duration<=0||video.duration>10800)throw Error('请先载入完整课堂回放；当前支持最长 3 小时的录播。');
    const uri=sourceOf(video);let u;try{u=new URL(uri,location.href);}catch{throw Error('当前播放器尚未提供视频文件，请先点击播放。');}
    if(!['https:','blob:'].includes(u.protocol)&&!(u.protocol==='http:'&&u.hostname==='127.0.0.1'))throw Error('当前视频来源暂不能读取。');
    if(video.mediaKeys)throw Error('当前播放器使用受保护媒体，无法直接解析此视频。');
    // Static recording paths identify the full file independently of expiring signatures.
    const identity=/\.(mp4|webm|mov|m4v)$/i.test(u.pathname)?u.origin+u.pathname:uri;
    const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(identity+'|'+Math.round(video.duration)));
    return{uri,key:[...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join(''),duration:video.duration,title:title.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,130)||'课堂回放'};
  }
  function base64(raw){let s='';for(let i=0;i<raw.length;i+=8192)s+=String.fromCharCode(...raw.subarray(i,i+8192));return btoa(s);}
  async function generate(video,description,api,{signal,progress=()=>{},isCurrent=()=>true,onJob=()=>{}}={}){
    const check=()=>{if(signal?.aborted)throw new DOMException('Cancelled','AbortError');if(!isCurrent()||sourceOf(video)!==description.uri)throw Error('播放器已换到另一段视频，已停止导入旧视频。');};
    check();const old=await api('videoBinding',{source_key:description.key});
    if(old.lecture){onJob(old.lecture);progress('使用已保存的整课记录，无需重复读取。');const job=await api('videoAnalyze',{job_id:old.lecture.id});onJob(job);return job;}
    const config=await api('videoSettings');if(!config.configured)throw Error('首次使用请先点“本机识别与数学模型”。配置一次后，只需点生成解析。');
    let sid=null,reader;
    try{
      progress('正在读取当前完整视频（从 00:00 到结尾）…');
      let response;try{response=await fetch(description.uri,{credentials:'omit',signal,cache:'no-store'});}catch(e){if(signal?.aborted)throw e;throw Error('当前视频文件暂时无法读取。请刷新回放并点播放后重试；分段或受限播放器需适配。');}
      if(response.status!==200||!response.body)throw Error('没有读到完整视频文件，请刷新回放后重试。');
      const size=Number(response.headers.get('content-length'))||null;if(size&&size>MAX)throw Error('视频超过 2 GiB，请使用较短课时。');
      reader=response.body.getReader();let first=await reader.read();
      while(!first.done&&first.value.length<12){check();const more=await reader.read();if(more.done)break;const joined=new Uint8Array(first.value.length+more.value.length);joined.set(first.value);joined.set(more.value,first.value.length);first={done:false,value:joined};}
      if(first.done||first.value.length<12)throw Error('视频文件没有有效内容。');
      const raw=first.value,mp4=String.fromCharCode(...raw.subarray(4,8))==='ftyp',webm=raw[0]===0x1a&&raw[1]===0x45&&raw[2]===0xdf&&raw[3]===0xa3;
      if(!mp4&&!webm)throw Error('当前地址不是可读取的 MP4 / WebM 完整文件，暂未开始模型解析。');
      const mime=mp4?'video/mp4':'video/webm',extension=mp4?'.mp4':'.webm';
      check();const begin=await api('videoImport',{request_id:crypto.randomUUID(),source_key:description.key,filename:description.title+extension,mime_type:mime,duration_seconds:description.duration,size_bytes:size});sid=begin.import_id;
      let offset=0;
      async function send(chunk){for(let i=0;i<chunk.length;i+=CHUNK){check();const part=chunk.subarray(i,i+CHUNK);if(offset+part.length>MAX)throw Error('视频超过 2 GiB，导入已停止。');const r=await api('videoChunk',{import_id:sid,offset,data:base64(part)});offset+=part.length;if(r.offset!==offset)throw Error('视频导入位置不一致，请重新生成。');progress(size?`正在读取整段视频：${Math.min(100,Math.floor(offset*100/size))}%`:`正在读取整段视频：${(offset/1024/1024).toFixed(1)} MB`);}}
      await send(first.value);
      while(true){const part=await reader.read();if(part.done)break;await send(part.value);}
      check();progress('完整视频已读取，正在创建整课解析…');const saved=await api('videoFinish',{import_id:sid});sid=null;onJob(saved);check();
      const job=await api('videoAnalyze',{job_id:saved.id});onJob(job);return job;
    }finally{if(reader)try{await reader.cancel();}catch{}if(sid)try{await api('videoAbort',{import_id:sid});}catch{}}
  }
  globalThis.MathPathDirectVideo={describe,generate,sameSource:(video,description)=>sourceOf(video)===description.uri};
})();
