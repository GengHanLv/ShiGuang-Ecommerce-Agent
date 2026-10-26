"""本地知识资料加载、来源校验与可读文本；不依赖模型或数据库。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from backend.app.core.config import KNOWLEDGE_DIR

CORPUS_DIR = KNOWLEDGE_DIR / "jd"
COLLECTIONS = ("product_knowledge", "faq")
LEGACY_DEMO_TEXTS = (
    "蓝牙耳机：支持降噪，蓝牙5.3，续航20小时，Type-C充电",
    "机械键盘：87键青轴，RGB背光，USB有线连接，1年质保",
    "如何退货：7天内无理由退货，需保持商品完好，联系我们客服获取退货地址",
    "发货时间：下单后48小时内发货，顺丰包邮",
    "客服电话：400-123-4567",
)


def load_corpus(directory: Path = CORPUS_DIR):
    sources_list = json.loads((directory / "sources.json").read_text(encoding="utf-8-sig"))
    sources = {source["id"]: source for source in sources_list}
    if len(sources) != len(sources_list):
        raise ValueError("来源编号重复")
    records = []
    seen_ids, seen_contents = set(), set()
    for collection in COLLECTIONS:
        for line_no, line in enumerate(
            (directory / f"{collection}.jsonl").read_text(encoding="utf-8-sig").splitlines(), 1
        ):
            if not line.strip():
                continue
            record = json.loads(line)
            required = {
                "id",
                "title",
                "question",
                "content",
                "category",
                "scope",
                "content_type",
                "source_ids",
                "reviewed_at",
            }
            if not required.issubset(record):
                raise ValueError(f"{collection}:{line_no} 缺少必需字段")
            if record.get("collection") != collection or not re.fullmatch(
                r"JD-[PF]-\d{4}", record["id"]
            ):
                raise ValueError("集合或知识编号无效")
            if record["id"] in seen_ids or record["content"] in seen_contents:
                raise ValueError(f"重复知识: {record['id']}")
            if not all(
                isinstance(record[k], str) and record[k].strip()
                for k in (
                    "title",
                    "question",
                    "content",
                    "category",
                    "scope",
                    "content_type",
                    "reviewed_at",
                )
            ):
                raise ValueError("知识字段必须为非空字符串")
            if len(record["content"]) < 20:
                raise ValueError("知识正文过短")
            if not record["source_ids"] and record["content_type"] != "editorial_selection_guide":
                raise ValueError(f"{record['id']} 官方事实缺少来源")
            for source_id in record["source_ids"]:
                source = sources.get(source_id)
                if (
                    not source
                    or source.get("verification") != "online_read"
                    or not source["url"].startswith("https://")
                ):
                    raise ValueError(f"{record['id']} 来源未核验")
            seen_ids.add(record["id"])
            seen_contents.add(record["content"])
            records.append(record)
    return records, sources


def embedding_text(record: dict) -> str:
    return f"京东 {record['category']}\n{record['title']}\n问题：{record['question']}\n{record['content']}\n适用：{record['scope']}"


def render_record(record: dict, sources: dict) -> str:
    evidence = {
        "official_policy_summary": "京东官方规则摘要",
        "verified_model_card": "已核验型号资料，非实时在售或库存承诺",
        "editorial_selection_guide": "人工编写选购建议，不是具体SKU参数或京东官方承诺",
        "editorial_workflow": "结合京东场景编写的操作建议",
    }[record["content_type"]]
    urls = (
        "；".join(sources[s]["url"] for s in record["source_ids"]) or "项目人工策划，无外部事实来源"
    )
    return (
        f"【京东知识｜{record['id']}】{record['title']}\n"
        f"问题：{record['question']}\n回答：{record['content']}\n"
        f"适用：{record['scope']}\n依据：{evidence}\n核验日期：{record['reviewed_at']}\n来源：{urls}"
    )


def record_id(text: str) -> str | None:
    match = re.match(r"【京东知识｜(JD-[PF]-\d{4})】", text)
    return match.group(1) if match else None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def active_retrieval_filter(directory: Path = CORPUS_DIR) -> str:
    """导入完成后只排除明确的旧演示文本；不删除旧数据，不影响其他上传。"""
    policy_file = directory / "retrieval_policy.json"
    if not policy_file.exists():
        return ""
    policy = json.loads(policy_file.read_text(encoding="utf-8"))
    if not policy.get("active"):
        return ""
    texts = policy.get("excluded_texts", [])
    if not isinstance(texts, list) or not all(
        isinstance(t, str) and t in LEGACY_DEMO_TEXTS for t in texts
    ):
        raise ValueError("检索排除策略包含非演示数据")
    return "text not in " + json.dumps(texts, ensure_ascii=False) if texts else ""
