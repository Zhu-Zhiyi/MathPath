"""范围预检和书目目录只使用本地数据，不访问模型、账号或学习库。"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from pydantic import ValidationError

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import graph_builder
import learning_guidance
import llm_client
from graph_builder import KnowledgeGraph
from learning_guidance import (GoalScopeInput, GoalScopeOption, GoalScopeResponse, ReferenceBook,
                               ReferenceBooksInput, ReferenceBooksResponse, analyze_goal_scope,
                               get_reference_books)


def graph(label="理解同调群为什么对边界取商", base="理解链是几何片段的形式和"):
    return KnowledgeGraph.model_validate({"target_id": "goal", "nodes": [
        {"id": "base", "label": base, "prerequisite_sets": []},
        {"id": "goal", "label": label, "prerequisite_sets": [["base"]]},
    ]})


class LearningGuidanceTests(unittest.TestCase):
    def setUp(self):
        # A regression must fail before it can resolve real model credentials or send a request.
        for module, name in ((graph_builder, "generate_text"), (llm_client, "generate_text"),
                             (llm_client, "OpenAI"), (llm_client, "get_usable_session")):
            mock = patch.object(module, name, side_effect=AssertionError("范围预检和书目不得调用模型"))
            mock.start()
            self.addCleanup(mock.stop)

    def test_common_chinese_course_requests_are_subdivided(self):
        requests = ["数学", "我想学习数学", "讲讲拓扑学", "解释一下群论", "我想学习代数拓扑",
                    "请帮我系统学习线性代数", "从零开始学习微积分", "我希望全面掌握数学分析",
                    "学习抽象代数的全部内容", "我想学概率论", "学数论", "高等数学"]
        for text in requests:
            with self.subTest(text=text):
                response = analyze_goal_scope(GoalScopeInput(text=text, mode="proof"))
                self.assertTrue(response.needs_selection)
                self.assertGreaterEqual(len(response.options), 3)
                self.assertLessEqual(len(response.options), 5)
                self.assertEqual(response.original_text, text)
                self.assertEqual(len({item.id for item in response.options}), len(response.options))
                for item in response.options:
                    # Selecting any suggested direction must yield an actionable goal, not a second course menu.
                    self.assertFalse(analyze_goal_scope(item.goal).needs_selection)

    def test_english_course_requests_and_unicode_normalization(self):
        for text in ("I want to learn linear algebra", "Please explain topology", "learn calculus from scratch",
                     "abstract algebra", "I would like to understand real analysis", "mathematics",
                     "  线性代数！  ", "Ｌｉｎｅａｒ Ａｌｇｅｂｒａ"):
            with self.subTest(text=text):
                response = analyze_goal_scope(text)
                self.assertTrue(response.needs_selection)

    def test_concrete_questions_contextual_followups_and_math_text_proceed(self):
        for text in ("我想理解同调群为什么要取商", "SVD为什么存在？", "证明秩零化度定理",
                     "微积分中的函数极限定义是什么", "线性代数里如何求矩阵的核",
                     "这一步为什么？", "能给个例子吗", "这个符号是什么意思", "我还是不明白",
                     "拓扑学：设 X 是一个拓扑空间，连续映射的原像是开集。",
                     "Let V be a vector space and T: V -> V a linear map.",
                     "H_n = ker ∂_n / im ∂_{n+1}", "学习 Python", "解释一下这个矩阵的特征值",
                     "为什么拓扑空间不要求所有子集都开", "How do I prove a limit using epsilon-delta?"):
            with self.subTest(text=text):
                response = analyze_goal_scope(text)
                self.assertFalse(response.needs_selection)
                self.assertEqual(response.options, [])

    def test_subject_words_inside_question_do_not_force_unrelated_direction(self):
        for text in ("为什么同调群使用抽象代数里的商群", "比较线性代数和拓扑的商空间",
                     "这一步数学分析的估计为什么成立", "The word topology appears in this proof."):
            self.assertFalse(analyze_goal_scope(text).needs_selection)

    def test_scope_bounds_and_strict_fields(self):
        for payload in ({"text": " "}, {"text": ""}, {"text": "x" * 5001}, {"text": 12},
                        {"text": "数学", "mode": "advanced"}, {"text": "数学", "api_key": "synthetic"}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    GoalScopeInput.model_validate(payload)
        self.assertFalse(analyze_goal_scope("x" * 5000).needs_selection)

    def test_scope_response_consistency_and_copy_isolation(self):
        option = GoalScopeOption(id="one", title="方向", goal="具体目标", description="说明")
        with self.assertRaises(ValidationError):
            GoalScopeResponse(needs_selection=True, reason="宽泛", options=[option], original_text="数学")
        with self.assertRaises(ValidationError):
            GoalScopeResponse(needs_selection=False, reason="具体", options=[option], original_text="目标")
        first = analyze_goal_scope("数学")
        first.options[0].title = "合成的修改"
        self.assertNotEqual(analyze_goal_scope("数学").options[0].title, "合成的修改")

    def test_verified_subjects_have_author_or_publisher_metadata(self):
        cases = {
            "理解同调群为什么要取商": ("hatcher_algebraic_topology", "Allen Hatcher", "https://pi.math.cornell.edu/~hatcher/AT/ATpage.html", "§2.1"),
            "SVD 的证明": ("axler_linear_algebra", "Sheldon Axler", "https://linear.axler.net/", "§7E"),
            "实分析中极限的定义": ("abbott_understanding_analysis", "Stephen Abbott", "https://link.springer.com/book/10.1007/978-1-4939-2712-8", "第 2、4 章"),
            "商群中的正规子群": ("judson_abstract_algebra", "Thomas W. Judson", "https://judsonbooks.org/aata-files/aata-html/aata-toc.html", "10–11"),
            "点集拓扑中的紧致性": ("munkres_topology", "James R. Munkres", "https://www.pearson.com/en-us/subject-catalog/p/topology-classic-version/P200000006299/9780137848669", "第 2–3 章"),
            "微积分导数": ("openstax_calculus_one", "Gilbert Strang", "https://openstax.org/books/calculus-volume-1/pages/preface", "第 2、3、5 章"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                response = get_reference_books(text=text)
                book = response.books[0]
                self.assertEqual(book.id, expected[0])
                self.assertIn(expected[1], book.author)
                self.assertEqual(book.url, expected[2])
                self.assertIn(expected[3], book.section)
                self.assertIn("掌握程度仍需", response.message)
                ReferenceBooksResponse.model_validate_json(response.model_dump_json())

    def test_specific_verified_chapters(self):
        cases = {
            "基本群与覆盖空间": "§1.1、§1.3", "胞腔同调": "§2.2",
            "线性映射的商向量空间": "§3E", "正交投影为什么最小化误差": "§6C",
            "特征值与对角化": "第 5 章", "伽罗瓦理论": "第 21–23 章",
            "商环与理想": "第 16、18 章", "函数列的一致收敛": "第 6 章", "黎曼积分": "第 7 章",
        }
        for text, section in cases.items():
            with self.subTest(text=text):
                self.assertIn(section, get_reference_books(text=text).books[0].section)
        calculus = get_reference_books(text="导数")
        self.assertEqual(len(calculus.books), 2)
        self.assertEqual(calculus.books[1].section, "第 5 章：导数")

    def test_unknown_or_uncovered_subjects_never_receive_guess_books(self):
        for text in ("新概念 alpha", "机器学习", "代数几何", "泛函分析的线性算子", "复分析的积分",
                     "测度论的收敛定理", "微分几何中的切向量空间", "群同调", "持久同调",
                     "概率论的极限定理", "多变量微积分", "群表示论", "functional analysis",
                     "matrix representations of a group in representation theory", "Hochschild homology",
                     "同调代数", "用导出函子定义同调", "homological algebra", "derived functors"):
            with self.subTest(text=text):
                response = get_reference_books(text=text)
                self.assertEqual(response.books, [])
                self.assertIn("暂无已核对", response.message)
        self.assertEqual(get_reference_books().books, [])

    def test_node_focus_and_actual_goal_do_not_scan_irrelevant_prerequisites(self):
        current = graph(base="理解商群及正规子群")
        overall = get_reference_books(graph=current)
        self.assertEqual(overall.books[0].id, "hatcher_algebraic_topology")
        focused = get_reference_books(graph=current, node_id="base")
        self.assertEqual(focused.books[0].id, "judson_abstract_algebra")
        opaque = graph(base="基础知识")
        self.assertEqual(get_reference_books(graph=opaque, node_id="base").books[0].id,
                         "hatcher_algebraic_topology")
        uncovered = graph(base="持久同调")
        self.assertEqual(get_reference_books(graph=uncovered, node_id="base").books, [])
        # An explicit query must not be replaced by a previously viewed graph's subject.
        self.assertEqual(get_reference_books(graph=current, text="量子力学").books, [])

    def test_reference_input_bounds_membership_and_url_safety(self):
        for payload in ({}, {"text": " "}, {"text": "x" * 5001}, {"text": 10},
                        {"text": "同调", "node_id": "base"}, {"graph": graph(), "node_id": "missing"},
                        {"text": "同调", "api_key": "synthetic"}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    ReferenceBooksInput.model_validate(payload)
        valid = get_reference_books(text="同调").books[0].model_dump()
        for url in ("http://example.org/book", "https://user:secret@example.org/book", "javascript:alert(1)",
                    "https://example.org/\nbook", "https://example.org/ book"):
            with self.assertRaises(ValidationError):
                ReferenceBook.model_validate({**valid, "url": url})

    def test_catalog_is_not_mutated_by_adapted_chapters(self):
        specialised = get_reference_books(text="SVD").books[0]
        general = get_reference_books(text="线性代数").books[0]
        self.assertIn("§7E", specialised.section)
        self.assertIn("第 1–3 章", general.section)
        with self.assertRaises(ValidationError):
            specialised.title = "替换"


if __name__ == "__main__":
    unittest.main()
