"""多平台官方资料校验。资料正文留在本地knowledge_base，不随源码发布。"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from backend.app.core.config import KNOWLEDGE_DIR

PLATFORMS = {"tmall": ("天猫", "TM"), "pdd": ("拼多多", "PDD")}
OFFICIAL_DOMAINS = {
    "tmall.com",
    "alicdn.com",
    "yangkeduo.com",
    "pinduoduo.com",
    "apple.com.cn",
    "apple.com",
    "huawei.com",
    "sony.com.cn",
    "logitech.com",
    "samsung.com",
    "mi.com",
}


def load_platform(platform, directory=None):
    if platform not in PLATFORMS:
        raise ValueError("只支持tmall或pdd")
    directory = Path(directory or KNOWLEDGE_DIR / platform)
    sources = {
        s["id"]: s for s in json.loads((directory / "sources.json").read_text(encoding="utf-8"))
    }
    records = []
    identifiers = set()
    contents = set()
    for collection in ["product_knowledge", "faq"]:
        for line in (directory / f"{collection}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["platform"] != platform or row["collection"] != collection:
                raise ValueError("平台或集合不匹配")
            if not re.fullmatch(PLATFORMS[platform][1] + r"-[PF]-\d{4}", row["id"]):
                raise ValueError("编号无效")
            if row["id"] in identifiers or row["content"] in contents:
                raise ValueError("知识重复")
            if len(row["content"]) < 70:
                raise ValueError("正文过短")
            if not row["source_ids"]:
                raise ValueError("没有官方来源")
            for source_id in row["source_ids"]:
                source = sources[source_id]
                host = urlparse(source["url"]).hostname or ""
                if not source["url"].startswith("https://") or not any(
                    host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS
                ):
                    raise ValueError("非官方域名")
                if source["verification"] != "official_content_reviewed":
                    raise ValueError("来源未核验")
            identifiers.add(row["id"])
            contents.add(row["content"])
            records.append(row)
    return records, sources


def render_platform(row, sources):
    label = PLATFORMS[row["platform"]][0]
    links = "；".join(sources[s]["url"] for s in row["source_ids"])
    return (
        f"【{label}知识｜{row['id']}】{row['title']}\n问题：{row['question']}\n回答：{row['content']}\n"
        f"适用：{row['scope']}\n依据：{row['content_type']}\n核验日期：{row['reviewed_at']}\n来源：{links}"
    )


def managed_id(text):
    found = re.match(r"【(?:天猫|拼多多)知识｜((?:TM|PDD)-[PF]-\d{4})】", text)
    return found.group(1) if found else None


def render_documents(platform, records, sources):
    """根据JSONL重建阅读版和校验清单，避免人工修改后文档与主数据脱节。"""
    import hashlib

    directory = KNOWLEDGE_DIR / platform
    for collection in ["product_knowledge", "faq"]:
        title = PLATFORMS[platform][0] + (
            "商品型号资料" if collection == "product_knowledge" else "常见问题"
        )
        sections = ["# " + title + "\n\n核验日期2026-10-19。官方内容摘要；非全站实时SKU数据库。"]
        for row in records:
            if row["collection"] != collection:
                continue
            links = "\n".join(
                f"- [{sources[k]['title']}]({sources[k]['url']})" for k in row["source_ids"]
            )
            sections.append(
                f"## {row['id']} {row['title']}\n\n{row['content']}\n\n适用范围：{row['scope']}\n\n{links}"
            )
        (directory / f"{collection}.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    files = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ["sources.json", "product_knowledge.jsonl", "faq.jsonl"]
    }
    manifest = {
        "platform": platform,
        "reviewed_at": "2026-10-19",
        "product_knowledge": sum(r["collection"] == "product_knowledge" for r in records),
        "faq": sum(r["collection"] == "faq" for r in records),
        "sources": len(sources),
        "sha256": files,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
