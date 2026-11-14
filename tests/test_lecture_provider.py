"""Native video transport tests using synthetic bytes and wholly offline HTTP."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch
import urllib.error

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import lecture_provider as provider

KEY = "synthetic-google-key-never-echo-this"
NAME = "files/mathpath-test"
URI = provider.BASE_URL + "/v1beta/" + NAME
UPLOAD_URL = provider.BASE_URL + "/upload/v1beta/files?upload_id=synthetic-session"


def metadata(**overrides):
    return {"name": NAME, "uri": URI, "mimeType": "video/mp4", "state": "ACTIVE",
            "videoMetadata": {"videoDuration": "601.25s"}, **overrides}


def clip_data():
    return {"title": "线性映射的核", "overview": "说明核的定义及例子。",
        "items": [{"start_seconds": 300.0, "end_seconds": 350.0, "kind": "definition",
            "title": "核的定义", "evidence": "audio_visual", "source_summary": "教师写出核的定义。",
            "explanation": "核由映到零向量的所有向量组成。", "formulas": [r"\ker T=\{v:T(v)=0\}"],
            "steps": ["先固定线性映射。", "再取零向量的原像。"], "uncertainties": []}],
        "learning_goals": ["能写出核的定义。"],
        "practice": [{"question": "零映射的核是什么？", "hint": "考虑每个向量的像。",
                      "answer": "补充参考解法：核为整个定义域。", "origin": "supplement"}],
        "coverage_notes": ["只解析指定区间，文字和公式仍需回看原视频核对。"], "uncertainties": []}


def completion(value=None, **overrides):
    text = json.dumps(clip_data() if value is None else value, ensure_ascii=False)
    return {"status": "completed", "steps": [{"type": "model_output",
              "content": [{"type": "text", "text": text}]}], **overrides}


class Response:
    def __init__(self, payload=None, *, headers=None, raw=None, status=200):
        self.status = status
        self.headers = headers or {}
        self.raw = io.BytesIO(json.dumps(payload).encode("utf-8") if raw is None else raw)

    def read(self, size=-1):
        return self.raw.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.body_sizes = []
        self.upload_bytes = b""

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        if hasattr(request.data, "read"):
            while True:
                part = request.data.read(8192)
                self.body_sizes.append(len(part))
                if not part:
                    break
                self.upload_bytes += part
        if not self.responses:
            raise AssertionError("Unexpected offline HTTP call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FastEvent:
    def __init__(self, *, cancel_on_wait=False):
        self.cancelled = False
        self.cancel_on_wait = cancel_on_wait
        self.waits = []

    def is_set(self):
        return self.cancelled

    def wait(self, seconds):
        self.waits.append(seconds)
        self.cancelled = self.cancel_on_wait
        return self.cancelled


class LectureProviderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="mathpath-video-provider-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "sample.mp4"
        self.source = b"synthetic-video-bytes-" * 900
        self.path.write_bytes(self.source)
        self.remote = provider.RemoteVideo(NAME, URI, 601.25, "video/mp4")
        self.guard = patch.object(provider.urllib.request, "build_opener",
                                  side_effect=AssertionError("Must replace every HTTP call offline"))
        self.blocked_http = self.guard.start()
        self.addCleanup(self.guard.stop)

    def upload(self, responses, *, cancel=None, mime_type="video/mp4"):
        opener = Opener(responses)
        progress = []
        with patch.object(provider.urllib.request, "build_opener", return_value=opener) as constructor:
            value = provider.upload_video(self.path, mime_type, KEY, cancel or Event(), progress.append)
        return value, opener, progress, constructor

    def analyze(self, response, *, remote=None, start=300.0, end=600.0, cancel=None, model=provider.DEFAULT_VIDEO_MODEL):
        opener = Opener([response])
        with patch.object(provider.urllib.request, "build_opener", return_value=opener):
            result = provider.analyze_clip(remote or self.remote, start, end, KEY, model, cancel or Event(),
                                           previous_context="前段候选内容，不是本段来源。")
        return result, opener

    def test_streamed_upload_uses_explicit_key_no_redirect_and_real_duration(self):
        value, opener, progress, constructor = self.upload([
            Response(raw=b"", headers={"X-Goog-Upload-URL": UPLOAD_URL}), Response({"file": metadata()})])
        self.assertEqual(value.duration_seconds, 601.25)
        self.assertEqual(value.uri, URI)
        self.assertEqual(progress, ["uploading_remote", "processing_remote"])
        self.assertEqual(opener.upload_bytes, self.source)
        self.assertLessEqual(max(opener.body_sizes), 8192)
        init, transfer = [item[0] for item in opener.requests]
        self.assertEqual(init.get_header("X-goog-api-key"), KEY)
        self.assertEqual(transfer.get_header("Content-length"), str(len(self.source)))
        self.assertEqual(transfer.get_header("X-goog-upload-command"), "upload, finalize")
        self.assertNotIn(KEY, init.full_url)
        self.assertNotIn(KEY, transfer.full_url)
        self.assertNotIn(self.path.name, init.data.decode("utf-8"), "private local filename is not sent as displayName")
        self.assertTrue(all(isinstance(call.args[0], provider._NoRedirect) for call in constructor.call_args_list))

    def test_processing_state_polls_same_file_until_active(self):
        event = FastEvent()
        value, opener, _progress, _constructor = self.upload([
            Response(raw=b"", headers={"x-goog-upload-url": UPLOAD_URL}),
            Response({"file": metadata(state="PROCESSING")}), Response(metadata())], cancel=event)
        self.assertEqual(value.name, NAME)
        self.assertEqual(event.waits, [provider.POLL_INTERVAL])
        self.assertEqual(opener.requests[-1][0].full_url, URI)

    def test_equivalent_mov_metadata_mime_is_retained_for_inference(self):
        value, *_ = self.upload([Response(raw=b"", headers={"x-goog-upload-url": UPLOAD_URL}),
                                  Response({"file": metadata(mimeType="video/mov")})], mime_type="video/quicktime")
        self.assertEqual(value.mime_type, "video/mov")

    def test_untrusted_upload_destination_is_rejected_before_sending_bytes(self):
        bad = ["http://generativelanguage.googleapis.com/upload/v1beta/files?x=1",
               "https://evil.test/upload/v1beta/files", "https://generativelanguage.googleapis.com.evil.test/upload/v1beta/files",
               "https://name:secret@generativelanguage.googleapis.com/upload/v1beta/files",
               provider.BASE_URL + "/upload/v1beta/files/../files", provider.BASE_URL + "/elsewhere",
               provider.BASE_URL + "/upload/v1beta/files#fragment"]
        for url in bad:
            opener = Opener([Response(raw=b"", headers={"x-goog-upload-url": url})])
            with self.subTest(url=url), patch.object(provider.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(provider.LectureProviderError) as caught:
                    provider.upload_video(self.path, "video/mp4", KEY, Event(), lambda _stage: None)
                self.assertEqual(len(opener.requests), 1)
                self.assertEqual(opener.upload_bytes, b"")
                self.assertFalse(caught.exception.cleanup_failed)
                self.assertNotIn(url, str(caught.exception))

    def test_missing_key_invalid_model_and_cancelled_work_never_calls_http(self):
        for value in ["", "line\nbreak", KEY + "\r\nX-Extra: yes", "密钥"]:
            with self.subTest(key=value), self.assertRaises(provider.LectureProviderError):
                provider.upload_video(self.path, "video/mp4", value, Event(), lambda _stage: None)
        stopped = Event(); stopped.set()
        with self.assertRaisesRegex(provider.LectureProviderError, "已取消"):
            provider.upload_video(self.path, "video/mp4", KEY, stopped, lambda _stage: None)
        for model in ["../gemini", "gemini-3.8-flash?key=", "text-only", "gemini-hello\nthere"]:
            with self.subTest(model=model), self.assertRaises(provider.LectureProviderError):
                provider.analyze_clip(self.remote, 0.0, 300.0, KEY, model, Event())
        self.blocked_http.assert_not_called()

    def test_remote_failure_cleans_up_the_known_handle(self):
        for state in ["FAILED", "UNKNOWN", "STATE_UNSPECIFIED"]:
            opener = Opener([Response(raw=b"", headers={"x-goog-upload-url": UPLOAD_URL}),
                             Response({"file": metadata(state=state)}), Response(raw=b"")])
            with self.subTest(state=state), patch.object(provider.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(provider.LectureProviderError) as caught:
                    provider.upload_video(self.path, "video/mp4", KEY, Event(), lambda _stage: None)
                self.assertEqual(opener.requests[-1][0].method, "DELETE")
                self.assertEqual(opener.requests[-1][0].full_url, URI)
                self.assertFalse(caught.exception.cleanup_failed)

    def test_missing_or_bad_duration_is_not_replaced_by_client_guess(self):
        for duration in [None, "", "0s", "-3s", "nans", "120", "1e9s", "0.0000000000s"]:
            bad = metadata(videoMetadata={"videoDuration": duration})
            opener = Opener([Response(raw=b"", headers={"x-goog-upload-url": UPLOAD_URL}),
                             Response({"file": bad}), Response(raw=b"")])
            with self.subTest(duration=duration), patch.object(provider.urllib.request, "build_opener", return_value=opener):
                with self.assertRaisesRegex(provider.LectureProviderError, "时长"):
                    provider.upload_video(self.path, "video/mp4", KEY, Event(), lambda _stage: None)
                self.assertEqual(opener.requests[-1][0].method, "DELETE")

    def test_cancel_during_processing_still_cleans_up_remote_file(self):
        opener = Opener([Response(raw=b"", headers={"x-goog-upload-url": UPLOAD_URL}),
                         Response({"file": metadata(state="PROCESSING")}), Response(raw=b"")])
        with patch.object(provider.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(provider.LectureProviderError, "已取消") as caught:
                provider.upload_video(self.path, "video/mp4", KEY, FastEvent(cancel_on_wait=True), lambda _stage: None)
        self.assertEqual(opener.requests[-1][0].method, "DELETE")
        self.assertFalse(caught.exception.cleanup_failed)

    def test_processing_timeout_cleans_up_without_unbounded_poll(self):
        opener = Opener([Response(raw=b"", headers={"x-goog-upload-url": UPLOAD_URL}),
                         Response({"file": metadata(state="PROCESSING")}), Response(raw=b"")])
        with patch.object(provider.urllib.request, "build_opener", return_value=opener), \
                patch.object(provider.time, "monotonic", side_effect=[0, provider.PROCESSING_TIMEOUT + 1]):
            with self.assertRaisesRegex(provider.LectureProviderError, "等待时间"):
                provider.upload_video(self.path, "video/mp4", KEY, FastEvent(), lambda _stage: None)
        self.assertEqual(len(opener.requests), 3)

    def test_cleanup_failure_is_reported_without_echoing_provider_or_key(self):
        opener = Opener([Response(raw=b"", headers={"x-goog-upload-url": UPLOAD_URL}),
                         Response({"file": metadata(state="FAILED")}), urllib.error.URLError(KEY)])
        with patch.object(provider.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(provider.LectureProviderError) as caught:
                provider.upload_video(self.path, "video/mp4", KEY, Event(), lambda _stage: None)
        self.assertTrue(caught.exception.cleanup_failed)
        self.assertNotIn(KEY, str(caught.exception))

    def test_uncertain_finalize_failure_retains_a_cleanup_warning(self):
        opener = Opener([Response(raw=b"", headers={"x-goog-upload-url": UPLOAD_URL}), urllib.error.URLError(KEY)])
        with patch.object(provider.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(provider.LectureProviderError) as caught:
                provider.upload_video(self.path, "video/mp4", KEY, Event(), lambda _stage: None)
        self.assertTrue(caught.exception.cleanup_failed)
        self.assertEqual(len(opener.requests), 2, "no unknown handle or format is retried")
        self.assertNotIn(KEY, str(caught.exception))

    def test_analyze_uses_audio_visual_interval_stateless_json_and_filters_thought(self):
        response = completion()
        response["steps"].insert(0, {"type": "thought", "summary": [{"type": "text", "text": KEY}]})
        result, opener = self.analyze(Response(response))
        self.assertEqual(result, clip_data())
        request = opener.requests[0][0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, provider.BASE_URL + "/v1beta/interactions")
        self.assertEqual(request.get_header("Api-revision"), "2026-05-20")
        self.assertEqual(payload["input"][0]["processing"], {"type": "static", "start_offset": "300s", "end_offset": "600s", "fps": 1})
        self.assertEqual(payload["input"][0]["mime_type"], "video/mp4")
        self.assertFalse(payload["store"])
        self.assertFalse(payload["stream"])
        self.assertNotIn("tools", payload)
        self.assertNotIn("previous_interaction_id", payload)
        self.assertNotIn(KEY, request.data.decode("utf-8"))
        self.assertEqual(payload["response_format"]["mime_type"], "application/json")
        self.assertIn("title", payload["response_format"]["schema"]["properties"])
        self.assertIn("source_summary", payload["response_format"]["schema"]["$defs"]["LectureItem"]["required"])
        self.assertIn("声音", payload["system_instruction"])
        self.assertIn("可见板书", payload["system_instruction"])
        self.assertIn("绝对秒数", payload["system_instruction"])

    def test_truncated_failed_and_nonterminal_generations_are_not_saved(self):
        for status in [None, "in_progress", "requires_action", "failed", "cancelled", "incomplete", "requires_continuation"]:
            with self.subTest(status=status), self.assertRaisesRegex(provider.LectureProviderError, "未完整完成"):
                self.analyze(Response(completion(status=status)))
        for changes in [{"error": {"message": KEY}}, {"continuation_token": KEY}]:
            with self.subTest(changes=changes), self.assertRaises(provider.LectureProviderError) as caught:
                self.analyze(Response(completion(**changes)))
            self.assertNotIn(KEY, str(caught.exception))

    def test_only_final_output_text_is_accepted(self):
        for steps in [None, [], [{"type": "thought", "content": [{"type": "text", "text": json.dumps(clip_data())}]}],
                      [{"type": "model_output", "content": [{"type": "refusal", "text": KEY}]}],
                      [{"type": "model_output", "content": [{"type": "image", "data": KEY}]}]]:
            with self.subTest(steps=steps), self.assertRaises(provider.LectureProviderError) as caught:
                self.analyze(Response(completion(steps=steps)))
            self.assertNotIn(KEY, str(caught.exception))

    def test_invalid_json_wrong_schema_and_out_of_interval_times_are_rejected(self):
        bad = [[], {"unrelated": KEY}]
        value = clip_data(); value["items"][0]["start_seconds"] = 299.0; bad.append(value)
        value = clip_data(); value["items"][0]["end_seconds"] = 601.0; bad.append(value)
        value = clip_data(); value["api_key"] = KEY; bad.append(value)
        for value in bad:
            with self.subTest(value=value), self.assertRaisesRegex(provider.LectureProviderError, "结构或时间"):
                self.analyze(Response(completion(value)))
        invalid = completion(steps=[{"type": "model_output", "content": [{"type": "text", "text": KEY}]}])
        with self.assertRaises(provider.LectureProviderError) as caught:
            self.analyze(Response(invalid))
        self.assertNotIn(KEY, str(caught.exception))

    def test_invalid_remote_file_and_interval_are_rejected_before_network(self):
        for start, end in [(-1, 300), (300, 300), (0, 602), (False, 100), (0, float("inf"))]:
            with self.subTest(start=start, end=end), self.assertRaises(provider.LectureProviderError):
                provider.analyze_clip(self.remote, start, end, KEY, provider.DEFAULT_VIDEO_MODEL, Event())
        for name, uri in [("files/../other", URI), (NAME, "https://elsewhere.test/file"),
                          (NAME, URI + "?key=must-not-be-forwarded")]:
            with self.subTest(name=name, uri=uri), self.assertRaises(provider.LectureProviderError):
                provider.analyze_clip(provider.RemoteVideo(name, uri, 700, "video/mp4"), 0, 300, KEY,
                                      provider.DEFAULT_VIDEO_MODEL, Event())
        self.blocked_http.assert_not_called()

    def test_http_failures_never_echo_raw_provider_payloads_and_do_not_retry(self):
        for status in [301, 302, 400, 401, 403, 404, 429, 503]:
            error = urllib.error.HTTPError("https://private.invalid?key=" + KEY, status, KEY, {}, io.BytesIO(KEY.encode()))
            opener = Opener([error])
            with self.subTest(status=status), patch.object(provider.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(provider.LectureProviderError) as caught:
                    provider.analyze_clip(self.remote, 300, 600, KEY, provider.DEFAULT_VIDEO_MODEL, Event())
                self.assertNotIn(KEY, str(caught.exception))
                self.assertEqual(len(opener.requests), 1)

    def test_delete_only_known_file_and_treats_already_removed_file_as_clean(self):
        for name in ["../files/abc", "files/a/b", "files/a?key=x", "files/-bad", "files/UPPER"]:
            with self.subTest(name=name), self.assertRaises(provider.LectureProviderError):
                provider.delete_remote(name, KEY)
        error = urllib.error.HTTPError(URI, 404, KEY, {}, io.BytesIO())
        opener = Opener([error])
        with patch.object(provider.urllib.request, "build_opener", return_value=opener):
            provider.delete_remote(NAME, KEY)
        self.assertEqual(opener.requests[0][0].method, "DELETE")
        self.assertEqual(opener.requests[0][0].full_url, URI)


if __name__ == "__main__":
    unittest.main()
