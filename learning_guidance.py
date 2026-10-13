"""本地学习范围预检与经过核对的小型教材目录；不调用模型或读取账号配置。"""

import re
import unicodedata
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from graph_builder import KnowledgeGraph, NodeId, StudyMode


class GoalScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=5000)
    mode: StudyMode | None = None

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value):
        if not value.strip():
            raise ValueError("请先输入学习目标或数学文本")
        return value.strip()


class GoalScopeOption(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: NodeId
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=600)
    description: str = Field(min_length=1, max_length=500)


class GoalScopeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    needs_selection: bool
    reason: str = Field(min_length=1, max_length=500)
    options: list[GoalScopeOption] = Field(default_factory=list, max_length=5)
    original_text: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.needs_selection and len(self.options) < 3:
            raise ValueError("宽泛目标至少需要三个可选的具体方向")
        if not self.needs_selection and self.options:
            raise ValueError("具体目标不应带有强制选择项")
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("方向编号必须唯一")
        return self


class ReferenceBooksInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    graph: KnowledgeGraph | None = None
    node_id: NodeId | None = None
    text: str | None = Field(default=None, min_length=1, max_length=5000)

    @model_validator(mode="after")
    def validate_context(self):
        if self.text is not None and not self.text.strip():
            raise ValueError("教材查询文本不能为空白")
        if self.graph is None and (self.text is None or self.node_id is not None):
            raise ValueError("请提供学习图或查询文本；知识点编号需要对应学习图")
        if self.graph is not None and self.node_id is not None:
            if self.node_id not in {node.id for node in self.graph.nodes}:
                raise ValueError("教材查询知识点不属于当前学习图")
        return self


class ReferenceBook(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: NodeId
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    section: str = Field(min_length=1, max_length=500)
    why: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def validate_link(self):
        parts = urlsplit(self.url)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or any(ord(char) < 33 for char in self.url)):
            raise ValueError("教材链接必须是无登录信息的 HTTPS 地址")
        if any(not value.strip() for value in (self.title, self.author, self.section, self.why)):
            raise ValueError("教材说明不能为空白")
        return self


class ReferenceBooksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    books: list[ReferenceBook] = Field(default_factory=list, max_length=5)
    message: str = Field(min_length=1, max_length=600)


