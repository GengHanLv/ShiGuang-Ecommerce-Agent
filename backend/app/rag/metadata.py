"""来源日期各自保留语义，核验时间不能自动充当发布日期或生效日期。"""

import re

from backend.app.rag.entities import model_keys, normalize, parse_scope

SCALAR_FIELDS = (
    "platform",
    "source_id",
    "title",
    "source_url",
    "brand",
    "model",
    "variant",
    "model_year",
    "model_keys",
    "capacities",
    "published_at",
    "effective_at",
    "reviewed_at",
    "document_id",
)


def metadata(text):
    lines = text.splitlines()
    title = lines[0][:500] if lines else ""
    platform = next(
        (
            key
            for marker, key in [("京东", "jd"), ("天猫", "tmall"), ("拼多多", "pdd")]
            if re.search(r"(?:^|\n)【" + marker + r"知识｜", text)
        ),
        "generic",
    )
    identifier = re.search(r"【[^\n]+｜([A-Z]+-[PF]-\d+)】", text)
    doc = re.search(r"\[document_id:([a-f0-9]+)\]", text)
    # 上传分块的父标题写在单独行中，不能把整篇其它产品的型号塞进当前分块。
    heading = re.search(r"(?:^|\n)(?:商品型号|章节标题|型号)[：:]\s*([^\n]+)", text)
    identity_text = heading.group(1) if heading else title
    keys = model_keys(identity_text)
    if not keys:
        # 无标题上传文本仅接受正文前250字的显式型号，仍保留所有检出的版本。
        keys = model_keys(text[:250])
    for key in list(keys):
        family = re.match(r"^(ipad(?:pro|air|mini)?)[am]\d+$", key)
        if family and family.group(1) not in keys:
            keys.append(family.group(1))
    scope = parse_scope(identity_text)
    urls = list(
        dict.fromkeys(u.rstrip(").,;") for u in re.findall(r"https?://[^\s；，）\]<>]+", text))
    )

    def date(labels):
        match = re.search("(?:" + labels + r")[：:]?\s*(20\d{2}[-/]\d{1,2}[-/]\d{1,2})", text)
        return match.group(1).replace("/", "-") if match else ""

    brand = next(
        (
            name
            for word, name in [
                ("iphone", "apple"),
                ("ipad", "apple"),
                ("airpods", "apple"),
                ("macbook", "apple"),
                ("freebuds", "huawei"),
                ("华为", "huawei"),
                ("galaxy", "samsung"),
                ("小米", "xiaomi"),
                ("redmi", "xiaomi"),
                ("thinkpad", "lenovo"),
                ("联想", "lenovo"),
                ("xps", "dell"),
                ("戴尔", "dell"),
                ("wh-", "sony"),
                ("索尼", "sony"),
                ("mx master", "logitech"),
                ("mx anywhere", "logitech"),
            ]
            if word in identity_text.casefold()
        ),
        "",
    )
    return {
        "platform": platform,
        "source_id": identifier.group(1) if identifier else (doc.group(1) if doc else ""),
        "title": title,
        "urls": urls,
        "source_url": urls[0] if urls else "",
        "brand": brand,
        "model": keys[0] if len(keys) == 1 else "",
        "model_keys": keys,
        "variant": scope.variant,
        "model_year": scope.year,
        "capacities": list(
            dict.fromkeys(
                normalize(m.group())
                for m in re.finditer(r"(?<![\d.])\d{1,4}\s*(?:GB|TB)\b", text, re.I)
            )
        ),
        "published_at": date("发布日期|发布于|发布时间"),
        "effective_at": date("生效日期|施行日期|实施日期"),
        "reviewed_at": date("核验日期|整理日期"),
        "document_id": doc.group(1) if doc else "",
    }


def scalar_values(text, extra=None):
    meta = metadata(text)
    if extra:
        meta.update({k: v for k, v in extra.items() if k in SCALAR_FIELDS})
    return {key: meta[key] for key in SCALAR_FIELDS}
