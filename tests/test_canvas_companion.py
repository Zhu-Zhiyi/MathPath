"""Companion checks use temporary storage, fake feeds and fake model replies only."""
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
import canvas_companion as companion
import graph_builder
import lecture_store as store
import main
import research_memory as memory
from model_settings import GenerationConfig

EXTENSION = "a" * 32


def theorem(**overrides):
    return memory.TheoremInput(**{"name":"秩—零度定理", "category":"common", "statement":"设 V 为有限维向量空间，T:V→W 为线性映射，则 dim V = dim ker T + dim im T。",
        "assumptions":["V 有限维", "T 线性"], "source":"合成测试教材，§1", **overrides})


def feed():
    recent=(datetime.now(timezone.utc)-timedelta(days=10)).isoformat()
    old=(datetime.now(timezone.utc)-timedelta(days=800)).isoformat()
    return f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2610.12345v1</id><title>Synthetic recent paper</title><published>{recent}</published><summary>Not a real paper.</summary></entry><entry><id>http://arxiv.org/abs/2201.12345</id><title>Old paper updated yesterday</title><published>{old}</published><updated>{recent}</updated></entry><entry><id>https://invalid.example/abs/javascript:bad</id><published>{recent}</published></entry></feed>'''.encode()


class CanvasCompanionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="mathpath-companion-check-",ignore_cleanup_errors=True);self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"MATHPATH_DATA_DIR":self.tmp.name});self.env.start();self.addCleanup(self.env.stop)
        self.client=TestClient(main.app,base_url="http://127.0.0.1");self.addCleanup(self.client.close)
        self.model=patch.object(companion,"generate_text",side_effect=AssertionError("real model forbidden"));self.model.start();self.addCleanup(self.model.stop)
        self.remote=patch.object(memory,"_fetch_feed",side_effect=AssertionError("real network forbidden"));self.remote.start();self.addCleanup(self.remote.stop)
        memory._paper_cache.clear();memory._paper_time=0.;companion._cache.clear()
        self.config=GenerationConfig(provider="api",base_url="https://synthetic.invalid/v1",model="synthetic",api_format="chat_completions",output_mode="json_schema",revision="test",api_key="never-used")
        self.snapshot=patch.object(companion,"resolve_generation_config",return_value=self.config);self.snapshot.start();self.addCleanup(self.snapshot.stop)

    def pair(self):
        r=self.client.post("/canvas/pair",json={"extension_id":EXTENSION});self.assertEqual(r.status_code,200,r.text)
        v=r.json();return {"Authorization":"Bearer "+v["token"],"X-MathPath-Extension":EXTENSION,"Origin":"chrome-extension://"+EXTENSION}

    def workspace(self,**kw):
        return memory.save_workspace(memory.WorkspaceInput(title="合成研究问题",intent="question",question="有限维条件用在哪里？",**kw))

    def lecture(self):
        path=store.begin_upload("合成回放.mp4","video/mp4");video=b"\x00\x00\x00\x18ftypisom"+b"synthetic"*20;(path/"video.part").write_bytes(video)
        job=store.finish_upload(path,"合成回放.mp4","video/mp4",len(video),hashlib.sha256(video).hexdigest(),100.)
        item={"start_seconds":10.,"end_seconds":20.,"kind":"theorem","title":"秩—零度定理","evidence":"audio_visual","source_summary":"设 V 有限维，T 线性。", "explanation":"合成解析", "formulas":[],"steps":[],"uncertainties":[]}
        job.update(status="completed",duration_seconds=100.,total_chunks=1,completed_chunks=1,clips=[{"index":0,"start_seconds":0.,"end_seconds":100.,"analysis":{"title":"合成","overview":"合成", "items":[item],"learning_goals":[],"practice":[],"coverage_notes":[],"uncertainties":[]}}])
        store._save(path,job);return job

    def test_pair_encrypted_at_rest_and_status_never_exposes_token(self):
        h=self.pair();raw=companion._pair_path().read_bytes();self.assertNotIn(h["Authorization"].encode(),raw)
        status=self.client.get("/canvas/pair/status").json();self.assertTrue(status["connected"]);self.assertNotIn("token",status)

    def test_bridge_rejects_missing_wrong_and_revoked_credentials(self):
        self.assertEqual(self.client.get("/canvas-bridge/lectures").status_code,403)
        h=self.pair();self.assertEqual(self.client.get("/canvas-bridge/lectures",headers=h).status_code,200)
        bad={**h,"Authorization":"Bearer wrong"};self.assertEqual(self.client.get("/canvas-bridge/lectures",headers=bad).status_code,403)
        self.client.delete("/canvas/pair");self.assertEqual(self.client.get("/canvas-bridge/lectures",headers=h).status_code,403)

    def test_bridge_cors_is_scoped_to_paired_extension(self):
        h=self.pair()
        for origin in ["https://oc.sjtu.edu.cn","http://127.0.0.1","null","chrome-extension://"+"b"*32]:
            self.assertEqual(self.client.get("/canvas-bridge/lectures",headers={**h,"Origin":origin}).status_code,403)
        r=self.client.options("/canvas-bridge/context",headers={"Origin":h["Origin"]});self.assertEqual(r.status_code,204);self.assertEqual(r.headers["access-control-allow-origin"],h["Origin"])
        self.assertEqual(self.client.options("/canvas-bridge/context").status_code,403)

    def test_extension_cannot_use_private_settings_or_pair_api(self):
        h=self.pair()
        for path in ["/settings/model","/library/histories","/research/workspaces","/canvas/pair/status"]:
            self.assertEqual(self.client.get(path,headers=h).status_code,403,path)
        self.assertEqual(self.client.post("/canvas/pair",headers=h,json={"extension_id":"b"*32}).status_code,403)

    def test_host_and_expiry_are_checked(self):
        h=self.pair()
        self.assertEqual(self.client.get("/canvas-bridge/lectures",headers={**h,"Host":"localhost"}).status_code,403)
        with patch.object(companion,"pairing",return_value={"extension_id":EXTENSION,"token":"x"*43,"expires_at":0}):
            self.assertEqual(self.client.get("/canvas-bridge/lectures",headers=h).status_code,403)

    def test_pair_input_and_cross_origin_are_rejected(self):
        self.assertEqual(self.client.post("/canvas/pair",json={"extension_id":"../evil"}).status_code,422)
        self.assertEqual(self.client.post("/canvas/pair",headers={"Origin":"https://evil.invalid"},json={"extension_id":EXTENSION}).status_code,403)

    def test_context_exact_intervals_gaps_and_offset(self):
        j=self.lecture()
        for time,expected in [(9.,0),(10.,1),(19.9,1),(20.,0),(100.,0)]:
            v=companion.context(companion.FrameInput(time=time,lecture_id=j["id"]));self.assertEqual(len(v["items"]),expected);self.assertEqual(v["gap"],not bool(expected))
        v=companion.context(companion.FrameInput(time=5.,offset=5.,lecture_id=j["id"]));self.assertEqual(v["items"][0]["title"],"秩—零度定理");self.assertEqual(v["source_time"],10.)

    def test_invalid_frame_and_id_never_read_arbitrary_files(self):
        h=self.pair()
        self.assertEqual(self.client.post("/canvas-bridge/context",headers=h,json={"time":0,"lecture_id":"../../secret"}).status_code,404)
        for data in [{"time":-1},{"time":10801},{"time":0,"caption":"a"*8001},{"time":0,"video_url":"secret"}]:
            self.assertEqual(self.client.post("/canvas-bridge/context",headers=h,json=data).status_code,422)

    def test_only_current_workspace_verified_memories_enter_model_context(self):
        a=self.workspace();b=memory.save_workspace(memory.WorkspaceInput(title="另一个",intent="study"))
        memory.save_theorem(theorem(workspace_id=a["id"]))
        verified=memory.save_theorem(theorem(workspace_id=a["id"],name="已核对",statement_complete=True,verified_by_user=True))
        memory.save_theorem(theorem(workspace_id=b["id"],name="别的项目",statement_complete=True,verified_by_user=True))
        c=companion.context(companion.FrameInput(time=0.,workspace_id=a["id"]));self.assertEqual([r["id"] for r in c["verified_memory"]],[verified["id"]])
        self.assertNotIn("verified_memory",companion.context(companion.FrameInput(time=0.)))

    def test_theorem_markdown_is_named_complete_and_versioned(self):
        w=self.workspace();body=theorem(name="非标准定理 / 特例",category="nonstandard",workspace_id=w["id"],statement="对每个 x∈V，存在唯一 y∈W 满足 P(x,y)，且 f(x)=y。",assumptions=["V,W 非空","P 满足假设 A"])
        record=memory.save_theorem(body);path=memory.theorem_path(record);self.assertIn("非标准定理",path.name);self.assertIn(body.statement,path.read_text(encoding="utf-8"));self.assertIn("陈述待补全",path.read_text(encoding="utf-8"))
        updated=memory.save_theorem(body.model_copy(update={"record_id":record["id"],"expected_revision":1,"statement_complete":True,"verified_by_user":True}))
        self.assertEqual(updated["revision"],2);self.assertTrue((memory.root()/"versions"/record["id"]/"r1.md").is_file());self.assertIn("已由用户",path.read_text(encoding="utf-8"))
        with self.assertRaises(store.LectureError):memory.save_theorem(body.model_copy(update={"record_id":record["id"],"expected_revision":1}))

    def test_homonym_variants_and_duplicate_record_are_distinguished(self):
        a=memory.save_theorem(theorem());b=memory.save_theorem(theorem(statement="不同条件与结论"));c=memory.save_theorem(theorem())
        self.assertNotEqual(a["id"],b["id"]);self.assertEqual(a["id"],c["id"]);self.assertNotEqual(memory.theorem_path(a),memory.theorem_path(b))

    def test_incomplete_or_uncertain_memory_cannot_be_verified(self):
        with self.assertRaises(ValidationError):theorem(verified_by_user=True)
        with self.assertRaises(ValidationError):theorem(verified_by_user=True,statement_complete=True,uncertainties=["缺一个假设"])
        for url in ["http://example.com","https://example.com/?token=private","https://u:p@example.com/"]:
            with self.assertRaises(ValidationError):theorem(source_url=url)

    def test_markdown_download_roundtrip_and_safe_filename(self):
        r=self.client.post("/research/theorems",json=theorem(name="../../定理:<>").model_dump());self.assertEqual(r.status_code,200,r.text)
        value=r.json();path=memory.theorem_path(value);self.assertEqual(path.parent,memory.root()/"theorems")
        response=self.client.get(f"/research/theorems/{value['id']}/markdown");self.assertEqual(response.status_code,200);self.assertIn("完整陈述",response.text)
        self.assertEqual(len(self.client.get("/research/theorems?q=有限维").json()),1)

    def test_onboarding_requires_question_only_in_question_mode(self):
        for intent,code in [("question",422),("explore",200),("study",200)]:
            self.assertEqual(self.client.post("/research/workspaces",json={"title":"起点","intent":intent}).status_code,code)
        h=self.pair();r=self.client.post("/canvas-bridge/workspaces",headers=h,json={"title":"初学","intent":"explore","search_terms":"homology"});self.assertEqual(r.status_code,200)
        rows=self.client.get("/canvas-bridge/workspaces",headers=h).json();self.assertEqual(rows[0]["search_terms"],"homology");self.assertNotIn("question",rows[0])

    def test_explanation_requires_material_and_is_candidate(self):
        with self.assertRaises(store.LectureError):companion.explain(companion.FrameInput(time=0.))
        value={"name":"合成定理","statement":"若 A 则 B。","assumptions":["A"],"intuition":"仅为示意。","proof_steps":["核对 A。"],"prerequisites":[],"questions":[],"uncertainties":["需查原文"],"diagram":None}
        with patch.object(companion,"generate_text",return_value=json.dumps(value)) as m:
            result=companion.explain(companion.FrameInput(time=0.,caption="若 A 则 B。"));self.assertTrue(result["review_required"]);self.assertEqual(result["source"],"caption")
            companion.explain(companion.FrameInput(time=0.,caption="若 A 则 B。"));self.assertEqual(m.call_count,1)
            self.assertEqual(m.call_args.kwargs["configuration"],self.config)

    def test_model_schema_and_chat_turn_bounds(self):
        with patch.object(companion,"generate_text",return_value='{"answer":" ","uncertainties":[]}'):
            with self.assertRaises(store.LectureError):companion.ask(companion.AskInput(time=0.,question="为什么？"))
        with self.assertRaises(store.LectureError):companion.ask(companion.AskInput(time=0.,question="为什么？",turns=[{"question":"q","answer":"a","secret":"not permitted"}]))
        with self.assertRaises(ValidationError):companion.AskInput(time=0.,question="q",turns=[{}]*7)

    def test_public_search_uses_real_feed_dates_and_cache_without_model(self):
        with patch.object(memory,"_fetch_feed",return_value=feed()) as remote:
            data=companion.explore(companion.ExploreInput(terms="persistent homology"));again=memory.recent_papers("persistent homology")
            self.assertEqual(len(data["papers"]),1);self.assertEqual(again["papers"],data["papers"]);self.assertEqual(remote.call_count,1)
            self.assertNotIn("question",remote.call_args.args[0]);self.assertIn("submittedDate",remote.call_args.args[0]);self.assertEqual(data["directions"],[])

    def test_search_rate_limit_and_errors_do_not_fabricate_papers(self):
        with patch.object(memory,"_fetch_feed",return_value=b"<!DOCTYPE x><feed/>"):
            with self.assertRaises(store.LectureError) as e:memory.recent_papers("homology")
        self.assertEqual(e.exception.status_code,502)
        with self.assertRaises(store.LectureError) as e:memory.recent_papers("topology")
        self.assertEqual(e.exception.status_code,429)

    def test_direction_citations_must_match_retrieved_papers(self):
        metadata={"papers":[{"id":"2610.12345","title":"Synthetic","abstract":"Synthetic","published":"2026-11-01","url":"https://arxiv.org/abs/2610.12345"}],"query":"homology","window_days":730,"retrieved_at":"2026-11-14"}
        result={"directions":[{"title":"研究线索","why":"需看原文","first_step":"复现定义","prerequisites":["线性代数"],"paper_ids":["invented"]}],"caveats":["未完成查新"]}
        with patch.object(memory,"recent_papers",return_value=metadata),patch.object(companion,"generate_text",return_value=json.dumps(result)):
            with self.assertRaises(store.LectureError):companion.explore(companion.ExploreInput(terms="homology",use_model=True))

    def test_local_pages_do_not_trigger_generation(self):
        for path in ["/research-workbench","/canvas-setup","/canvas-demo","/static/research.js"]:
            self.assertEqual(self.client.get(path).status_code,200,path)
        r=self.client.get("/canvas-setup");self.assertEqual(r.headers["x-frame-options"],"DENY")

    def test_graph_receives_selected_research_background_only_on_request(self):
        w=self.workspace()
        with patch.object(main,"build_graph",side_effect=graph_builder.GraphError("synthetic stop")) as build:
            self.client.post("/analyze",json={"text":"学习有限维条件","workspace_id":w["id"]})
            self.assertEqual(build.call_args.kwargs["research_context"]["question"],w["question"])
        self.assertEqual(self.client.post("/analyze",json={"text":"目标","workspace_id":"../../bad"}).status_code,404)


if __name__=="__main__":unittest.main()