# 元数据与章节核对于 2026-10-13。只提供官网链接，不附带或上传书籍正文。
# Hatcher 作者的 Cornell 书籍页及目录：
# https://pi.math.cornell.edu/~hatcher/AT/ATpage.html
# https://pi.math.cornell.edu/~hatcher/AT/at1-tc.html
# Axler 作者的第 4 版 PDF 目录：https://linear.axler.net/LADR4e.pdf
# Abbott 出版社第 2 版目录：https://link.springer.com/book/10.1007/978-1-4939-2712-8
# Judson 作者主页与目录：https://judsonbooks.org/aata-files/aata-html/aata-toc.html
# Munkres 出版社页及 2025 官方目录：
# https://www.pearson.com/en-us/subject-catalog/p/topology-classic-version/P200000006299/9780137848669
# https://in.pearson.com/content/dam/region-growth/india/pearson-india/in-pdc/pdf/new-catalog-pdf/Catalogue-MathsPhysicsChemandBio-2025.pdf
# OpenStax 官方序言作者与章节：https://openstax.org/books/calculus-volume-1/pages/preface
_CATALOG = {
    "hatcher": ReferenceBook(
        id="hatcher_algebraic_topology", title="Algebraic Topology", author="Allen Hatcher",
        url="https://pi.math.cornell.edu/~hatcher/AT/ATpage.html",
        section="第 2 章，§2.1：单纯同调与奇异同调",
        why="沿教材中的链、循环、边界和同调定义核对推理，并尝试自行补全证明。"),
    "axler": ReferenceBook(
        id="axler_linear_algebra", title="Linear Algebra Done Right（第 4 版）", author="Sheldon Axler",
        url="https://linear.axler.net/", section="第 1–3 章：向量空间、有限维空间与线性映射",
        why="适合把计算经验整理为定义、定理和证明；作者官网提供合法电子版。"),
    "abbott": ReferenceBook(
        id="abbott_understanding_analysis", title="Understanding Analysis（第 2 版）", author="Stephen Abbott",
        url="https://link.springer.com/book/10.1007/978-1-4939-2712-8",
        section="第 2、4 章：序列与级数、函数极限与连续性",
        why="适合从实变量的定义与反例出发练习严谨证明；出版社页面可核对目录。"),
    "judson": ReferenceBook(
        id="judson_abstract_algebra", title="Abstract Algebra: Theory and Applications", author="Thomas W. Judson",
        url="https://judsonbooks.org/aata-files/aata-html/aata-toc.html",
        section="第 3、6、10–11 章：群、陪集、正规子群与商群、同态",
        why="适合用具体群的例子和证明习题巩固商群与同态；链接是作者的在线教材目录。"),
    "munkres": ReferenceBook(
        id="munkres_topology", title="Topology（第 2 版）", author="James R. Munkres",
        url="https://www.pearson.com/en-us/subject-catalog/p/topology-classic-version/P200000006299/9780137848669",
        section="第 2–3 章：拓扑空间与连续函数、连通性与紧致性",
        why="适合检查点集拓扑的定义、定理假设和反例；出版社页面提供目录与书籍信息。"),
    "calculus": ReferenceBook(
        id="openstax_calculus_one", title="Calculus Volume 1", author="Gilbert Strang、Edwin “Jed” Herman",
        url="https://openstax.org/books/calculus-volume-1/pages/preface",
        section="第 2、3、5 章：极限、导数与积分",
        why="用于补充单变量微积分的例题和习题；若目标是严格证明，可配合实分析教材。"),
}


def _options(rows):
    return [GoalScopeOption(id=key, title=title, goal=goal, description=description)
            for key, title, goal, description in rows]


