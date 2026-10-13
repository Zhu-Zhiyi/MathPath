"""在模型生成的教学图内选择需学节点最少的一条 AND/OR 路线。

每个未知节点按一个单位计数，共享先修只计一次；结果不代表真实数学学习
所需时间最短，也不证明模型图完整或正确。已掌握由用户自报，作为展开边界，
不会反推其祖先也已掌握。空先修只表示本图未继续展开，不表示无需学习。
"""

from functools import lru_cache
from itertools import combinations
from typing import Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from graph_builder import KnowledgeGraph, NodeId


class PlanError(Exception):
    pass


class ChosenGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    node_id: NodeId
    group_index: int = Field(ge=0)


class LearningStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_id: NodeId
    known_ids: list[NodeId]
    ready_ids: list[NodeId]
    blocked_ids: list[NodeId]
    required_ids: list[NodeId]
    recommended_ids: list[NodeId]
    selected_ids: list[NodeId]
    selected_groups: list[ChosenGroup]
    focus_id: NodeId | None
    completed: bool
    planning_known_ids: list[NodeId] = Field(default_factory=list)
    mode: Literal["intuition", "application", "proof", "repair"] | None = None
    explanation: str = ""


def _select_subgraph(by_id, target_id, known, original_order):
    """精确枚举至多 12 个节点的未知子集，并重建一条可行的依赖展开。"""
    unknown_ids = [node_id for node_id in original_order if node_id not in known and node_id != target_id]
    # 目标尚未掌握，必然在需学集合内；同大小子集按原节点顺序稳定选择。
    for other_count in range(len(unknown_ids) + 1):
        for others in combinations(unknown_ids, other_count):
            allowed_unknown = set(others) | {target_id}

            @lru_cache(maxsize=None)
            def achievable(node_id):
                if node_id in known:
                    return True
                if node_id not in allowed_unknown:
                    return False
                groups = by_id[node_id].prerequisite_sets
                return not groups or any(all(achievable(prerequisite) for prerequisite in group) for group in groups)

            if not achievable(target_id):
                continue

            selected = set()
            chosen_groups = {}

            def visit(node_id):
                if node_id in selected:
                    return
                selected.add(node_id)
                # 已知高级知识只是边界，不继续展开未掌握的祖先。
                if node_id in known:
                    return
                groups = by_id[node_id].prerequisite_sets
                for group_index, group in enumerate(groups):
                    if all(achievable(prerequisite) for prerequisite in group):
                        chosen_groups[node_id] = group_index
                        for prerequisite in group:
                            visit(prerequisite)
                        return

            visit(target_id)
            # 子集已是全局最小；任何可行重建若漏掉某未知成员，就会形成更小
            # 的可行子集。因此按组顺序选择可行分支不会重复计算共享先修，
            # 也不会变成分别求每个节点的局部最小后再相加。
            return selected, chosen_groups
    raise PlanError("当前图无法构建可行的学习路线")


