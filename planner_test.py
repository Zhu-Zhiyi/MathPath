"""用用户生成的同调学习图演示三种模拟知识状态，不调用模型。"""

from pathlib import Path

from graph_builder import KnowledgeGraph
from planner import current_learning_status


def main():
    path = Path(__file__).resolve().parent / "examples" / "homology_graph.json"
    graph = KnowledgeGraph.model_validate_json(path.read_text(encoding="utf-8"))
    by_id = {node.id: node for node in graph.nodes}
    cases = [
        ("模拟状态 1：暂不标记任何知识点为已知", []),
        ("模拟状态 2：已掌握链", ["chains_as_formal_sums"]),
        ("模拟状态 3：已掌握链和边界算子", ["chains_as_formal_sums", "boundary_operator"]),
    ]
    for title, known_ids in cases:
        result = current_learning_status(graph, known_ids)
        print(title)
        print("当前可学候选：")
        for node_id in result.ready_ids:
            print("  " + node_id + "：" + by_id[node_id].label)
        print()
    print("本地计算完成。以上是模拟状态，不是对你的知识水平的判断。")


if __name__ == "__main__":
    main()