_DIRECTIONS = {
    "math": _options([
        ("math_linear", "线性代数：空间与映射", "理解向量空间的基与维数为什么与坐标选择无关", "从向量、基和线性映射建立结构认识。"),
        ("math_analysis", "分析：极限与连续", "理解函数极限的 ε–δ 定义并用它证明一个简单极限", "从直觉走向有量词的严谨定义。"),
        ("math_algebra", "代数：群与商群", "理解商群为何要求正规子群，并用一个具体群说明", "研究运算、对称和等价类。"),
        ("math_topology", "拓扑：连续与空间", "理解拓扑空间中连续映射的开集原像定义", "比较不同空间中的连续性。"),
        ("math_proof", "证明入门", "区分必要条件与充分条件，并练习直接证明和反例", "先掌握陈述、推理和反例的基本方法。"),
    ]),
    "linear": _options([
        ("linear_basis", "基、维数与坐标", "理解向量空间的基与维数，并解释换基如何改变坐标", "区分向量本身和选定基下的坐标。"),
        ("linear_rank", "线性映射、核与像", "理解秩–零化度定理为什么成立", "把线性方程的自由度与映射的结构联系起来。"),
        ("linear_eigen", "特征值与对角化", "理解特征向量的几何意义以及矩阵何时可以对角化", "识别不变方向及对角化的条件。"),
        ("linear_projection", "正交投影与最小二乘", "理解正交投影为什么给出最小二乘解", "从误差的正交性理解最佳近似。"),
        ("linear_svd", "奇异值分解", "理解实矩阵的 SVD 如何分解为正交变换与非负伸缩", "联系几何作用、奇异值与低秩近似。"),
    ]),
    "topology": _options([
        ("topology_open", "开集与连续性", "理解拓扑空间中连续映射的开集原像定义", "建立拓扑空间和连续映射的基本语言。"),
        ("topology_compact", "紧致性", "理解紧致性的开覆盖定义，并比较闭有界条件的适用范围", "用例子检验不同空间中的紧致性。"),
        ("topology_connected", "连通与道路连通", "理解连通与道路连通的区别，并寻找反例", "分清两种不同的整体连通概念。"),
        ("topology_quotient", "商空间", "理解商拓扑如何描述把空间中的点粘合", "从具体粘合例子理解商映射。"),
        ("topology_fundamental", "基本群入门", "理解基本群如何记录闭路的同伦类型", "从点集拓扑过渡到代数拓扑。"),
    ]),
    "algebraic_topology": _options([
        ("at_fundamental", "基本群与闭路", "理解圆的基本群为什么是整数群", "从绕圈次数理解同伦类的运算。"),
        ("at_covering", "覆盖空间", "理解正规覆盖为何对应基本群的正规子群", "联系提升、覆盖变换和分类。"),
        ("at_homology", "同调群取商", "理解同调群为什么要将循环群对边界群取商", "厘清链、循环、边界和等价类。"),
        ("at_cellular", "胞腔同调", "使用一个具体 CW 复形的胞腔链复形计算同调群", "把空间分解转为可计算的代数结构。"),
        ("at_mayer_vietoris", "Mayer–Vietoris 序列", "理解 Mayer–Vietoris 长正合序列如何用于计算同调", "研究空间的分解与同调之间的关系。"),
    ]),
    "algebra": _options([
        ("algebra_elementary", "初等代数：方程与多项式", "通过因式分解理解一元二次方程的解", "如果想学习中学代数，可从具体方程开始。"),
        ("algebra_groups", "群与对称", "理解群的定义，并用置换群说明运算与对称", "从具体对称研究抽象运算。"),
        ("algebra_quotient", "陪集、商群与同态", "理解商群为何要求正规子群，并解释同态基本定理", "分清等价类上的运算何时成立。"),
        ("algebra_rings", "环、理想与商环", "理解理想为什么是构造商环所需的条件", "从整数模运算过渡到一般环。"),
        ("algebra_galois", "域扩张与伽罗瓦理论", "理解域扩张中伽罗瓦群如何描述根之间的对称", "从多项式的根进入域扩张理论。"),
    ]),
    "calculus": _options([
        ("calculus_limit", "函数极限", "理解函数极限的 ε–δ 定义并证明一个简单极限", "把趋近的直觉转换成可检验的条件。"),
        ("calculus_derivative", "导数与局部近似", "理解导数为何描述函数在一点附近的线性近似", "联系差商、切线与局部变化。"),
        ("calculus_integral", "定积分", "理解黎曼和如何定义定积分", "通过分割与极限理解累积量。"),
        ("calculus_fundamental", "微积分基本定理", "理解微积分基本定理为何将求导与积分联系起来", "检查连续性等假设和推理步骤。"),
        ("calculus_series", "数列与级数", "区分数列收敛和级数收敛，并用具体例子说明", "避免将通项趋于零误当作级数收敛。"),
    ]),
    "analysis": _options([
        ("analysis_sequences", "序列收敛", "用 ε–N 定义证明一个具体数列收敛", "练习有量词的定义与估计。"),
        ("analysis_continuity", "连续与一致连续", "理解连续与一致连续的量词差异，并给出反例", "检查取 δ 时能否依赖点的位置。"),
        ("analysis_completeness", "实数的完备性", "理解实数的上确界性质如何保证单调有界数列收敛", "联系实数结构和极限存在性。"),
        ("analysis_integral", "黎曼可积性", "理解黎曼可积的定义以及连续函数为何可积", "从上下和与紧致性理解积分。"),
        ("analysis_uniform", "一致收敛", "理解逐点收敛与一致收敛的区别及对连续性的影响", "检查函数列的极限能否保留性质。"),
    ]),
    "probability": _options([
        ("probability_conditional", "条件概率与独立性", "理解条件概率与独立性的区别，并用一个有限样本空间说明", "避免将不相交和独立混淆。"),
        ("probability_bayes", "贝叶斯公式", "理解贝叶斯公式如何从先验和证据得到后验概率", "用具体数据进行一次概率更新。"),
        ("probability_variable", "随机变量与分布", "理解随机变量、分布函数和概率质量函数之间的关系", "明确事件与数值描述之间的联系。"),
        ("probability_expectation", "期望与方差", "理解期望的线性性为什么不要求随机变量独立", "用具体随机变量检查运算规则。"),
    ]),
    "number_theory": _options([
        ("number_divisibility", "整除与最大公约数", "理解欧几里得算法为什么能计算最大公约数", "从算法步骤与整除不变量出发。"),
        ("number_congruence", "同余", "理解同余类上的加法与乘法为什么有定义", "把整数运算转化为等价类上的运算。"),
        ("number_primes", "素数与分解", "理解算术基本定理中素因数分解的唯一性", "练习整除性质与证明。"),
        ("number_chinese", "中国剩余定理", "理解中国剩余定理如何合并互素模数下的同余条件", "联系构造解的方法与互素假设。"),
    ]),
}