def _strict_learning_status(graph: KnowledgeGraph, known_ids: list[str]) -> LearningStatus:
    """返回全部直接可学候选，以及一条在本图内需学节点最少的推荐路线。"""
    by_id = {node.id: node for node in graph.nodes}
    known = set(known_ids)
    if len(known) != len(known_ids):
        raise PlanError("已知节点列表含有重复 ID")
    unknown = known - set(by_id)
    if unknown:
        raise PlanError("已知节点列表中的 ID 不在图中：" + ", ".join(sorted(unknown)))

    digraph = nx.DiGraph()
    digraph.add_nodes_from(by_id)
    for node in graph.nodes:
        for group in node.prerequisite_sets:
            digraph.add_edges_from((prerequisite, node.id) for prerequisite in group)
    # 边的方向是先修 -> 待学知识点；只保留目标及能通向目标的节点。
    relevant = nx.ancestors(digraph, graph.target_id) | {graph.target_id}
    position = {node.id: index for index, node in enumerate(graph.nodes)}
    order = list(nx.lexicographical_topological_sort(digraph.subgraph(relevant), key=position.__getitem__))
    known_ordered = [node_id for node_id in order if node_id in known]
    if graph.target_id in known:
        return LearningStatus(target_id=graph.target_id, known_ids=known_ordered,
                              ready_ids=[], blocked_ids=[], required_ids=[], recommended_ids=[],
                              selected_ids=[graph.target_id], selected_groups=[], focus_id=None, completed=True)

    ready, blocked = [], []
    for node_id in order:
        if node_id in known:
            continue
        groups = by_id[node_id].prerequisite_sets
        # 外层 OR，内层 AND；根节点只是图中没有建模先修，仍然是未知节点。
        satisfied = not groups or any(set(group).issubset(known) for group in groups)
        (ready if satisfied else blocked).append(node_id)
    selected, chosen_groups = _select_subgraph(by_id, graph.target_id, known, list(by_id))
    selected_ordered = [node_id for node_id in order if node_id in selected]
    required = [node_id for node_id in selected_ordered if node_id not in known]
    ready_set = set(ready)
    recommended = [node_id for node_id in required if node_id in ready_set]
    selected_groups = [ChosenGroup(node_id=node_id, group_index=chosen_groups[node_id])
                       for node_id in selected_ordered if node_id in chosen_groups]
    return LearningStatus(target_id=graph.target_id, known_ids=known_ordered,
                          ready_ids=ready, blocked_ids=blocked, required_ids=required,
                          recommended_ids=recommended, selected_ids=selected_ordered,
                          selected_groups=selected_groups, focus_id=recommended[0] if recommended else None,
                          completed=False)


def current_learning_status(graph: KnowledgeGraph, known_ids: list[str], *, mode=None, mastery=None) -> LearningStatus:
    """Keep self-reported full mastery separate from mode-specific prerequisite boundaries."""
    if mode is None:
        result = _strict_learning_status(graph, known_ids)
        return result.model_copy(update={"planning_known_ids": list(result.known_ids),
            "explanation": "按自行标记全部掌握的节点计算先修；路线只比较需学节点数量。"})
    requirements = {
        "intuition": ("definition", "intuition"),
        "application": ("definition", "application"),
        "proof": ("definition", "intuition", "application"),
        "repair": ("definition", "intuition", "application"),
    }
    if mode not in requirements:
        raise PlanError("学习模式无效")
    by_id = {node.id: node for node in graph.nodes}
    reported = set(known_ids)
    if len(reported) != len(known_ids) or not reported <= set(by_id):
        raise PlanError("掌握标记必须对应本图中不同的知识点")
    mastery = mastery or {}
    if not isinstance(mastery, dict) or not set(mastery) <= set(by_id):
        raise PlanError("能力标记引用了当前地图之外的知识点")
    dimensions = {"definition", "intuition", "application"}
    planning_known = set(reported)
    for node_id, state in mastery.items():
        if hasattr(state, "model_dump"):
            state = state.model_dump()
        if (not isinstance(state, dict) or set(state) - dimensions
                or any(type(value) is not bool for value in state.values())):
            raise PlanError("能力标记必须为布尔值")
        required = tuple(getattr(by_id[node_id], "required_dimensions", []) or requirements[mode])
        if all(state.get(dimension, False) for dimension in required):
            planning_known.add(node_id)
    result = _strict_learning_status(graph, [node.id for node in graph.nodes if node.id in planning_known])
    description = {"intuition": "定义与直觉", "application": "定义与使用",
                   "proof": "定义、直觉与使用", "repair": "定义、直觉与使用"}[mode]
    return result.model_copy(update={
        "known_ids": [node_id for node_id in result.known_ids if node_id in reported],
        "planning_known_ids": list(result.known_ids), "mode": mode,
        "explanation": f"当前按自报的{description}安排先修；节点有明确能力要求时按该要求。"
                       "这些标记不等于独立检验通过，路线只比较需学节点数量。",
    })
