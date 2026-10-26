"""常用检索指标。仅依赖标准库，标签为二元相关性，返回0至1的小数。"""

import math


def score_ranking(ranked_ids: list[str], relevant_ids: set[str], k: int) -> dict[str, float]:
    """Precision分母固定为K；MRR在K处截断；nDCG使用二元相关性。"""
    if k < 1 or not relevant_ids:
        raise ValueError("K须为正整数，且每个问题至少标注一条相关证据")
    if len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError("排序结果不能包含重复证据编号")
    relevance = [identifier in relevant_ids for identifier in ranked_ids[:k]]
    hits = sum(relevance)
    reciprocal = next((1.0 / rank for rank, hit in enumerate(relevance, 1) if hit), 0.0)
    dcg = sum(1.0 / math.log2(rank + 1) for rank, hit in enumerate(relevance, 1) if hit)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant_ids)) + 1))
    return {
        "recall": hits / len(relevant_ids),
        "precision": hits / k,
        "mrr": reciprocal,
        "ndcg": dcg / ideal,
    }


def macro_average(scores: list[dict[str, float]]) -> dict[str, float]:
    """每个问题权重相同，避免相关文档多的问题支配总体结果。"""
    if not scores:
        raise ValueError("不能对空测试集评分")
    return {
        name: sum(row[name] for row in scores) / len(scores)
        for name in ["recall", "precision", "mrr", "ndcg"]
    }