_ALIASES = {
    "math": ("数学", "math", "mathematics"),
    "linear": ("线性代数", "线代", "linear algebra"),
    "topology": ("拓扑", "拓扑学", "点集拓扑", "一般拓扑", "topology", "point set topology", "general topology"),
    "algebraic_topology": ("代数拓扑", "代数拓扑学", "algebraic topology"),
    "algebra": ("代数", "抽象代数", "近世代数", "群论", "algebra", "abstract algebra", "group theory"),
    "calculus": ("微积分", "高等数学", "高数", "calculus"),
    "analysis": ("数学分析", "实分析", "分析学", "real analysis", "mathematical analysis"),
    "probability": ("概率", "概率论", "probability", "probability theory"),
    "number_theory": ("数论", "number theory"),
}


def _normal(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _requested_subject(text):
    """Only recognize whole-course requests; a subject mentioned inside a question is insufficient."""
    value = _normal(text).strip(" .!?。！？,，:：;；\"'“”‘’")
    for subject, aliases in _ALIASES.items():
        for alias in aliases:
            if value == alias:
                return subject
            if re.search(r"[\u4e00-\u9fff]", alias):
                prefix = (r"(?:我|我们)?(?:想|想要|希望|要|打算)?(?:请)?(?:你)?"
                          r"(?:带我|帮我|教我)?(?:从零开始|从零|系统地|系统|全面地|全面|深入地|深入)?"
                          r"(?:学习|学|理解|掌握|了解|复习|介绍一下|介绍|解释一下|解释|讲解|讲一下|讲讲|入门)?")
                suffix = r"(?:的)?(?:全部内容|所有内容|基础知识|基础|入门|概论|这门课|课程)?(?:一下|吧|好吗|怎么学)?"
                if re.fullmatch(prefix + re.escape(alias) + suffix, value.replace(" ", "")):
                    return subject
            else:
                prefix = (r"(?:please )?(?:(?:i want to|i would like to|help me|teach me|let me) )?"
                          r"(?:(?:learn|study|understand|master|review|explain|introduce) )?"
                          r"(?:(?:all of|the basics of|an overview of|a course in) )?")
                suffix = r"(?: (?:from scratch|basics|comprehensively|in depth|please))?"
                if re.fullmatch(prefix + re.escape(alias) + suffix, value):
                    return subject
    vague = {
        "学点数学", "我想学点数学", "我想学习", "我想学", "帮我学习", "教我数学", "怎么学数学",
        "数学怎么学", "学习数学的全部内容", "学习", "learn math", "help me learn", "i want to learn",
    }
    return "math" if value in vague else None


def analyze_goal_scope(body: GoalScopeInput | str, mode: StudyMode | None = None) -> GoalScopeResponse:
    """Preflight is intentionally conservative: unrecognized specific text proceeds unchanged."""
    request = body if isinstance(body, GoalScopeInput) else GoalScopeInput(text=body, mode=mode)
    subject = _requested_subject(request.text)
    if subject is None:
        return GoalScopeResponse(needs_selection=False, reason="当前目标可以直接尝试生成学习地图。",
                                 options=[], original_text=request.text)
    return GoalScopeResponse(
        needs_selection=True, reason="这个目标覆盖多个主题。请先选择一个具体方向，再生成这一方向的学习地图。",
        options=[option.model_copy(deep=True) for option in _DIRECTIONS[subject]], original_text=request.text)


def _has(text, *keywords):
    value = _normal(text).replace("_", " ")
    for keyword in keywords:
        if re.search(r"[\u4e00-\u9fff]", keyword):
            if keyword in value:
                return True
        elif re.search(r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])", value):
            return True
    return False


