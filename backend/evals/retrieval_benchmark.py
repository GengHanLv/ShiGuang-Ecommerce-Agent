"""调用实际检索API评测，不调用聊天模型；测试问题和结果默认保存在私有Others。"""

import argparse
import getpass
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.evals.retrieval_metrics import macro_average, score_ranking

ROOT = Path(__file__).resolve().parents[2]


def load_cases(path: Path):
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if not cases:
        raise ValueError("测试集为空")
    seen = set()
    for row in cases:
        if row["id"] in seen or not row["query"].strip() or not row["relevant_ids"]:
            raise ValueError("测试ID重复、问题为空或缺少相关证据标注")
        if len(row["relevant_ids"]) != len(set(row["relevant_ids"])):
            raise ValueError("相关证据重复")
        if row["collection"] not in {"faq", "product_knowledge"}:
            raise ValueError("集合不合法")
        if row["platform"] not in {"jd", "tmall", "pdd", "all"}:
            raise ValueError("平台不合法")
        seen.add(row["id"])
    return cases


def summarize(cases, ks):
    return {str(k): macro_average([case["runs"][str(k)]["metrics"] for case in cases]) for k in ks}


def write_reports(report, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if report["status"] != "completed":
        return
    lines = [
        "# RAG检索评测结果",
        "",
        f"评测时间：{report['started_at']}；问题数：{len(report['cases'])}。",
        "",
        "| K | Recall@K | Precision@K | MRR@K | nDCG@K |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for k, row in report["overall"].items():
        lines.append(
            f"| {k} | {row['recall']:.2%} | {row['precision']:.2%} | {row['mrr']:.4f} | {row['ndcg']:.4f} |"
        )
    lines += [
        "",
        "## 分平台结果",
        "",
        "| 平台 | 问题数 | K | Recall | Precision | MRR | nDCG |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for platform, group in report["by_platform"].items():
        for k, row in group["metrics"].items():
            lines.append(
                f"| {platform} | {group['count']} | {k} | {row['recall']:.2%} | {row['precision']:.2%} | {row['mrr']:.4f} | {row['ndcg']:.4f} |"
            )
    lines += [
        "",
        "## 解释与限制",
        "",
        report["annotation_note"],
        "",
        "每次K都单独调用真实检索接口，使用线上候选规模与缓存规则，不把Top5直接切片冒充Top3。",
        "只测检索证据，未测聊天回答正确性。未做模型调参或根据本次失败样本修改标签；不是独立人工双人全量标注。",
        "Precision分母为K，返回不足K条仍除以K；nDCG按二元标签计算；总体采用按问题宏平均。",
        "MRR@K只看前K条中第一个正确证据的位置；不是无限深度MRR。",
        "每个样本的命中ID、分数和耗时见results.json；耗时受缓存与模型冷启动影响，不作为性能压测结论。",
        "",
        "## Top3未完全召回的样本",
        "",
    ]
    if "3" in report["overall"]:
        misses = [c for c in report["cases"] if c["runs"]["3"]["metrics"]["recall"] < 1]
        lines += [
            f"- {c['id']}：{c['query']}；正确={c['relevant_ids']}；返回={c['runs']['3']['ids']}"
            for c in misses
        ] or ["无。"]
    lines += [
        "",
        "指标定义参考：[ir-measures官方文档](https://ir-measur.es/en/latest/measures.html)。",
        "",
    ]
    (output / "报告.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "Others/evaluation/rag_cases.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "Others/evaluation/latest")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--ks", nargs="+", type=int, default=[1, 3, 5])
    args = parser.parse_args()
    ks = sorted(set(args.ks))
    if not ks or min(ks) < 1 or max(ks) > 10:
        parser.error("K须在1至10之间")
    cases = load_cases(args.cases)
    # 仅在实际执行时读取应用鉴权配置，报告和日志均不记录密钥。
    from backend.app.core import config  # noqa: F401 读取本地环境配置

    username = os.getenv("EVAL_USERNAME", "admin")
    password = os.getenv("EVAL_PASSWORD") or getpass.getpass("登录密码（不会写入报告）: ")

    report = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "ks": ks,
        "annotation_note": "这是基于现有语料内容整理的目标证据回归集，标签先于本轮运行固定。相关性标签只覆盖列明的目标证据，未穷尽所有可能回答相同问题的段落。结果是相对于该标注集的召回与排序指标，不能直接宣称整个RAG准确率。",
        "cases": [],
    }
    try:
        with httpx.Client(base_url=args.base_url, timeout=240, trust_env=False) as client:
            login = client.post("/auth/login", json={"username": username, "password": password})
            login.raise_for_status()
            for path in ["/status", "/knowledge"]:
                response = client.get(path)
                response.raise_for_status()
                report[path] = response.json()
            for index, case in enumerate(cases, 1):
                item = {**case, "runs": {}}
                for k in ks:
                    begin = time.perf_counter()
                    response = client.post(
                        "/knowledge/search",
                        json={
                            "query": case["query"],
                            "collection": case["collection"],
                            "platform": case["platform"],
                            "top_k": k,
                        },
                    )
                    response.raise_for_status()
                    hits = response.json()["hits"]
                    ids = [hit.get("source_id") or "vector:" + str(hit["id"]) for hit in hits]
                    if any(
                        case["platform"] != "all" and h.get("platform") != case["platform"]
                        for h in hits
                    ):
                        raise RuntimeError("检索出现平台越界")
                    item["runs"][str(k)] = {
                        "ids": ids,
                        "elapsed_ms": round((time.perf_counter() - begin) * 1000),
                        "metrics": score_ranking(ids, set(case["relevant_ids"]), k),
                        "scores": [
                            {
                                name: h.get(name)
                                for name in ["source_id", "dense_score", "bm25_score", "rrf_score"]
                            }
                            for h in hits
                        ],
                    }
                report["cases"].append(item)
                write_reports(report, args.output)
                print(
                    f"[{index}/{len(cases)}] {case['id']} R@3={item['runs'].get('3', {}).get('metrics', {}).get('recall', '-')}",
                    flush=True,
                )
        report["overall"] = summarize(report["cases"], ks)
        report["by_platform"] = {
            platform: {"count": len(group), "metrics": summarize(group, ks)}
            for platform in sorted({c["platform"] for c in cases})
            if (group := [c for c in report["cases"] if c["platform"] == platform])
        }
        report["status"] = "completed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_reports(report, args.output)
        print(json.dumps(report["overall"], ensure_ascii=False, indent=2))
    except Exception as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        write_reports(report, args.output)
        raise


if __name__ == "__main__":
    main()
