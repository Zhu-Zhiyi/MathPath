"""Classroom storage/jobs/API checks use synthetic containers and fake video models."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import lecture_provider as provider
import lecture_store as store
from lecture_routes import router

VIDEO = b"\x00\x00\x00\x18ftypisom" + b"synthetic-container-not-a-real-lecture" * 4
KEY = "synthetic-video-key-never-persist"
MODEL = "gemini-synthetic-test"


def analysis(start=0.0, end=1.0):
    return {"title": "测试课堂片段", "overview": "这是合成测试，不是真实课堂解析。",
            "items": [{"start_seconds": float(start), "end_seconds": float(end), "kind": "definition",
                       "title": "线性映射", "evidence": "audio_visual", "source_summary": "合成视频来源描述。",
                       "explanation": "合成解释。", "formulas": ["T(x+y)=T(x)+T(y)"], "steps": [],
                       "uncertainties": ["测试数据没有真实讲课内容。"]}], "learning_goals": ["理解线性性"],
            "practice": [{"question": "给出线性映射例子。", "hint": "考虑恒等映射。", "answer": "恒等映射。", "origin": "supplement"}],
            "coverage_notes": ["仅测试时间区间处理。"], "uncertainties": []}


class LectureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mathpath-classroom-test-", ignore_cleanup_errors=True)
        self.addCleanup(self.temporary.cleanup)
        self.env = patch.dict(os.environ, {"MATHPATH_DATA_DIR": self.temporary.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.guards = []
        for name in ("upload_video", "analyze_clip", "delete_remote"):
            guard = patch.object(provider, name, side_effect=AssertionError("A video model mock is required"))
            self.guards.append(guard)
            guard.start()
            self.addCleanup(guard.stop)
        self.addCleanup(self.wait_all)

    def wait_all(self):
        store.shutdown_workers()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            with store._lock:
                if not store._active:
                    return
            time.sleep(.01)
        self.fail("synthetic worker did not finish")

    def upload(self, **overrides):
        values = {"filename": "课堂.mp4", "duration_seconds": 999.0}
        values.update(overrides)
        response = self.client.post("/lectures", params=values, content=VIDEO, headers={"Content-Type": "video/mp4"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def finish(self, job_id):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            with store._lock:
                job = store.get_job(job_id)
                idle = str(store.job_directory(job_id)) not in store._active
            if idle:
                return job
            time.sleep(.01)
        self.fail("synthetic job did not finish")

    def start(self, job_id, **values):
        payload = {"api_key": KEY, "model": MODEL, "chunk_seconds": 300, "remote_upload_confirmed": True}
        payload.update(values)
        return self.client.post(f"/lectures/{job_id}/analyze", json=payload)

    def mocks(self, duration=601.25, handler=None):
        remote = provider.RemoteVideo(name="files/synthetic-video", uri="https://generativelanguage.googleapis.com/v1beta/files/synthetic-video",
                                      duration_seconds=duration, mime_type="video/mp4")
        return (patch.object(provider, "upload_video", return_value=remote),
                patch.object(provider, "analyze_clip", side_effect=handler or (lambda remote, start, end, *args, **kwargs: analysis(start, end))),
                patch.object(provider, "delete_remote", return_value=None))

    def test_upload_only_is_local_and_video_supports_ranges(self):
        self.assertEqual(self.client.get("/lectures").json(), [])
        self.assertFalse(store.data_root().exists())
        job = self.upload()
        self.assertEqual(job["status"], "uploaded")
        self.assertTrue(job["video_available"])
        self.assertIsNone(job["duration_seconds"])
        self.assertEqual(job["estimated_duration_seconds"], 999)
        self.assertEqual(job["video_sha256"], hashlib.sha256(VIDEO).hexdigest())
        self.assertEqual(self.client.get("/lectures").json()[0]["id"], job["id"])
        self.assertNotIn("clips", self.client.get("/lectures").json()[0])
        video = self.client.get(f"/lectures/{job['id']}/video", headers={"Range": "bytes=0-11"})
        self.assertEqual(video.status_code, 206)
        self.assertEqual(video.content, VIDEO[:12])
        self.assertIn("bytes 0-11/", video.headers["content-range"])
        self.assertEqual(job["clips"], [])

    def test_bad_container_paths_sizes_and_types_do_not_create_jobs(self):
        for filename in ("../lecture.mp4", "C:\\lecture.mp4", "x.exe", ".", "x\n.mp4"):
            response = self.client.post("/lectures", params={"filename": filename}, content=VIDEO,
                                        headers={"Content-Type": "video/mp4"})
            self.assertIn(response.status_code, (415, 422))
        response = self.client.post("/lectures?filename=x.mp4", content=b"not a video", headers={"Content-Type": "video/mp4"})
        self.assertEqual(response.status_code, 415)
        with patch.object(store, "MAX_VIDEO_BYTES", 16):
            response = self.client.post("/lectures?filename=x.mp4", content=VIDEO, headers={"Content-Type": "video/mp4"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(store.list_jobs(), [])
        if store.data_root().exists():
            self.assertEqual(list(store.data_root().iterdir()), [])

    def test_streamed_upload_does_not_trust_content_length_or_skip_final_chunk(self):
        response = self.client.post("/lectures?filename=x.mp4", content=iter([VIDEO[:8], VIDEO[8:]]),
                                    headers={"Content-Type": "video/mp4", "Content-Length": str(len(VIDEO) + 1)})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(store.list_jobs(), [])

    def test_entire_actual_duration_including_fractional_tail_processed_once(self):
        job = self.upload()
        upload, analyze, cleanup = self.mocks()
        with upload as uploaded, analyze as generated, cleanup as deleted:
            response = self.start(job["id"])
            self.assertEqual(response.status_code, 202)
            result = self.finish(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["duration_seconds"], 601.25)
        self.assertEqual(result["total_chunks"], 3)
        self.assertEqual([(clip["start_seconds"], clip["end_seconds"]) for clip in result["clips"]],
                         [(0.0, 300.0), (300.0, 600.0), (600.0, 601.25)])
        self.assertEqual(result["processed_seconds"], 601.25)
        self.assertEqual(result["coverage_ratio"], 1.0)
        self.assertEqual(generated.call_count, 3)
        uploaded.assert_called_once()
        deleted.assert_called_once_with("files/synthetic-video", KEY)
        self.assertEqual(result["source"], "model_candidate")
        self.assertIs(result["review_required"], True)
        self.assertEqual(self.start(job["id"]).status_code, 409)
        for path in store.job_directory(job["id"]).iterdir():
            self.assertNotIn(KEY.encode(), path.read_bytes())
        for format in ("json", "markdown"):
            export = self.client.get(f"/lectures/{job['id']}/export?format={format}")
            self.assertEqual(export.status_code, 200)
            self.assertNotIn(KEY, export.text)
            self.assertNotIn("generativelanguage.googleapis.com", export.text)
            self.assertIn("attachment;", export.headers["content-disposition"])

    def test_failure_retains_prior_clip_and_explicit_resume_skips_it(self):
        job = self.upload()
        def failure(remote, start, end, *args, **kwargs):
            if start >= 300:
                raise RuntimeError(KEY)
            return analysis(start, end)
        upload, analyze, cleanup = self.mocks(handler=failure)
        with upload, analyze, cleanup:
            self.assertEqual(self.start(job["id"]).status_code, 202)
            failed = self.finish(job["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["completed_chunks"], 1)
        self.assertAlmostEqual(failed["coverage_ratio"], 300 / 601.25)
        self.assertNotIn(KEY, json.dumps(failed))
        self.assertEqual(self.start(job["id"], model="gemini-other-model").status_code, 409)
        self.assertEqual(self.start(job["id"], chunk_seconds=600).status_code, 409)
        upload, analyze, cleanup = self.mocks()
        with upload, analyze as generated, cleanup:
            self.assertEqual(self.start(job["id"]).status_code, 202)
            resumed = self.finish(job["id"])
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(generated.call_count, 2)
        self.assertEqual([call.args[1] for call in generated.call_args_list], [300.0, 600.0])
        self.assertEqual(resumed["clips"][0], failed["clips"][0])

    def test_out_of_interval_invented_timestamps_are_not_counted(self):
        job = self.upload()
        upload, analyze, cleanup = self.mocks(handler=lambda *args, **kwargs: analysis(0, 301))
        with upload, analyze, cleanup:
            self.assertEqual(self.start(job["id"]).status_code, 202)
            result = self.finish(job["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["clips"], [])
        self.assertEqual(result["processed_seconds"], 0)

    def test_cancellation_no_late_result_overwrite_and_duplicate_start_delete_rejected(self):
        job = self.upload()
        entered, release = threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            entered.set()
            release.wait(4)
            return analysis(0, 300)
        upload, analyze, cleanup = self.mocks(handler=delayed)
        with upload, analyze, cleanup:
            self.assertEqual(self.start(job["id"]).status_code, 202)
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.start(job["id"]).status_code, 409)
            self.assertEqual(self.client.delete(f"/lectures/{job['id']}").status_code, 409)
            self.assertEqual(self.client.post(f"/lectures/{job['id']}/cancel").status_code, 200)
            release.set()
            result = self.finish(job["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["clips"], [])
        self.assertEqual(result["processed_seconds"], 0)

    def test_restarted_active_job_is_marked_interrupted_without_model_calls(self):
        job = self.upload()
        directory = store.job_directory(job["id"])
        with store._lock:
            job.update(status="processing_remote")
            store._save(directory, job)
        recovered = self.client.get(f"/lectures/{job['id']}").json()
        self.assertEqual(recovered["status"], "interrupted")
        self.assertIn("中断", recovered["error"])
        self.assertEqual(self.client.delete(f"/lectures/{job['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/lectures/{job['id']}").status_code, 404)

    def test_model_payload_errors_and_missing_confirmation_never_echo_key(self):
        job = self.upload()
        for values in ({"remote_upload_confirmed": False}, {"chunk_seconds": True}, {"model": "../" + KEY},
                       {"api_key": "\n" + KEY}):
            response = self.start(job["id"], **values)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(KEY, response.text)
        response = self.client.post(f"/lectures/{job['id']}/analyze", json={"api_key": KEY, "unknown": KEY})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(KEY, response.text)
        response = self.client.post(f"/lectures/{job['id']}/analyze", content=KEY * 1000)
        self.assertEqual(response.status_code, 413)
        self.assertNotIn(KEY, response.text)

    def test_remote_cleanup_failure_visible_and_bad_actual_duration_does_not_generate(self):
        job = self.upload()
        upload, analyze, cleanup = self.mocks(duration=store.MAX_DURATION_SECONDS + 1)
        with upload, analyze as generated, patch.object(provider, "delete_remote", side_effect=RuntimeError(KEY)):
            self.assertEqual(self.start(job["id"]).status_code, 202)
            result = self.finish(job["id"])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["cleanup_failed"])
        self.assertEqual(result["total_chunks"], 0)
        generated.assert_not_called()
        self.assertNotIn(KEY, json.dumps(result))

    def test_cleanup_is_nonterminal_until_settled_and_warning_stays_across_retry(self):
        job = self.upload()
        entered, release = threading.Event(), threading.Event()
        def delayed_cleanup(*args):
            entered.set()
            release.wait(4)
            raise RuntimeError(KEY)
        upload, analyze, _ = self.mocks(handler=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(KEY)))
        with upload, analyze, patch.object(provider, "delete_remote", side_effect=delayed_cleanup):
            self.assertEqual(self.start(job["id"]).status_code, 202)
            self.assertTrue(entered.wait(3))
            pending = self.client.get(f"/lectures/{job['id']}").json()
            self.assertEqual(pending["status"], "cleaning_remote")
            self.assertEqual(self.client.delete(f"/lectures/{job['id']}").status_code, 409)
            self.assertEqual(self.start(job["id"]).status_code, 409)
            release.set()
            failed = self.finish(job["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["cleanup_failed"])
        upload, analyze, cleanup = self.mocks()
        with upload, analyze, cleanup:
            self.assertEqual(self.start(job["id"]).status_code, 202)
            completed = self.finish(job["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["cleanup_failed"], "success deleting a new upload cannot clear an earlier orphan warning")

    def test_interrupted_local_upload_remains_visible_and_deletable_after_restart(self):
        directory = store.begin_upload("中断视频.mp4", "video/mp4", len(VIDEO), 15)
        (directory / "video.part").write_bytes(VIDEO[:8])
        self.assertEqual(store.get_job(directory.name)["status"], "uploading_local")
        self.assertEqual(self.start(directory.name).status_code, 409)
        self.assertEqual(self.client.delete(f"/lectures/{directory.name}").status_code, 409)
        with store._lock:
            store._uploads.discard(str(directory))
        recovered = self.client.get("/lectures").json()[0]
        self.assertEqual(recovered["status"], "interrupted")
        self.assertFalse(recovered["video_available"])
        self.assertIn("重新上传", recovered["error"])
        self.assertEqual(self.start(directory.name).status_code, 404)
        self.assertEqual(self.client.delete(f"/lectures/{directory.name}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
