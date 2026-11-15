"""No network or real model calls: evidence, cancellation and provider boundaries."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import local_video as local
import local_video_runtime as runtime
import lecture_store as store
import lecture_provider
from model_settings import GenerationConfig
from test_lectures import analysis, VIDEO

CONFIG = GenerationConfig(provider='api', base_url='https://synthetic.invalid/v1', model='chosen-text-model',
                          api_format='chat_completions', output_mode='json_object', revision='fake-revision', api_key='synthetic-local-secret')


class LocalVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mathpath-local-recognition-',ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'MATHPATH_DATA_DIR':self.tmp.name});self.env.start();self.addCleanup(self.env.stop)
        self.preflight=patch.object(local,'preflight',return_value=CONFIG);self.preflight.start();self.addCleanup(self.preflight.stop)
        self.addCleanup(self.stop)
        self.guards=[]
        for name in ['upload_video','analyze_clip','delete_remote']:
            guard=patch.object(lecture_provider,name,side_effect=AssertionError('Gemini must not be called'))
            guard.start();self.guards.append(guard);self.addCleanup(guard.stop)

    def stop(self):
        store.shutdown_workers()
        deadline=time.monotonic()+5
        while store._active and time.monotonic()<deadline:time.sleep(.01)
        self.assertFalse(store._active)

    def job(self):
        d=store.begin_upload('合成视频.mp4','video/mp4',len(VIDEO),999.)
        (d/'video.part').write_bytes(VIDEO)
        return store.finish_upload(d,'合成视频.mp4','video/mp4',len(VIDEO),hashlib.sha256(VIDEO).hexdigest(),999.)

    def wait(self,job):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            value=store.get_job(job['id'])
            if value['status'] not in store.ACTIVE:return value
            time.sleep(.01)
        self.fail('local test worker did not finish')

    def source(self,paths,directory,index,start,end,cancel):
        return {'pipeline':local.PIPELINE,'start_seconds':start,'end_seconds':end,
                'transcript':[{'start_seconds':start,'end_seconds':end,'text':'合成转写'}],
                'frames':[{'index':index*10,'time_seconds':start,'text':'合成板书','status':'ok','file':'frame-0.jpg'}],
                'warnings':['手写公式需核对。']}

    def run_patches(self,**kwargs):
        values={'ensure':patch.object(runtime,'ensure',return_value={}),
                'duration':patch.object(local,'media_duration',return_value=601.25),
                'source':patch.object(local,'evidence',side_effect=self.source),
                'memory':patch('research_memory.remember_clip',return_value=None),
                'text':patch.object(local,'generate_text',side_effect=lambda prompt,**kw:json.dumps(analysis(json.loads(prompt)['start_seconds'],json.loads(prompt)['end_seconds'])))}
        values.update(kwargs)
        mocks={}
        for key,p in values.items():mocks[key]=p.start();self.addCleanup(p.stop)
        return mocks

    def test_whole_duration_selected_connection_only_text_and_no_secret_on_disk(self):
        mocks=self.run_patches();job=self.job();local.start(job['id']);done=self.wait(job)
        self.assertEqual(done['status'],'completed');self.assertEqual(done['duration_seconds'],601.25)
        self.assertEqual([(c['start_seconds'],c['end_seconds']) for c in done['clips']],[(0.,300.),(300.,600.),(600.,601.25)])
        self.assertEqual(done['processed_seconds'],601.25);self.assertEqual(done['coverage_ratio'],1.)
        for call in mocks['text'].call_args_list:
            self.assertIs(call.kwargs['configuration'],CONFIG)
            payload=json.loads(call.args[0]);self.assertNotIn('frames',payload)
            self.assertNotIn('synthetic-local-secret',call.args[0]);self.assertNotIn('file',payload['ocr'][0])
            self.assertIn('没有观看',call.kwargs['instructions'])
        self.assertNotIn('synthetic-local-secret',(store.job_directory(job['id'])/'metadata.json').read_text(encoding='utf-8'))
        self.assertTrue(done['review_required']);self.assertIn('手写公式需核对。',done['clips'][0]['analysis']['uncertainties'])
        self.assertEqual(mocks['memory'].call_count,3)
        local.start(job['id']);self.assertEqual(mocks['text'].call_count,3,'completed record must never rebill')

    def test_failed_segment_resume_keeps_completed_notes(self):
        n=0
        def text(prompt,**kw):
            nonlocal n
            n+=1
            if n==2:raise local.ModelError('合成额度不足。')
            row=json.loads(prompt);return json.dumps(analysis(row['start_seconds'],row['end_seconds']))
        mocks=self.run_patches(text=patch.object(local,'generate_text',side_effect=text));job=self.job()
        local.start(job['id']);first=self.wait(job);self.assertEqual(first['completed_chunks'],1)
        self.assertEqual(first['status'],'failed');self.assertEqual(first['error'],'合成额度不足。')
        local.start(job['id']);done=self.wait(job);self.assertEqual(done['status'],'completed')
        self.assertEqual(mocks['text'].call_count,4,'one successful first segment must not be regenerated')

    def test_cancelled_recognition_never_sends_to_model(self):
        entered=threading.Event()
        def source(*args):
            entered.set();cancel=args[-1]
            cancel.wait(3);runtime.check(cancel)
        mocks=self.run_patches(source=patch.object(local,'evidence',side_effect=source));job=self.job()
        local.start(job['id']);self.assertTrue(entered.wait(2));store.cancel_analysis(job['id'])
        done=self.wait(job);self.assertEqual(done['status'],'cancelled');self.assertEqual(mocks['text'].call_count,0)

    def test_invalid_model_times_are_rejected(self):
        mocks=self.run_patches(text=patch.object(local,'generate_text',return_value=json.dumps(analysis(900.,950.))))
        job=self.job();local.start(job['id']);done=self.wait(job)
        self.assertEqual(done['status'],'failed');self.assertEqual(done['completed_chunks'],0)

    def test_changing_connection_cannot_mix_existing_notes(self):
        self.run_patches();job=self.job();local.start(job['id']);done=self.wait(job)
        d=store.job_directory(job['id']);done['status']='failed';store._save(d,done)
        with patch.object(local,'preflight',return_value=GenerationConfig(**{**CONFIG.__dict__,'revision':'changed'})):
            with self.assertRaisesRegex(store.LectureError,'原数学模型'):local.start(job['id'])

    def test_transcript_offsets_are_absolute_and_bounded(self):
        result=local.parse_transcript({'transcription':[{'offsets':{'from':0,'to':2500},'text':'核'}]},300.,301.)
        self.assertEqual(result,[{'start_seconds':300.,'end_seconds':301.,'text':'核'}])
        with self.assertRaises(store.LectureError):local.parse_transcript({'transcription':[{'offsets':{'from':float('nan'),'to':1},'text':'x'}]},0.,1.)

    def test_frame_route_has_no_arbitrary_path_access(self):
        job=self.job()
        for number in [-1,1000,'../metadata.json',True]:
            with self.assertRaises(store.LectureError):local.frame_path(job['id'],number)

    def test_component_download_resumes_and_verifies_hash(self):
        raw=b'public-fixture-binary';asset={'url':'https://synthetic.invalid/fixture','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'filename':'fixture.bin'}
        target=Path(self.tmp.name)/'fixture.bin';target.with_name('fixture.bin.part').write_bytes(raw[:6])
        class Response(io.BytesIO):
            status=206
            headers={'Content-Range':f'bytes 6-{len(raw)-1}/{len(raw)}'}
        class Opener:
            def open(self,request,timeout):
                self.assert_range=request.get_header('Range')
                return Response(raw[6:])
        opener=Opener()
        with patch.object(runtime.urllib.request,'build_opener',return_value=opener):runtime.download(asset,target,threading.Event(),lambda _:None)
        self.assertEqual(target.read_bytes(),raw);self.assertEqual(opener.assert_range,f'bytes=6-{len(raw)-1}')

    def test_component_bad_hash_is_never_executed(self):
        class Response(io.BytesIO):
            status=200;headers={}
        class Opener:
            def open(self,*a,**k):return Response(b'bad')
        target=Path(self.tmp.name)/'bad.bin'
        with patch.object(runtime.urllib.request,'build_opener',return_value=Opener()):
            with self.assertRaisesRegex(store.LectureError,'完整性'):runtime.download({'url':'https://synthetic.invalid/f','bytes':3,'sha256':'0'*64,'filename':'bad.bin'},target,threading.Event(),lambda _:None)
        self.assertFalse(target.exists());self.assertFalse(target.with_name('bad.bin.part').exists())


if __name__=='__main__':unittest.main()
