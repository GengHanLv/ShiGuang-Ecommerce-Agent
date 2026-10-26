"""联网证据与图片发现：搜索摘要不冒充网页正文，只有实际抓取才产生图片资产。"""

import asyncio
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from backend.app.infrastructure.store import store
from backend.app.rag.entities import matches, model_keys, normalize, parse_scope
from backend.app.rag.metadata import metadata
from backend.app.tools.http import fetch_public, public_address

REVIEW_DOMAINS = (
    "zol.com.cn,pconline.com.cn,ithome.com,ithome.com.tw,notebookcheck.net,notebookcheck.com"
)

DEFAULT_DOMAINS = "apple.com.cn,apple.com,huawei.com,vmall.com,mi.com,xiaomi.com,lenovo.com.cn,lenovo.com,dell.com,samsung.com.cn,samsung.com,asus.com.cn,asus.com,hp.com,honor.com,oppo.com,vivo.com.cn,realme.com,oneplus.com,sony.com.cn,logitech.com,jd.com,tmall.com,yangkeduo.com,pinduoduo.com,pdd.com,acer.com,microsoft.com,meizu.com,iqoo.com,zte.com.cn,nubia.com"


def trusted_host(host):
    # 默认允许公开来源；显式配置仍可用于部署者收紧范围。
    configured = os.getenv("WEB_ALLOWED_DOMAINS", "").strip()
    if not configured:
        return bool(host)
    return bool(host) and any(
        host == d.strip() or host.endswith("." + d.strip())
        for d in configured.lower().split(",")
        if d.strip()
    )


def now():
    return datetime.now(UTC).isoformat()


def source_kind(url):
    host = urlsplit(url).hostname or ""
    if any(host == d or host.endswith("." + d) for d in REVIEW_DOMAINS.split(",")):
        return "third_party_page"
    if any(host == d or host.endswith("." + d) for d in ("jd.com", "tmall.com", "pinduoduo.com")):
        return "merchant_page"
    if any(
        host == d or host.endswith("." + d)
        for d in (DEFAULT_DOMAINS + ",edifier.com,edifier.com.cn").split(",")
    ):
        return "brand_page"
    return "third_party_page"


def relevant_rows(rows, query):
    expected = set(model_keys(query))
    selected = {}
    for row in rows:
        url = str(row.get("href", ""))
        try:
            parsed = urlsplit(url)
            if not trusted_host(parsed.hostname) or parsed.scheme not in {"http", "https"}:
                continue
        except ValueError:
            continue
        title = str(row.get("title", ""))
        body = str(row.get("body", ""))
        # 官网入口、支持首页即使在白名单内，也不能算型号检索成功。
        if expected and not expected.intersection(model_keys(title + " " + body)):
            continue
        if expected and parsed.path.rstrip("/") in {"", "/support", "/index.html"}:
            continue
        score = 2 * bool(expected.intersection(model_keys(title)))
        is_listing = (
            parsed.hostname in {"search.jd.com", "mall.jd.com"} or "/series/" in parsed.path
        )
        is_detail = parsed.hostname in {"item.jd.com", "item.m.jd.com", "item.lenovo.com.cn"}
        score += 4 * is_detail - 3 * is_listing
        score -= 2 * ("/wiki/article-" in parsed.path)
        score += bool(re.search(r"参数|配置|评测|测评|价格|商品|评析|review", title, re.I))
        selected.setdefault(
            url,
            (
                score,
                {
                    "title": title[:250],
                    "url": url,
                    "snippet": body[:900],
                    "source_type": source_kind(url),
                    "page_kind": "listing" if is_listing else "detail_or_article",
                    "evidence_type": "search_snippet",
                },
            ),
        )
    return [row for _, row in sorted(selected.values(), key=lambda pair: pair[0], reverse=True)]


async def search_provider(query, provider, count):
    if provider == "tavily":
        key = os.getenv("TAVILY_API_KEY", "")
        if not key:
            raise ValueError("尚未配置 Tavily 密钥")
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": count,
                    "search_depth": "basic",
                    "include_raw_content": False,
                },
            )
            response.raise_for_status()
            return [
                {"href": r["url"], "title": r["title"], "body": r.get("content", "")}
                for r in response.json().get("results", [])
            ]
    if provider == "bing_rss":
        _, _, raw = await fetch_public(
            "https://cn.bing.com/search?" + urlencode({"q": query, "format": "rss"}),
            accept="application/rss+xml, text/xml",
        )
        root = ET.fromstring(raw)
        return [
            {
                "href": item.findtext("link", ""),
                "title": item.findtext("title", ""),
                "body": item.findtext("description", ""),
            }
            for item in root.findall("./channel/item")
        ]
    from ddgs import DDGS

    return await asyncio.to_thread(
        lambda: DDGS(timeout=8).text(
            query,
            region="cn-zh",
            max_results=count,
            backend=os.getenv("WEB_SEARCH_BACKENDS", "auto"),
        )
    )


