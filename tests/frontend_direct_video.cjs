"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const code=fs.readFileSync(path.join(__dirname,'..','browser-extension','mathpath-canvas','direct_video.js'),'utf8');
const bytes=Buffer.concat([Buffer.from([0,0,0,24]),Buffer.from('ftypisom'),Buffer.alloc(600000,17)]);
function environment({old=null,configured=true,change=false,status=200}={}){
  const calls=[],downloads=[],progress=[],chunks=[];
  const video={currentSrc:'https://live.sjtu.edu.cn/recording.mp4?token=synthetic-secret',duration:2983.5,currentTime:994,mediaKeys:null};
  const context=vm.createContext({crypto:webcrypto,TextEncoder,URL,Uint8Array,Number,DOMException,AbortController,location:{href:'https://v.sjtu.edu.cn/'},btoa:s=>Buffer.from(s,'binary').toString('base64'),fetch:async(url,options)=>{downloads.push({url,options});let i=0;const pieces=[bytes.subarray(0,3),bytes.subarray(3,20),bytes.subarray(20)];return{status,headers:{get:n=>n==='content-length'?String(bytes.length):'video/mp4'},body:{getReader:()=>({read:async()=>i<pieces.length?{done:false,value:pieces[i++]}:{done:true},cancel:async()=>{}})}};}});
  vm.runInContext(code,context);
  const api=async(action,body)=>{calls.push({action,body});if(action==='videoBinding')return{lecture:old};if(action==='videoSettings')return{configured};if(action==='videoImport')return{import_id:'11111111-1111-4111-8111-111111111111',offset:0};if(action==='videoChunk'){chunks.push(Buffer.from(body.data,'base64'));video.currentTime=2000;if(change)video.currentSrc='https://live.sjtu.edu.cn/another.mp4';return{offset:body.offset+chunks.at(-1).length};}if(action==='videoFinish')return{id:'saved',completed_chunks:0};if(action==='videoAnalyze')return{id:old?.id||'saved',status:old?.status||'queued'};if(action==='videoAbort')return{};throw Error(action);};
  return{video,calls,downloads,progress,chunks,api,helper:context.MathPathDirectVideo};
}
async function main(){
  const e=environment();assert.equal(e.downloads.length,0);
  const d=await e.helper.describe(e.video,'合成课堂');assert.equal(d.duration,2983.5);assert.equal(d.key.length,64);assert.equal(e.downloads.length,0,'metadata never fetches video');
  const d2=await e.helper.describe({...e.video,currentSrc:e.video.currentSrc.replace('synthetic-secret','rotated-signature')});assert.equal(d.key,d2.key,'expiring signature rotation keeps the same static recording association');
  await e.helper.generate(e.video,d,e.api,{progress:t=>e.progress.push(t)});
  assert.equal(e.downloads.length,1);assert.equal(e.downloads[0].options.credentials,'omit');assert(!e.downloads[0].options.headers,'no browser/application credentials are attached');
  assert(Buffer.concat(e.chunks).equals(bytes),'all bytes, including fragmented header, arrive from the beginning');assert(e.chunks.every(c=>c.length<=256*1024));
  const meta=e.calls.find(c=>c.action==='videoImport').body;assert.equal(meta.duration_seconds,2983.5);assert(!('time'in meta));assert(!JSON.stringify(e.calls).includes('synthetic-secret'),'signed URL stays in the browser only');
  assert.equal(e.calls.filter(c=>c.action==='videoAnalyze').length,1);assert.equal(e.video.currentTime,2000,'seeking does not change analysis scope or require rewinding');
  const missing=environment({configured:false});await assert.rejects(missing.helper.generate(missing.video,await missing.helper.describe(missing.video),missing.api),/本机识别与数学模型/);assert.equal(missing.downloads.length,0);
  const old=environment({old:{id:'already',status:'completed'}});await old.helper.generate(old.video,await old.helper.describe(old.video),old.api);assert.equal(old.downloads.length,0);assert(!old.calls.some(c=>c.action==='videoImport'));
  const changed=environment({change:true});await assert.rejects(changed.helper.generate(changed.video,await changed.helper.describe(changed.video),changed.api),/另一段视频/);assert(changed.calls.some(c=>c.action==='videoAbort'));assert(!changed.calls.some(c=>c.action==='videoAnalyze'));
  const partial=environment({status:206});await assert.rejects(partial.helper.generate(partial.video,await partial.helper.describe(partial.video),partial.api),/完整视频/);assert(!partial.calls.some(c=>c.action==='videoImport'));
  const cancelled=environment(),controller=new AbortController();controller.abort();await assert.rejects(cancelled.helper.generate(cancelled.video,await cancelled.helper.describe(cancelled.video),cancelled.api,{signal:controller.signal}),e=>e.name==='AbortError');assert.equal(cancelled.downloads.length,0);
  console.log('PASS direct full video: click-only fetch, entire bytes/range, fragmented header, bounded chunks, seeking, dedup binding, missing settings, source change/cancel, partial-response refusal and no signed URL or cookies in local requests.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
