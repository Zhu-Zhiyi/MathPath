"""Automatic memory and opt-in classified notes; isolated files and fake models."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
import main
import note_service as notes
import research_memory as memory
import lecture_store
import lesson_builder
import teaching_help
from model_settings import GenerationConfig


def document(kind="A"):
    result={"name":"合成秩—零度定理","statement":r"若 $V$ 有限维，$T:V\to W$ 线性，则 $\dim V=\dim\ker T+\dim\operatorname{im}T$。",
        "assumptions":["V 有限维","T 线性"],"category":"common","statement_complete":True,
        "proof":"取核的基并扩充为 V 的基。扩充向量的像构成像空间的基；由此计算维数。","proof_complete":False,
        "significance":"把原空间的维数拆成被压到零和仍可分辨的两部分。","next_work":"计算投影的核和像，核对维数公式；这是直接应用。",
        "boundary":"有限维保证基的有限计数；必须先确认映射线性。","check_question":"零映射的核和像分别是什么？","check_answer":"核是 V，像为零空间。","uncertainties":["合成软件测试；证明细节待补全。"]}
    return {"title":"合成线性映射笔记","category":"Basic Algebra","introduction":"先区分定义、直观与证明。",
        "exposition":[] if kind=="B" else [{"heading":"核与像","text":r"$\ker T=\{v:T(v)=0\}$；像由所有 $T(v)$ 组成。"}],
        "results":[] if kind=="B" else [result],"questions":[{"question":"零映射的核是什么？","answer":"整个定义域。"}],"memories":[],"uncertainties":["仅合成软件测试材料。"]}


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="mathpath-note-test-",ignore_cleanup_errors=True);self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        env=patch.dict(os.environ,{"MATHPATH_DATA_DIR":str(self.base/"data")});env.start();self.addCleanup(env.stop)
        self.folder=self.base/"notebook";self.folder.mkdir()
        self.mirror=self.base/"cloud";self.mirror.mkdir()
        notes.set_directory(notes.DirectoryInput(directory=str(self.folder),mirror_directory=str(self.mirror)))
        model=patch.object(notes,"generate_text",side_effect=AssertionError("real model forbidden"));model.start();self.addCleanup(model.stop)
        compiler=patch.object(notes,"compile_pdf",return_value=(None,{"status":"not_tested"}));compiler.start();self.addCleanup(compiler.stop)
        self.client=TestClient(main.app,base_url="http://127.0.0.1");self.addCleanup(self.client.close)

    def body(self,kind="A",**changes):
        return notes.NoteInput(**{"enabled":True,"request_id":str(uuid4()),"note_type":kind,"content_date":"2026-11-15","source_kind":"text","source_text":"合成线性映射材料。",**changes})

    def generate(self,kind="A",body=None,value=None):
        with patch.object(notes,"generate_text",return_value=json.dumps(value or document(kind),ensure_ascii=False)) as model:
            result=notes.generate(body or self.body(kind))
        return result,model

    def test_unchecked_has_no_model_or_file_effect(self):
        before=list(self.folder.rglob("*"))
        with patch.object(notes,"settings",side_effect=AssertionError("disabled must not read settings")):
            self.assertEqual(notes.generate(self.body(enabled=False))["status"],"disabled")
        self.assertEqual(before,list(self.folder.rglob("*")))

    def test_a_has_conclusions_first_and_two_way_proof_links(self):
        result,_=self.generate();tex=Path(result["paths"]["tex"]).read_text(encoding="utf-8")
        self.assertLess(tex.index("主要结论"),tex.index("定义、例子与直观"));self.assertLess(tex.index("定义、例子与直观"),tex.index("证明附录"))
        self.assertIn(r"\hypertarget{result-1}",tex);self.assertIn(r"\hyperlink{proof-1}",tex);self.assertIn(r"\hyperlink{result-1}",tex)
        self.assertIn("2026-11-15_",Path(result["paths"]["tex"]).name);self.assertEqual(Path(result["paths"]["tex"]).parent,self.folder/"Basic Algebra")
        self.assertTrue(result["review_required"]);self.assertEqual(result["memory"]["status"],"saved")

    def test_b_contains_questions_answers_only(self):
        result,_=self.generate("B");md=Path(result["paths"]["md"]).read_text(encoding="utf-8")
        self.assertIn("问题 1",md);self.assertIn("参考答案",md);self.assertNotIn("定义、例子",md);self.assertNotIn("证明附录",md)

    def test_b_rejects_model_that_ignores_requested_structure(self):
        with self.assertRaises(lecture_store.LectureError):self.generate("B",value=document("A"))
        self.assertEqual(list(self.folder.rglob("*.tex")),[])

    def test_c_has_dedicated_folder_and_five_teaching_requirements(self):
        result,_=self.generate("C");self.assertEqual(Path(result["paths"]["md"]).parent,self.folder/"Type C 讲课笔记"/"Basic Algebra")
        md=Path(result["paths"]["md"]).read_text(encoding="utf-8")
        for heading in ("为什么有意思","接着能做什么","假设作用与结论边界","证明及关键想法","理解检查"):self.assertIn(heading,md)

    def test_repeat_request_does_not_rebill_or_write_another_note(self):
        body=self.body();first,_=self.generate(body=body)
        with patch.object(notes,"generate_text",side_effect=AssertionError("duplicate must not call model")):
            self.assertEqual(notes.generate(body),first)
        self.assertEqual(len(list(self.folder.rglob("*.tex"))),1)
        with self.assertRaises(lecture_store.LectureError):notes.generate(body.model_copy(update={"note_type":"C"}))

    def test_same_date_topic_creates_new_note_without_overwrite(self):
        first,_=self.generate();second,_=self.generate();self.assertNotEqual(first["paths"]["md"],second["paths"]["md"])
        self.assertTrue(Path(first["paths"]["md"]).is_file())

    def test_mirror_is_checked_byte_for_byte(self):
        result,_=self.generate(body=self.body(sync=True));self.assertEqual(result["sync"]["status"],"completed")
        for path in result["paths"].values():
            local=Path(path);remote=self.mirror/local.relative_to(self.folder);self.assertEqual(local.read_bytes(),remote.read_bytes())

    def test_tex_instructions_from_model_are_data(self):
        for text in [r"$\input{secret}$",r"$\write18{cmd}$",r"$\^^69nput{secret}$",r"\input{secret}",r"$\begin{document}x\end{document}$"]:
            value=notes.tex_text(text);self.assertNotIn(r"\input",value);self.assertNotIn(r"\write18",value);self.assertNotIn(r"\^^69",value);self.assertNotIn(r"\begin{document}",value)
        self.assertIn(r"\frac{1}{2}",notes.tex_text(r"$\frac{1}{2}$"))

    def test_category_cannot_choose_arbitrary_path(self):
        bad=document();bad["category"]="../../elsewhere"
        with self.assertRaises(lecture_store.LectureError):self.generate(value=bad)
        self.assertEqual(list(self.folder.rglob("*.tex")),[])

    def test_directory_setting_never_uses_model_and_cross_origin_is_denied(self):
        result=self.client.get("/notes/settings");self.assertEqual(result.status_code,200);self.assertEqual(result.json()["directory"],str(self.folder))
        self.assertEqual(self.client.post("/notes/settings",headers={"Origin":"https://evil.invalid"},json={"directory":str(self.folder)}).status_code,403)
        self.assertEqual(self.client.get("/notes/sources").status_code,200)

    def test_download_uses_only_recorded_artifact(self):
        result,_=self.generate();self.assertEqual(self.client.get(f"/notes/files/{result['note_id']}/tex").status_code,200)
        self.assertEqual(self.client.get(f"/notes/files/{result['note_id']}/pdf").status_code,404)

    def test_ai_memory_auto_deduplicates_and_versions(self):
        value={"name":"自动定理","category":"nonstandard","statement":"每个 x 都满足 P(x)。","assumptions":[],"statement_complete":True}
        first=memory.remember([value],source_key="test",source="合成来源");again=memory.remember([value],source_key="test",source="合成来源")
        self.assertEqual(first["ids"],again["ids"]);record=memory.theorems()[0];self.assertEqual(record["revision"],1);self.assertEqual(record["origin"],"ai");self.assertFalse(record["verified_by_user"])
        newer=memory.remember([{**value,"statement":"每个 x 都满足 Q(x)。"}],source_key="test",source="合成来源")
        self.assertEqual(newer["ids"],first["ids"]);self.assertEqual(memory.theorems()[0]["revision"],2)
        self.assertTrue((memory.root()/"versions"/record["id"]/"r1.md").is_file())

    def test_verified_memory_is_preserved_and_candidate_is_recalled_with_warning(self):
        value={"name":"自动定理","category":"nonstandard","statement":"若 A 则 B。","assumptions":[],"statement_complete":True}
        original=memory.remember([value],source_key="test",source="来源");r=memory.theorems()[0]
        fields={k:r[k] for k in memory.TheoremInput.model_fields if k in r};fields.update(record_id=r["id"],expected_revision=1,verified_by_user=True)
        memory.save_theorem(memory.TheoremInput(**fields))
        memory.remember([{**value,"statement":"若 C 则 D。"}],source_key="test",source="来源")
        rows=memory.theorems();self.assertEqual(len(rows),2);self.assertTrue(next(x for x in rows if x["id"]==r["id"])["verified_by_user"])
        recalled=memory.recall_candidates(None,"自动定理");self.assertEqual(len(recalled),1);self.assertEqual(recalled[0]["status"],"unverified_memory")

    def test_learning_card_captures_ai_chosen_theorem_without_save_request(self):
        from test_lessons import generated_card,small_graph
        card=generated_card();candidate={"name":"卡片定理","category":"nonstandard","statement":"若 A 则 B。","assumptions":["A"],"uncertainties":["需核对来源"],"statement_complete":True};card["memories"]=[candidate]
        config=GenerationConfig(provider="api",base_url="https://synthetic.invalid/v1",model="test",api_format="chat_completions",output_mode="json_schema",revision="test",api_key="never-used")
        lesson_builder.clear_lesson_cache();self.addCleanup(lesson_builder.clear_lesson_cache)
        with patch.object(lesson_builder,"resolve_generation_config",return_value=config),patch.object(lesson_builder,"_generate_lesson",return_value=lesson_builder.Lesson.model_validate(card)):
            r=self.client.post("/lesson",json={"graph":small_graph().model_dump(),"node_id":"goal"})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(memory.theorems()[0]["name"],"卡片定理");self.assertEqual(memory.theorems()[0]["origin"],"ai")

    def test_chat_captures_theorem_without_changing_public_response_fields(self):
        candidate={"name":"问答定理","category":"nonstandard","statement":"若 A 则 B。","assumptions":["A"],"uncertainties":[],"statement_complete":True}
        result={"response":"这是候选说明，需核对。","source":"model_candidate","review_required":True,"answer_status":"answered","theorems":[candidate]}
        with patch.object(teaching_help,"generate_text",return_value=json.dumps(result)):
            r=self.client.post("/study/chat",json={"question":"请说明若 A 则 B 的版本。","use_model":True})
        self.assertEqual(r.status_code,200,r.text);self.assertNotIn("theorems",r.json());self.assertEqual(memory.theorems()[0]["name"],"问答定理");self.assertFalse(memory.theorems()[0]["verified_by_user"])

    def test_stale_directory_choice_stops_before_model(self):
        revision=notes.settings()["revision"];notes.set_directory(notes.DirectoryInput(directory=str(self.base/"elsewhere")))
        with self.assertRaises(lecture_store.LectureError) as error:notes.generate(self.body(settings_revision=revision))
        self.assertEqual(error.exception.status_code,409)


if __name__=="__main__":unittest.main()