async def web_search(query: str, max_results: int = 5):
    if not query.strip() or len(query) > 500:
        raise ValueError("搜索内容需为1至500字")
    max_results = max(1, min(max_results, 10))
    provider = os.getenv("WEB_SEARCH_PROVIDER", "auto")
    attempts = []

    async def run(q, engine, timeout=10):
        try:
            rows = await asyncio.wait_for(search_provider(q, engine, 10), timeout=timeout)
            found = relevant_rows(rows, query)
            attempts.append(
                {"query": q, "provider": engine, "status": "ok" if found else "no_relevant_results"}
            )
            return found
        except Exception:
            attempts.append({"query": q, "provider": engine, "status": "unavailable"})
            return []

    engine = (
        ("tavily" if os.getenv("TAVILY_API_KEY") else "bing_rss")
        if provider == "auto"
        else provider
    )
    results = await run(query, engine)
    wanted = {"merchant_page"} if re.search(r"京东|jd\.com|购买|价格", query, re.I) else set()
    if re.search(r"测评|评测|性能", query):
        wanted.add("third_party_page")
    if len(results) < min(3, max_results) or not wanted.issubset(
        {r["source_type"] for r in results}
    ):
        # 有界补搜：型号资料、平台与测评分开，避免把整段自然语言当成一个搜索词。
        models = model_keys(query)
        subject = " ".join(models[:2]) if models else query[:160]
        if "三金标" in query:
            subject += " 三金标版"
        years = re.findall(r"20\d{2}", query)
        if models and years:
            subject += " " + " ".join(dict.fromkeys(years))
        elif models and re.search(r"最近|近期|最新", query):
            subject += " " + str(datetime.now(UTC).year)
        queries = (
            [subject + " 参数 配置", subject + " site:jd.com", subject + " 评测 性能"]
            if models
            else [query]
        )
        fallback = "ddgs" if provider == "auto" and engine == "bing_rss" else engine
        batches = await asyncio.gather(*(run(q, fallback, 18) for q in queries))
        results.extend(row for batch in batches for row in batch)
    unique = {row["url"]: row for row in results}
    # 先保留各类来源，再填充剩余候选，避免同一官网挤掉商品和测评。
    ordered = []
    for kind in ("brand_page", "merchant_page", "third_party_page"):
        row = next((r for r in unique.values() if r["source_type"] == kind), None)
        if row:
            ordered.append(row)
    ordered.extend(r for r in unique.values() if r not in ordered)

    async def validate(row):
        try:
            await asyncio.wait_for(public_address(row["url"]), timeout=3)
            return row
        except (ValueError, OSError, TimeoutError):
            return None

    checked = await asyncio.gather(*(validate(r) for r in ordered[:20]))
    results = [r for r in checked if r][:max_results]
    return {
        "status": "ok"
        if results
        else (
            "unavailable" if all(a["status"] == "unavailable" for a in attempts) else "no_results"
        ),
        "fetched_at": now(),
        "results": results,
        "attempts": attempts,
        "notice": "可引用摘要中的明确数据，标注来源链接及‘搜索摘要，未读取正文’；优先继续读取原文。第三方转述可以使用但不得冒充官方核实。价格、年份、配置分别陈述。",
    }


def product_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from product_objects(item)
    elif isinstance(value, dict):
        kind = value.get("@type", [])
        if kind == "Product" or isinstance(kind, list) and "Product" in kind:
            yield value
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in value:
                yield from product_objects(value[key])


