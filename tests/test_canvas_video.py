"""Full-video ingestion is local and explicit; all model operations are mocked."""
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import main
import canvas_video as video
import lecture_store as store
import canvas_companion as companion
import local_video
from model_settings import GenerationConfig

RAW=b'\x00\x00\x00\x18ftypisom'+b'synthetic-video'*50


class CanvasVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mathpath-full-video-',ignore_cleanup_errors=True);self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'MATHPATH_DATA_DIR':self.tmp.name});self.env.start();self.addCleanup(self.env.stop)
        self.preflight=patch.object(local_video,'preflight',return_value=GenerationConfig(provider='api',base_url='https://synthetic.invalid/v1',model='synthetic',api_format='chat_completions',output_mode='json_object',revision='synthetic',api_key='synthetic-local-key'))
        self.preflight.start();self.addCleanup(self.preflight.stop)
        self.client=TestClient(main.app,base_url='http://127.0.0.1');self.addCleanup(self.client.close)
        self.addCleanup(lambda:video.imports.clear())
        p=self.client.post('/canvas/pair',json={'extension_id':'a'*32}).json()
        self.headers={'Authorization':'Bearer '+p['token'],'X-MathPath-Extension':'a'*32,'Origin':'chrome-extension://'+'a'*32}

    def config(self):
        return self.client.post('/settings/video',json={'api_key':'synthetic-video-key','model':'gemini-synthetic','chunk_seconds':300,'remote_upload_confirmed':True})

    def begin(self,**kw):
        self.config()
        body={'request_id':str(uuid4()),'source_key':'b'*64,'filename':'合成课堂.mp4','mime_type':'video/mp4','duration_seconds':601.25,'size_bytes':len(RAW),**kw}
        r=self.client.post('/canvas-bridge/video-imports',json=body,headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);return r.json()['import_id'],body

    def chunk(self,sid,offset,raw):return self.client.post(f'/canvas-bridge/video-imports/{sid}/chunks?offset={offset}',content=raw,headers=self.headers)
    def finish(self,sid):return self.client.post(f'/canvas-bridge/video-imports/{sid}/finish',headers=self.headers)

    def test_settings_once_encrypted_and_no_model_call(self):
        with patch.object(store,'start_analysis',side_effect=AssertionError('must not start')):
            self.assertFalse(self.client.get('/settings/video').json()['configured'])
            r=self.config();self.assertEqual(r.status_code,200);self.assertNotIn('api_key',r.json())
            self.assertNotIn(b'synthetic-video-key',(video.root()/'connection.dpapi').read_bytes())
            public=self.client.get('/canvas-bridge/video-settings',headers=self.headers).json()
            self.assertTrue(public['local']);self.assertNotIn('api_key',public)
            self.assertEqual(video.credentials()[1],'synthetic-video-key')

    def test_settings_reject_no_consent_and_foreign_origin(self):
        r=self.client.post('/settings/video',json={'api_key':'synthetic-video-key'});self.assertEqual(r.status_code,422)
        self.assertEqual(self.client.get('/settings/video',headers={'Origin':'https://foreign.invalid'}).status_code,403)
        self.assertEqual(self.client.get('/canvas-bridge/video-settings').status_code,403)

    def test_whole_video_chunked_bound_and_no_implicit_generation(self):
        with patch.object(store,'start_analysis',side_effect=AssertionError('not explicit')):
            sid,b=self.begin()
            self.assertEqual(self.chunk(sid,0,RAW[:25]).json()['offset'],25)
            self.assertEqual(self.chunk(sid,25,RAW[25:]).json()['offset'],len(RAW))
            job=self.finish(sid).json()
            self.assertEqual(store.video_path(job['id']).read_bytes(),RAW)
            self.assertEqual(job['status'],'uploaded');self.assertEqual(job['estimated_duration_seconds'],601.25)
            mapped=self.client.get('/canvas-bridge/video-bindings/'+b['source_key'],headers=self.headers).json()
            self.assertEqual(mapped['lecture']['id'],job['id'])
            self.assertNotIn('http',json.dumps(mapped))

    def test_chunk_retry_conflict_and_incomplete(self):
        sid,_=self.begin();self.chunk(sid,0,RAW[:25])
        self.assertEqual(self.chunk(sid,0,RAW[:25]).json()['offset'],25)
        self.assertEqual(self.chunk(sid,0,b'bad').status_code,409)
        self.assertEqual(self.finish(sid).status_code,422)
        self.assertEqual(self.chunk(sid,-1,b'x').status_code,422)

    def test_chunk_size_and_declared_length_limits(self):
        sid,_=self.begin();self.assertEqual(self.chunk(sid,0,b'x'*(video.MAX_CHUNK+1)).status_code,413)
        self.assertEqual(self.chunk(sid,0,RAW+b'extra').status_code,413)

    def test_duplicate_source_file_reuses_existing_job(self):
        sid,_=self.begin();self.chunk(sid,0,RAW);first=self.finish(sid).json()
        sid,_=self.begin(source_key='c'*64);self.chunk(sid,0,RAW);second=self.finish(sid).json()
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(store.list_jobs()),1)

    def test_explicit_analyze_uses_saved_video_credentials(self):
        sid,_=self.begin();self.chunk(sid,0,RAW);job=self.finish(sid).json()
        with patch.object(local_video,'start',return_value=job) as start:
            r=self.client.post('/canvas-bridge/video-jobs/'+job['id']+'/analyze',headers=self.headers)
            self.assertEqual(r.status_code,200);self.assertEqual(start.call_count,1)
            self.assertEqual(start.call_args.args,(job['id'],))
            self.assertEqual(start.call_args.kwargs,{})
            self.assertNotIn('time',start.call_args.kwargs)

    def test_completed_job_is_not_rebilled(self):
        sid,_=self.begin();self.chunk(sid,0,RAW);job=self.finish(sid).json()
        job.update(status='completed');store._save(store.job_directory(job['id']),job)
        with patch.object(store,'start_analysis',side_effect=AssertionError('no rebilling')):
            r=self.client.post('/canvas-bridge/video-jobs/'+job['id']+'/analyze',headers=self.headers);self.assertEqual(r.status_code,200)

    def test_cancel_discards_only_own_partial_import(self):
        sid,_=self.begin();self.chunk(sid,0,RAW[:25]);self.client.post(f'/canvas-bridge/video-imports/{sid}/cancel',headers=self.headers)
        self.assertEqual(store.list_jobs(),[]);self.assertEqual(self.chunk(sid,25,b'x').status_code,404)

    def test_raw_url_or_cookie_input_is_rejected(self):
        self.config()
        b={'request_id':str(uuid4()),'source_key':'b'*64,'filename':'x.mp4','mime_type':'video/mp4','duration_seconds':10.,'url':'https://synthetic.invalid/?token=not-real','cookie':'not-real'}
        self.assertEqual(self.client.post('/canvas-bridge/video-imports',json=b,headers=self.headers).status_code,422)
        self.assertFalse(store.data_root().exists())

    def test_existing_deleted_binding_is_safe(self):
        sid,b=self.begin();self.chunk(sid,0,RAW);job=self.finish(sid).json();store.delete_job(job['id'])
        self.assertIsNone(self.client.get('/canvas-bridge/video-bindings/'+b['source_key'],headers=self.headers).json()['lecture'])


if __name__=='__main__':unittest.main()
