"""MathPath 内容评测：默认仅校验本地案例，--run 才调用真实模型。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import uuid4


EVAL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EVAL_DIR.parent
DATASET_PATH = EVAL_DIR / "cases.json"
RESULTS_DIR = EVAL_DIR / "results"
CRITERIA = (
    "coverage", "mathematical_correctness", "dependency_quality",
    "or_reasonableness", "target_match", "adaptation",
)
DOMAINS = {"linear_algebra", "groups", "homology", "topology"}
ACTIONS = {
    "formal_definition", "geometric_intuition", "concrete_example",
    "counterexample", "analogy", "proof_idea", "prerequisite_review",
    "micro_exercise",
}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


class DatasetError(ValueError):
    """离线案例格式错误；不包含登录或模型请求。"""


def require(condition, message):
    if not condition:
        raise DatasetError(message)


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def check_strings(value, location, *, allow_empty=False):
    require(isinstance(value, list), location + " 必须是列表")
    require(allow_empty or bool(value), location + " 不能为空")
    require(all(nonblank(item) for item in value), location + " 必须包含非空字符串")
    require(len(value) == len(set(value)), location + " 不得含重复项")


def validate_dataset(dataset):
    require(isinstance(dataset, dict), "数据集必须是 JSON 对象")
    require(type(dataset.get("schema_version")) is int and dataset["schema_version"] == 1,
            "不支持的数据集 schema_version")
    require(nonblank(dataset.get("dataset_name")), "缺少 dataset_name")
    require(nonblank(dataset.get("status")), "缺少 status")
    check_strings(dataset.get("notes"), "notes")
    sources = dataset.get("sources")
    require(isinstance(sources, list) and bool(sources), "缺少 sources")
    source_ids = set()
    for source in sources:
        require(isinstance(source, dict), "source 必须是对象")
        source_id = source.get("id")
        require(isinstance(source_id, str) and ID_PATTERN.fullmatch(source_id), "source id 无效")
        require(source_id not in source_ids, "source id 重复：" + source_id)
        source_ids.add(source_id)
        require(nonblank(source.get("title")) and nonblank(source.get("kind")), "source 说明缺失")
        require(isinstance(source.get("url"), str) and source["url"].startswith("https://"),
                "source url 必须使用 HTTPS")
    rubrics = dataset.get("rubrics")
    require(isinstance(rubrics, dict) and set(rubrics) == set(CRITERIA), "评分维度必须完整")
    for criterion, levels in rubrics.items():
        require(isinstance(levels, dict) and set(levels) == {"0", "1", "2"}, criterion + " 分档错误")
        require(all(nonblank(text) for text in levels.values()), criterion + " 分档说明不能为空")
    cases = dataset.get("cases")
    require(isinstance(cases, list) and bool(cases), "cases 必须是非空列表")
    case_ids = set()
    for case in cases:
        require(isinstance(case, dict), "case 必须是对象")
        case_id = case.get("id")
        require(isinstance(case_id, str) and ID_PATTERN.fullmatch(case_id), "case id 无效")
        require(case_id not in case_ids, "case id 重复：" + case_id)
        case_ids.add(case_id)
        require(case.get("domain") in DOMAINS, case_id + " domain 无效")
        for field in ("title", "goal", "query"):
            require(nonblank(case.get(field)), case_id + " 缺少 " + field)
        require(len(graph_input(case)) <= 5000, case_id + " 输入超过后端上限")
        check_strings(case.get("expected_concepts"), case_id + " expected_concepts")
        check_strings(case.get("pitfalls"), case_id + " pitfalls")
        profiles = case.get("profiles")
        require(isinstance(profiles, list) and len(profiles) >= 2, case_id + " 至少需要两个状态")
        profile_ids = set()
        for profile in profiles:
            require(isinstance(profile, dict), case_id + " profile 必须是对象")
            profile_id = profile.get("id")
            require(isinstance(profile_id, str) and ID_PATTERN.fullmatch(profile_id), case_id + " profile id 无效")
            require(profile_id not in profile_ids, case_id + " profile id 重复")
            profile_ids.add(profile_id)
            require(nonblank(profile.get("self_report")), case_id + " 缺少自报状态")
            check_strings(profile.get("known_concepts"), case_id + " known_concepts", allow_empty=True)
            check_strings(profile.get("familiar_but_unclear_concepts"), case_id + " unclear", allow_empty=True)
            require(not set(profile["known_concepts"]) & set(profile["familiar_but_unclear_concepts"]),
                    case_id + " 同一概念不能同时已掌握与未理解")
            steps = profile.get("acceptable_first_steps")
            require(isinstance(steps, list) and bool(steps), case_id + " 缺少可接受第一步")
            for step in steps:
                require(isinstance(step, dict), case_id + " first step 必须是对象")
                require(nonblank(step.get("focus")) and nonblank(step.get("rationale")),
                        case_id + " first step 缺少概念或理由")
                require(step.get("action") in ACTIONS, case_id + " 教学动作无效")
        refs = case.get("source_sections")
        require(isinstance(refs, list) and bool(refs), case_id + " 缺少数学核查来源")
        for ref in refs:
            require(isinstance(ref, dict) and ref.get("source_id") in source_ids and nonblank(ref.get("section")),
                    case_id + " 来源引用无效")
    return dataset


def graph_input(case):
    """严格固定构图输入；模拟状态不被偷偷加入当前无状态构图器。"""
    return "学习目标：" + case["goal"] + "\n\n当前困惑：" + case["query"]


def sha256(value):
    if not isinstance(value, bytes):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def review_template(case):
    return {
        "graph_review": {
            "reviewer": None,
            "scores": {criterion: None for criterion in CRITERIA if criterion != "adaptation"},
            "evidence": [],
            "mathematical_errors": [],
            "accepted_alternative_routes": [],
        },
        "profile_reviews": [{
            "profile_id": profile["id"],
            "known_node_mapping": [],
            "mapping_notes": "人工将自报概念映射到该次图的节点 ID；不由字符串匹配猜测掌握情况。",
            "recommended_focus": None,
            "recommended_action": None,
            "adaptation_score": None,
            "evidence": [],
            "status": "尚未生成或审阅该状态下的推荐与教学输出",
        } for profile in case["profiles"]],
    }


def output_path(prefix, suffix):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return RESULTS_DIR / f"{prefix}-{stamp}-{uuid4().hex[:8]}.{suffix}"


def select_cases(dataset, requested, parser, *, live=False):
    by_id = {case["id"]: case for case in dataset["cases"]}
    if live and not requested:
        parser.error("--run 必须同时指定 --case 案例ID；全量运行请明确指定 --case all")
    if not requested or requested == ["all"]:
        return dataset["cases"]
    if "all" in requested:
        parser.error("--case all 不得与其他案例 ID 混用")
    unknown = set(requested) - set(by_id)
    if unknown:
        parser.error("未知案例 ID：" + ", ".join(sorted(unknown)))
    return [by_id[case_id] for case_id in dict.fromkeys(requested)]


def prepare(dataset, selected, dataset_hash):
    path = output_path("review-bundle", "json")
    bundle = {
        "status": "仅准备离线评审材料；未调用模型；空分数不代表零分",
        "dataset_sha256": dataset_hash,
        "rubrics": dataset["rubrics"],
        "sources": dataset["sources"],
        "cases": [{"case": case, "graph_input": graph_input(case), "review": review_template(case)}
                  for case in selected],
    }
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("离线评审材料：" + str(path))
    return 0


def collect(dataset, selected, trials, dataset_hash):
    # 只在显式 --run 分支导入依赖；离线分支无需虚拟环境、登录或网络。
    sys.path.insert(0, str(PROJECT_DIR))
    from graph_builder import GRAPH_INSTRUCTIONS, KnowledgeGraph
    from llm_client import generate_text
    from model_settings import resolve_generation_config

    configuration = resolve_generation_config()
    model = configuration.model

    path = output_path("graph-collection", "jsonl")
    schema_text = json.dumps(KnowledgeGraph.model_json_schema(), sort_keys=True, ensure_ascii=False)
    print(f"将调用真实模型 {len(selected) * trials} 次；请求配置模型：{model}")
    print("本次仅采集学习图，不自动评分或宣称教学效果。结果：" + str(path))
    failures = 0
    with path.open("x", encoding="utf-8") as stream:
        for case in selected:
            prompt = graph_input(case)
            for trial in range(1, trials + 1):
                record = {
                    "case_id": case["id"], "trial": trial,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "model": model, "model_identity": "configured_request_model",
                    "provider": configuration.provider,
                    "api_format": configuration.api_format, "output_mode": configuration.output_mode,
                    "dataset_sha256": dataset_hash,
                    "prompt_sha256": sha256(prompt), "instructions_sha256": sha256(GRAPH_INSTRUCTIONS),
                    "schema_sha256": sha256(schema_text),
                    "graph_input": prompt,
                    "instructions": GRAPH_INSTRUCTIONS,
                    "schema": KnowledgeGraph.model_json_schema(),
                    "stage": "state_agnostic_graph_collection",
                    "self_reported_profiles_sent_to_model": False,
                    "review": review_template(case),
                }
                try:
                    output = generate_text(prompt, instructions=GRAPH_INSTRUCTIONS,
                                           json_schema=KnowledgeGraph.model_json_schema(),
                                           configuration=configuration)
                    if not isinstance(output, str) or len(output) > 150_000:
                        raise ValueError("Invalid graph output")
                    graph = KnowledgeGraph.model_validate_json(output)
                    if graph.study_plan is not None:
                        graph.study_plan.source_notes = [note.model_copy(update={"review_status": "unverified"})
                                                         for note in graph.study_plan.source_notes]
                        for task in [*graph.study_plan.diagnostics, *graph.study_plan.final_tasks]:
                            task.source = "generated"
                    record.update(status="collected_unreviewed", graph=graph.model_dump())
                    print(f"{case['id']} 第 {trial} 次：已采集，待数学审阅")
                except Exception as exc:
                    # 不记录异常正文、响应体或认证信息；仅记录异常类型。
                    failures += 1
                    record.update(status="request_failed", error_type=type(exc).__name__)
                    print(f"{case['id']} 第 {trial} 次：请求失败（{type(exc).__name__}）")
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
    print(f"采集结束：{len(selected) * trials - failures} 次成功，{failures} 次失败；人工分数仍为空。")
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate", action="store_true", help="离线校验（默认）")
    mode.add_argument("--prepare", action="store_true", help="离线准备人工评审表，不调用模型")
    mode.add_argument("--run", action="store_true", help="显式调用当前 MathPath 模型采集图")
    parser.add_argument("--case", action="append", dest="cases", help="案例 ID，可重复；all 表示全量")
    parser.add_argument("--trials", type=int, default=1, help="每个案例采集次数，1–10，默认 1")
    parser.add_argument("--list", action="store_true", help="列出案例 ID，不调用模型")
    args = parser.parse_args(argv)
    if not 1 <= args.trials <= 10:
        parser.error("--trials 必须在 1–10 之间")
    if args.trials != 1 and not args.run:
        parser.error("--trials 仅用于 --run")
    if args.list and (args.run or args.prepare):
        parser.error("--list 不得与 --run 或 --prepare 同时使用")
    try:
        raw = DATASET_PATH.read_bytes()
        dataset = validate_dataset(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, DatasetError) as exc:
        print("案例校验失败：" + str(exc), file=sys.stderr)
        return 2
    selected = select_cases(dataset, args.cases, parser, live=args.run)
    profiles = sum(len(case["profiles"]) for case in selected)
    print(f"离线校验通过：{len(selected)} 个数学目标，{profiles} 个模拟自报状态。")
    print("领域：" + ", ".join(f"{key}={value}" for key, value in sorted(Counter(case["domain"] for case in selected).items())))
    if args.list:
        for case in selected:
            print(case["id"] + "：" + case["title"])
        return 0
    if args.prepare:
        return prepare(dataset, selected, sha256(raw))
    if args.run:
        return collect(dataset, selected, args.trials, sha256(raw))
    print("未调用模型，未测量数学正确率或学习效果。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