def _unsupported_reference_subject(text):
    # A recognized broad field must not swallow a more specialized, uncovered subject.
    return _has(text, "代数几何", "复分析", "复变函数", "泛函分析", "测度论", "微分几何", "随机过程",
            "偏微分方程", "概率论", "数论", "表示论", "algebraic geometry", "complex analysis",
            "functional analysis", "measure theory", "differential geometry", "stochastic process",
            "partial differential", "representation theory", "probability", "number theory",
            "群同调", "群上同调", "层上同调", "持久同调", "group homology", "group cohomology",
            "sheaf cohomology", "persistent homology", "hochschild", "同调代数", "导出函子",
            "homological algebra", "derived functor", "derived functors")


def _reference_subject(text):
    if _unsupported_reference_subject(text):
        return None
    if _has(text, "同调", "代数拓扑", "链复形", "边界算子", "基本群", "覆盖空间", "同伦",
            "homology", "homological", "algebraic topology", "chain complex", "boundary operator",
            "fundamental group", "covering space", "homotopy"):
        return "hatcher"
    if _has(text, "向量空间", "线性", "线代", "矩阵", "特征值", "特征向量", "奇异值", "正交投影",
            "vector space", "linear", "matrix", "matrices", "eigenvalue", "eigenvector", "svd",
            "singular value", "orthogonal projection", "rank nullity"):
        return "axler"
    if _has(text, "群论", "抽象代数", "近世代数", "商群", "正规子群", "同态", "陪集", "商环", "理想",
            "环论", "伽罗瓦", "域扩张", "group theory", "abstract algebra", "quotient group",
            "normal subgroup", "homomorphism", "coset", "factor group", "ring theory", "galois", "field extension"):
        return "judson"
    if _has(text, "拓扑", "开集", "紧致", "连通", "商空间", "topology", "topological", "open set",
            "compactness", "connectedness", "quotient space"):
        return "munkres"
    if _has(text, "多变量", "多元", "重积分", "曲线积分", "曲面积分", "multivariable", "multiple integral"):
        return None
    if _has(text, "实分析", "数学分析", "实数", "上确界", "连续", "极限", "数列", "序列", "级数", "一致收敛", "可积", "黎曼积分",
            "real analysis", "limit", "limits", "sequence", "sequences", "series", "continuity",
            "continuous", "convergence", "riemann", "supremum", "real numbers"):
        return "abbott"
    if _has(text, "微积分", "导数", "求导", "积分", "微分", "calculus", "derivative", "differentiation", "integral"):
        return "calculus"
    return None


