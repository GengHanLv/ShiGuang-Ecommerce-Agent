"""商品配图统一通过MCP读取实际网页；不读取旧的人工四型号图片清单。"""

import asyncio
import hashlib
import json
import re

from langchain_core.messages import HumanMessage, ToolMessage

from backend.app.agent import journal
from backend.app.rag.entities import model_keys, normalize
from backend.app.tools.registry import registry


def observation(message):
    if not isinstance(message, ToolMessage) or message.status == "error":
        return {}
    try:
        value = json.loads(message.content)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


async def resolve_product_images(messages, reply, run_id=None):
    fetch_tool = next((t for t in registry.tools if t.name == "fetch_product_page"), None)
    if fetch_tool is None:
        return []
    question = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    reference = reply + "\n" + str(question)
    mentioned = set(model_keys(reference))
    selected = []
    evidence = []

    def collect(value):
        if not value.get("model_match") or not isinstance(value.get("images"), list):
            return
        identity = value.get("model", "")
        if not mentioned.intersection(model_keys(identity)) and not (
            len(normalize(identity)) >= 3 and normalize(identity) in normalize(reference)
        ):
            return
        for image in value["images"]:
            if (
                isinstance(image, dict)
                and re.fullmatch(r"/media/[a-f0-9]{64}", str(image.get("url", "")))
                and not any(p["url"] == image["url"] for p in selected)
            ):
                selected.append({k: image[k] for k in ("model", "url", "alt", "source_url")})

    for message in messages:
        value = observation(message)
        if getattr(message, "name", "") == "fetch_product_page":
            collect(value)
        elif getattr(message, "name", "") == "web_search":
            evidence.extend(
                {**r, "source_url": r.get("url", "")}
                for r in value.get("results", [])
                if isinstance(r, dict)
            )
        elif getattr(message, "name", "") == "search_products":
            evidence.extend(value.get("evidence", []))
    if selected:
        return selected[:3]
    visited = set()
    attempted = 0
    for item in evidence:
        if not isinstance(item, dict) or not mentioned.intersection(
            item.get("model_keys") or model_keys(item.get("title", ""))
        ):
            continue
        label = re.sub(r"^【[^】]+】", "", item.get("title", ""))
        label = re.split(r"型号规格|显示与接口|续航|防护|连接|充电|芯片与|配件与", label)[
            0
        ].strip()[:100]
        if not label:
            label = item.get("model", "")
        for url in dict.fromkeys([item.get("source_url", ""), *item.get("urls", [])]):
            if not url:
                continue
            if url in visited:
                continue
            visited.add(url)
            call_id = "media:" + hashlib.sha256((url + "|" + label).encode()).hexdigest()[:24]
            args = {"url": url, "model": label}
            try:
                cached = (
                    await asyncio.to_thread(
                        journal.start_tool,
                        run_id,
                        call_id,
                        "fetch_product_page",
                        args,
                        bool((getattr(fetch_tool, "metadata", None) or {}).get("retryable")),
                    )
                    if run_id
                    else None
                )
                value = cached if cached else await registry.invoke("fetch_product_page", args)
                if not isinstance(value, dict):
                    continue
                if run_id and not cached:
                    await asyncio.to_thread(
                        journal.finish_tool, run_id, call_id, value, value.get("status") == "ok"
                    )
                collect(value)
            except asyncio.CancelledError:
                raise
            except Exception:
                if run_id:
                    await asyncio.to_thread(
                        journal.finish_tool, run_id, call_id, {"status": "unavailable"}, False
                    )
            attempted += 1
            if selected or attempted >= 2:
                return selected[:3]
    return selected[:3]