async def fetch_product_page(url: str, model: str = ""):
    final, headers, raw = await fetch_public(url, limit=3_000_000, allowed=trusted_host)
    if "html" not in headers.get("content-type", "").lower():
        raise ValueError("该地址没有返回可解析的商品HTML网页")
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if re.search(r"安全验证|访问验证|验证码|access denied|captcha|just a moment", title, re.I):
        return {
            "status": "blocked",
            "url": final,
            "title": title[:500],
            "reason": "来源要求安全验证，未获得商品正文；可保留链接并读取其他来源。",
            "model_match": False,
            "images": [],
            "content": "",
            "offers": [],
            "fetched_at": now(),
        }
    products = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            products.extend(product_objects(json.loads(script.string or script.get_text())))
        except (ValueError, TypeError):
            continue
    product_names = " ".join(str(p.get("name", "")) for p in products)
    expected = model_keys(model)
    scope = parse_scope(model)

    def target_matches(label):
        meta = metadata(label)
        return matches(meta, scope) and (bool(expected) or normalize(model) in normalize(label))

    actual = model_keys(title + " " + product_names)
    if not model and len(set(actual)) == 1:
        model = str(products[0].get("name", "")) if products else title.split("|")[0].strip()
    matching_products = [p for p in products if target_matches(str(p.get("name", "")))]
    title_match = target_matches(title)
    body_match = any(
        target_matches(tag.get_text(" ", strip=True))
        for tag in soup.select("h1, h2, article p, main p")[:100]
    )
    match = bool(model) and (title_match or bool(matching_products) or body_match)
    image_urls = []
    for product in matching_products:
        value = product.get("image", [])
        if isinstance(value, str):
            value = [value]
        if isinstance(value, dict):
            value = [value.get("url", "")]
        for item in value if isinstance(value, list) else []:
            image_urls.append(item.get("url", "") if isinstance(item, dict) else item)
    for prop in ("og:image", "og:image:secure_url", "twitter:image"):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if title_match and tag and tag.get("content"):
            image_urls.append(tag["content"])
    if not image_urls:
        for tag in soup.find_all("img"):
            hint = (
                str(tag.get("alt", ""))
                + " "
                + str(tag.get("src", ""))
                + " "
                + str(tag.get("data-src", ""))
                + " "
                + str(tag.get("data-original", ""))
            )
            figure = tag.find_parent("figure")
            if figure and figure.find("figcaption"):
                hint += " " + figure.find("figcaption").get_text(" ", strip=True)
            if model and (
                set(model_keys(hint)).intersection(expected) or normalize(model) in normalize(hint)
            ):
                image_urls.append(
                    tag.get("data-src") or tag.get("data-original") or tag.get("src", "")
                )
    if title_match:
        for tag in soup.select("#spec-img, #spec-list img, .product-gallery img"):
            image_urls.append(
                tag.get("data-origin")
                or tag.get("data-src")
                or tag.get("data-original")
                or tag.get("src", "")
            )
    # 漫步者静态页把主图以 JSON 字符串数组写在脚本中；只解析数据，不执行脚本。
    host = urlsplit(final).hostname or ""
    if title_match and (host == "edifier.com" or host.endswith(".edifier.com")):
        for script in soup.find_all("script"):
            text = script.get_text()
            marker = re.search(r"\b(?:var|let|const)\s+colorarr\s*=\s*", text)
            if not marker:
                continue
            try:
                gallery, _ = json.JSONDecoder().raw_decode(text[marker.end() :])
                if isinstance(gallery, list):
                    for fragment in gallery[:1]:
                        if isinstance(fragment, str):
                            image_urls.extend(
                                img.get("src", "")
                                for img in BeautifulSoup(fragment, "html.parser").find_all("img")
                            )
            except (ValueError, TypeError):
                continue
    images = []
    if match:
        for candidate in list(dict.fromkeys(u for u in image_urls if isinstance(u, str)))[:8]:
            image = urljoin(final, candidate)
            try:
                await public_address(image)
            except (ValueError, OSError):
                continue
            if image.lower().split("?")[0].endswith(".svg"):
                continue
            identifier = hashlib.sha256((image + "|" + final + "|" + model).encode()).hexdigest()
            asset = {
                "id": identifier,
                "url": "/media/" + identifier,
                "source_url": final,
                "model": (title.split("|")[0].split("_")[0].strip() or model)[:150],
                "alt": (title[:120] or model) + " · 来源图片，具体版本及是否实拍请以原文为准",
                "fetched_at": now(),
            }
            with store.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO web_assets VALUES(?,?,?,?,?,?)",
                    (identifier, image, final, asset["model"], asset["alt"], asset["fetched_at"]),
                )
            images.append(asset)
            if len(images) == 3:
                break
    published = ""
    tag = soup.find("meta", property="article:published_time") or soup.find(
        "meta", attrs={"name": "datePublished"}
    )
    if tag:
        published = str(tag.get("content", ""))[:64]
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        tag.decompose()
    content = soup.get_text("\n", strip=True)
    content = re.sub(r"\n{3,}", "\n\n", content)[:18000]
    offers = [p.get("offers") for p in matching_products if p.get("offers")]
    # offers保留原结构和币种/有效期，不能把多个SKU的价格拼成一个确定成交价。
    return {
        "status": "ok",
        "url": final,
        "title": title[:500],
        "model": model,
        "model_match": match,
        "match_scope": "型号相关；年份、容量及特别版本需按原文分别核对",
        "content": content,
        "offers": offers[:5],
        "images": images,
        "published_at": published,
        "effective_at": "",
        "reviewed_at": "",
        "fetched_at": now(),
        "source_type": source_kind(final),
        "evidence_type": "fetched_" + source_kind(final),
    }
