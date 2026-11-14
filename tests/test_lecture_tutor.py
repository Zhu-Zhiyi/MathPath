"""Grounded diagnosis, explanation evidence and persistence; never a real model call."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import lecture_store as store
import lecture_tutor as tutor
import main
from model_settings import GenerationConfig


def candidate():
    return {"status": "candidate", "difficulty_kind": "prerequisite", "hypothesis": "可能需要先区分核的元素与线性关系。",
        "evidence_quotes": [{"evidence_id": "c0_i0", "quote": "T(v)=0"}],
        "prerequisites": [{"concept": "线性映射的核", "why_needed": "需要用核的定义解释这一步。", "quick_check": "v 属于核意味着什么？"}],
        "repair_steps": ["写出核的定义。", "核对线性关系与系数条件。"],
        "checkpoint": {"question": "若 T(v)=0，v 一定是零向量吗？", "hint": "考虑零映射。",
                       "reference_answer": "不一定；核可以含非零向量。", "rubric": ["指出一般不成立。", "给出理由或反例。"]},
        "next_action": "try_check", "uncertainties": ["需核对课堂中的额外假设。"]}


class LectureTutorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mathpath-tutor-test-", ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"MATHPATH_DATA_DIR": directory.name})
        environment.start(); self.addCleanup(environment.stop)
        for name in ("generate_text", "resolve_generation_config"):
            guard = patch.object(tutor, name, side_effect=AssertionError("Explicit offline model mock required"))
            guard.start(); self.addCleanup(guard.stop)
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8123")
        self.addCleanup(self.client.close)
        video = b"\x00\x00\x00\x18ftypisom" + b"synthetic-not-a-video" * 4
        path = store.begin_upload("合成课堂.mp4", "video/mp4", len(video), 60.)
        (path / "video.part").write_bytes(video)
        self.job = store.finish_upload(path, "合成课堂.mp4", "video/mp4", len(video), hashlib.sha256(video).hexdigest(), 60.)
        item = {"start_seconds": 0., "end_seconds": 60., "kind": "proof", "title": "核与线性关系", "evidence": "audio_visual",
                "source_summary": "由线性关系 T(v)=0 可知 v 属于核。", "explanation": "合成示例，不是真实视频识别。",
                "formulas": ["T(v)=0"], "steps": ["使用核的定义。"], "uncertainties": ["需核对额外条件。"]}
        analysis = {"title": "合成片段", "overview": "仅为软件测试。", "items": [item], "learning_goals": [], "practice": [], "coverage_notes": [], "uncertainties": []}
        self.job.update(status="completed", duration_seconds=60., total_chunks=1, completed_chunks=1, processed_seconds=60., coverage_ratio=1.,
                        clips=[{"index": 0, "start_seconds": 0., "end_seconds": 60., "analysis": analysis}])
        store._save(path, self.job)
        self.base = f"/lectures/{self.job['id']}/tutor"
        self.body = {"request_id": str(uuid4()), "item_id": "c0_i0", "question": "这一步为什么成立？", "learner_context": "会计算，但不熟悉定义。", "use_model": False}

    def local(self):
        response = self.client.post(self.base, json=self.body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def mock(self, result, side_effect=None):
        config = GenerationConfig(provider="api", base_url="https://example.invalid/v1", model="synthetic-text-model",
                                  api_format="chat_completions", output_mode="json_schema", revision="synthetic", api_key="synthetic-never-sent")
        return patch.object(tutor, "resolve_generation_config", return_value=config), patch.object(tutor, "generate_text", return_value=json.dumps(result, ensure_ascii=False), side_effect=side_effect)

    def test_local_diagnosis_is_persistent_but_not_a_mastery_claim(self):
        record = self.local()
        self.assertEqual(record["source"], "local_reference")
        self.assertEqual(record["diagnosis"]["status"], "insufficient_evidence")
        self.assertTrue(record["review_required"])
        self.assertEqual(record["evidence"][0]["start_seconds"], 0)
        self.assertEqual(self.client.get(self.base).json(), [record])
        self.assertEqual(store.get_job(self.job["id"])["clips"], self.job["clips"])

    def test_candidate_quotes_and_absolute_timestamps_come_from_saved_evidence(self):
        self.body["use_model"] = True
        a, b = self.mock(candidate())
        with a, b as model:
            response = self.client.post(self.base, json=self.body)
        self.assertEqual(response.status_code, 200)
        record = response.json()
        self.assertEqual(record["model"], "synthetic-text-model")
        self.assertEqual(record["source"], "model_candidate")
        self.assertTrue(record["review_required"])
        prompt = json.loads(model.call_args.args[0])
        self.assertEqual(prompt["selected_id"], "c0_i0")
        self.assertEqual(prompt["learner_context"], self.body["learner_context"])
        self.assertNotIn("api_key", prompt)
        self.assertNotIn("mastery", record)

    def test_fake_quote_unknown_source_and_missing_selected_source_are_rejected(self):
        for mutate in [lambda d: d["evidence_quotes"][0].update(quote="视频里没有这句话"),
                       lambda d: d["evidence_quotes"][0].update(evidence_id="c99_i99"),
                       lambda d: d.update(evidence_quotes=[])]:
            value = candidate(); mutate(value)
            body = {**self.body, "request_id": str(uuid4()), "use_model": True}
            a, b = self.mock(value)
            with a, b:
                response = self.client.post(self.base, json=body)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(self.client.get(self.base).json(), [])

    def test_changed_request_id_payload_does_not_silently_reuse_a_diagnosis(self):
        first = self.local()
        self.assertEqual(self.client.post(self.base, json=self.body).json(), first)
        changed = {**self.body, "question": "另一个问题"}
        self.assertEqual(self.client.post(self.base, json=changed).status_code, 409)
        self.assertEqual(len(self.client.get(self.base).json()), 1)

    def test_local_explanation_and_candidate_feedback_are_both_saved(self):
        record = self.local()
        path = self.base + "/" + record["id"] + "/answer"
        body = {"request_id": str(uuid4()), "answer": "T(v)=0 不一定推出 v=0；例如零映射。", "use_model": False}
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, 200)
        attempt = response.json()["attempts"][0]
        self.assertEqual(attempt["feedback"]["assessment"], "needs_review")
        self.assertEqual(self.client.post(path, json=body).json(), response.json())
        body["answer"] = "换了一份回答"
        self.assertEqual(self.client.post(path, json=body).status_code, 409)
        feedback = {"assessment": "matches_reference", "feedback": "候选意见：与反例要点相符。", "remaining_gap": "", "next_action": "independent_check", "next_prompt": "若 T 单射，结论如何改变？"}
        a, b = self.mock(feedback)
        with a, b as model:
            result = self.client.post(path, json={**body, "request_id": str(uuid4()), "use_model": True})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["attempts"][-1]["review_required"])
        self.assertNotIn("known_ids", result.json())
        prompt = json.loads(model.call_args.args[0])
        self.assertEqual(prompt["previous_attempts"][0]["answer"], attempt["answer"])
        self.assertTrue(prompt["previous_attempts"][0]["review_required"])

    def test_export_retains_diagnosis_and_student_work_and_delete_removes_session_only(self):
        record = self.local()
        self.client.post(self.base + "/" + record["id"] + "/answer", json={"request_id": str(uuid4()), "answer": "我还不确定额外条件。", "use_model": False})
        export = self.client.get(f"/lectures/{self.job['id']}/export").json()
        self.assertEqual(len(export["tutoring"]), 1)
        markdown = self.client.get(f"/lectures/{self.job['id']}/export?format=markdown").text
        self.assertIn("我还不确定额外条件", markdown)
        self.assertIn("卡点诊断", markdown)
        self.assertNotIn("synthetic-never-sent", markdown)
        self.assertEqual(self.client.delete(self.base + "/" + record["id"]).status_code, 200)
        self.assertEqual(self.client.get(self.base).json(), [])
        self.assertTrue(store.video_path(self.job["id"]).exists())

    def test_deleted_classroom_during_model_request_is_never_recreated(self):
        def generate(*args, **kwargs):
            store.delete_job(self.job["id"])
            return json.dumps(candidate(), ensure_ascii=False)
        a, b = self.mock(candidate(), side_effect=generate)
        with a, b:
            response = self.client.post(self.base, json={**self.body, "use_model": True})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(store.job_directory(self.job["id"]).exists())

    def test_deleted_session_during_feedback_is_not_restored(self):
        record = self.local()
        feedback = {"assessment": "needs_review", "feedback": "仍需核对。", "remaining_gap": "缺理由", "next_action": "try_again", "next_prompt": "依据是什么？"}
        def generate(*args, **kwargs):
            tutor.delete_session(self.job["id"], record["id"])
            return json.dumps(feedback, ensure_ascii=False)
        a, b = self.mock(feedback, side_effect=generate)
        with a, b:
            result = self.client.post(self.base + "/" + record["id"] + "/answer", json={"request_id": str(uuid4()), "answer": "我的解释", "use_model": True})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.get(self.base).json(), [])

    def test_bad_inputs_and_foreign_origin_are_rejected_without_echoing_student_text(self):
        for change in [{"item_id": "c99_i99"}, {"question": " "}, {"question": "x" * 3001}, {"api_key": "synthetic-secret"}]:
            response = self.client.post(self.base, json={**self.body, **change})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("synthetic-secret", response.text)
        self.assertEqual(self.client.post(self.base, json=self.body, headers={"Origin": "https://foreign.example"}).status_code, 403)
        self.assertEqual(self.client.get(self.base).json(), [])

    def test_context_is_bounded_and_other_classrooms_are_not_read(self):
        copied = copy.deepcopy(self.job)
        copied["clips"][0]["analysis"]["items"] *= 30
        store._save(store.job_directory(self.job["id"]), copied)
        self.body["item_id"] = "c0_i15"
        original = store.video_path(self.job["id"]).read_bytes()
        other = store.begin_upload("另一堂合成课.mp4", "video/mp4", len(original), 60.)
        (other / "video.part").write_bytes(original)
        store.finish_upload(other, "另一堂合成课.mp4", "video/mp4", len(original), hashlib.sha256(original).hexdigest(), 60.)
        with patch.object(store, "get_job", wraps=store.get_job) as reads:
            record = self.local()
        self.assertTrue(all(call.args[0] == self.job["id"] for call in reads.call_args_list))
        self.assertLessEqual(len(record["evidence"]), 3)
        self.assertLessEqual(len(json.dumps(record["evidence"], ensure_ascii=False)), 32000)
        self.assertTrue(any(item["id"] == "c0_i15" for item in record["evidence"]))

    def test_another_request_cannot_start_while_a_diagnosis_is_running(self):
        def generate(*args, **kwargs):
            with self.assertRaises(store.LectureError) as error:
                tutor.diagnose(self.job["id"], tutor.Input.model_validate({**self.body, "request_id": str(uuid4())}))
            self.assertEqual(error.exception.status_code, 409)
            return json.dumps(candidate(), ensure_ascii=False)
        a, b = self.mock(candidate(), side_effect=generate)
        with a, b as model:
            result = self.client.post(self.base, json={**self.body, "use_model": True})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(model.call_count, 1)

    def test_model_failure_and_corrupt_history_do_not_fall_back_or_erase_notes(self):
        a, b = self.mock(candidate(), side_effect=RuntimeError("synthetic-secret-error"))
        with a, b:
            result = self.client.post(self.base, json={**self.body, "use_model": True})
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("synthetic-secret-error", result.text)
        self.assertEqual(self.client.get(self.base).json(), [])
        path = store.job_directory(self.job["id"]) / "tutoring.json"
        path.write_text('{"version":1,"sessions":[{"bad":"record"}]}', encoding="utf-8")
        self.assertEqual(self.client.get(self.base).status_code, 503)
        self.assertEqual(store.get_job(self.job["id"])["clips"], self.job["clips"])