def _book_for(key, context):
    book = _CATALOG[key]
    changes = {}
    if key == "hatcher" and _has(context, "基本群", "覆盖空间", "fundamental group", "covering space"):
        changes.update(section="第 1 章：基本群与覆盖空间（特别是 §1.1、§1.3）",
                       why="核对路径同伦、基本群和覆盖空间的定义、提升性质与分类证明。")
    elif key == "hatcher" and _has(context, "胞腔", "mayer", "cellular"):
        changes.update(section="第 2 章，§2.2：同调的计算与应用",
                       why="继续学习胞腔同调和 Mayer–Vietoris 序列，并完成相关计算练习。")
    elif key == "hatcher" and _has(context, "同伦", "homotopy") and not _has(context, "同调", "homology"):
        changes.update(section="第 0 章：基本几何概念；第 4 章：同伦理论",
                       why="先核对同伦与同伦型的基本定义，再按已有基础选择同伦群等后续内容。")
    elif key == "axler" and _has(context, "奇异值", "svd", "singular value"):
        changes.update(section="§7E：奇异值分解；§7F：奇异值分解的推论",
                       why="核对 SVD 的定理条件与证明，再练习低秩近似等应用。")
    elif key == "axler" and _has(context, "特征", "对角化", "eigenvalue", "eigenvector", "diagonal"):
        changes.update(section="第 5 章：特征值与特征向量；§7B：谱定理",
                       why="比较一般线性算子的对角化条件与内积空间中的谱定理条件。")
    elif key == "axler" and _has(context, "正交", "最小二乘", "orthogonal", "least squares"):
        changes.update(section="第 6 章：内积空间；§6C：正交补与最小化问题",
                       why="从内积、正交补和投影的定义出发核对最小化推理。")
    elif key == "axler" and _has(context, "商", "quotient"):
        changes.update(section="§3E：向量空间的积与商",
                       why="核对商向量空间的构造、等价类运算与维数关系。")
    elif key == "judson" and _has(context, "伽罗瓦", "域扩张", "galois", "field extension"):
        changes.update(section="第 21–23 章：域、有限域与伽罗瓦理论",
                       why="先核对域扩张的基础，再按定理假设学习伽罗瓦对应。")
    elif key == "judson" and _has(context, "环", "理想", "ring", "ideal"):
        changes.update(section="第 16、18 章：环与整环",
                       why="在环的章节中核对理想、商环与同态，随后比较整环的附加性质。")
    elif key == "abbott" and _has(context, "一致收敛", "函数列", "uniform convergence", "function sequence"):
        changes.update(section="第 6 章：函数的序列与级数",
                       why="核对逐点收敛与一致收敛的量词，再检查极限与连续、求导等操作的条件。")
    elif key == "abbott" and _has(context, "积分", "可积", "integral", "integrable", "riemann"):
        changes.update(section="第 7 章：黎曼积分",
                       why="用上下和、可积性与定理条件核对积分相关证明。")
    elif key == "abbott" and _has(context, "导数", "求导", "微分", "derivative", "differentiation"):
        changes.update(section="第 5 章：导数",
                       why="核对可微性、导数与相关定理的假设，练习实变量微分的严谨证明。")
    return book.model_copy(update=changes, deep=True)


def get_reference_books(graph: KnowledgeGraph | None = None, node_id: str | None = None,
                        text: str | None = None) -> ReferenceBooksResponse:
    """Return relevant verified metadata, never generated bibliography or mastery certification."""
    if graph is None and node_id is None and text is None:
        return ReferenceBooksResponse(books=[], message="选择学习内容后，可以查看已核对的参考书。")
    request = ReferenceBooksInput(graph=graph, node_id=node_id, text=text)
    focus = []
    if request.text:
        focus.append(request.text)
    if request.graph and request.node_id:
        node = next(node for node in request.graph.nodes if node.id == request.node_id)
        focus.extend((node.label, node.id))
    full = []
    if request.graph:
        target = next(node for node in request.graph.nodes if node.id == request.graph.target_id)
        full.append(target.label)
        if request.graph.study_plan:
            full.append(request.graph.study_plan.objective)
        # Do not include all prerequisites: an algebraic prerequisite is not the overall topic.
    context = " ".join(focus) if focus else " ".join(full)
    key = _reference_subject(context)
    if key is None and focus and not request.text and not _unsupported_reference_subject(context):
        # Opaque labels can inherit the actual target, while an explicit text query stays authoritative.
        key = _reference_subject(" ".join(full))
        context = " ".join(full)
    if key is None:
        return ReferenceBooksResponse(
            books=[], message="这个主题暂无已核对的针对性教材。请补充更具体的数学主题或教材名称，暂不自动生成书目。")
    books = [_book_for(key, context)]
    if key == "calculus":
        books.append(_book_for("abbott", context))
    return ReferenceBooksResponse(
        books=books, message="以下书目与章节已根据作者或出版社页面核对；阅读建议对应当前主题，掌握程度仍需通过练习和证明检验。")
