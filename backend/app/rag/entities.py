"""型号与版本解析：保留 Pro/Plus/Ultra 等后缀，不以子串包含代替型号相等。"""

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field

PATTERNS = [
    r"(?:拯救者\s*)?[yr]\s*[79]000\s*[pxk](?:\s*(?:至尊版|至尊|se|iax|irx))?",
    r"iphone\s*\d{1,2}\s*(?:pro\s*max|pro|plus|mini|e)?",
    r"airpods\s*(?:pro\s*)?(?:\d+|max)",
    r"freebuds\s*(?:pro\s*)?\d+[a-z]?",
    r"wh[ -]?\d{4}xm\d+",
    r"mx\s*(?:master|anywhere)\s*\d+s?",
    r"galaxy\s*(?:s\s*\d{1,2}\s*(?:ultra|plus|fe|\+)?|z\s*(?:fold|flip)\s*\d+|a\s*\d{2})",
    r"(?:小米|xiaomi)\s*\d{1,2}\s*(?:ultra|pro|s)?",
    r"(?:redmi|红米)\s*(?:note\s*)?[ak]\d{1,3}\s*(?:pro\+?|ultra|至尊版)?",
    r"(?:huawei\s*)?(?:pura|mate|nova)\s*\d{1,3}\s*(?:pro\+?|ultra|plus)?",
    r"thinkpad\s*[a-z]\d{2}\s*(?:gen\s*\d+)?",
    r"(?:戴尔\s*)?xps\s*\d{2}",
    r"(?:小新|yoga)\s*(?:pro\s*)?[a-z]?\d{2,4}[a-z]?",
    r"(?:macbook\s*(?:air|pro)|mac\s*mini)\s*(?:\d{2}\s*英寸\s*)?(?:m\d+\s*(?:pro|max)?)?",
    r"(?:oppo\s*)?find\s*[xn]\d+\s*(?:pro|ultra|mini)?",
    r"(?:vivo\s*)?[xs]\d{2,3}\s*(?:pro\+?|ultra)?",
    r"iqoo\s*(?:neo\s*)?\d+\s*(?:pro|s)?",
    r"(?:荣耀|honor)\s*magic\s*\d+\s*(?:pro|ultimate|至臻版)?",
    r"(?:一加|oneplus)\s*(?:ace\s*)?\d+\s*(?:pro|t|r)?",
]


def normalize(value):
    value = (
        unicodedata.normalize("NFKC", value)
        .casefold()
        .replace("小米", "xiaomi")
        .replace("红米", "redmi")
    )
    return re.sub(r"[\s\-（）()，,英寸]", "", value)


def model_keys(text):
    recognized = [m for pattern in PATTERNS for m in re.finditer(pattern, text, re.I)]
    result = [normalize(m.group()) for m in recognized]
    # 带品牌与省略品牌的拯救者型号使用同一键；至尊版不与标准版合并。
    result = [re.sub(r"^拯救者(?=[yr][79]000)", "", key) for key in result]
    result = list(dict.fromkeys(result))
    spans = [m.span() for m in recognized]
    # 常见省略品牌写法也保留完整版本后缀，不能退化成宽泛基础型号。
    result += [key.removeprefix("galaxy") for key in result if key.startswith("galaxy")]
    result += [
        key.removeprefix("huawei")
        for key in result
        if key.startswith("huaweimate") or key.startswith("huaweipura")
    ]
    # iPad 的芯片与系列比“11英寸”更能确定型号，避免 A16 与 Pro/Air 串用。
    for match in re.finditer(r"ipad(?:\s*(?:air|pro|mini))?[^\n。；]{0,24}", text, re.I):
        part = match.group()
        series = re.match(r"ipad(?:\s*(?:air|pro|mini))?", part, re.I).group()
        chip = re.search(r"\b(a\d{2}|m\d+)\b", part, re.I)
        if chip:
            result.append(normalize(series + chip.group()))
        else:
            result.append(normalize(series))
        spans.append(match.span())
    # 非预置品牌的新型号仍可提取字母数字型号；排除接口、防护、芯片与文档编号。
    for match in re.finditer(
        r"\b[a-z]{1,12}[ -]?\d{1,4}[a-z0-9]*(?:\s*(?:pro\s*max|pro|max|ultra|plus|fe))?\b",
        text,
        re.I,
    ):
        if any(start <= match.start() and match.end() <= end for start, end in spans):
            continue
        key = normalize(match.group())
        if not re.match(r"^(?:usb|ip|hdmi|ep|gb|tb|p|f)\d|^[am]\d+$", key):
            result.append(key)
    return list(dict.fromkeys(result))


@dataclass
class ProductScope:
    models: list[str] = field(default_factory=list)
    variant: str = ""
    capacity: str = ""
    year: int = 0

    def json(self):
        return asdict(self)


def parse_scope(text):
    variant = "business" if re.search(r"商用|商务版|for\s+business", text, re.I) else ""
    if re.search(r"标准版|普通版", text):
        variant = "standard"
    if re.search(r"airpods\s*4", text, re.I) and re.search(r"主动降噪版|主动降噪款", text):
        variant = "anc"
    sizes = list(re.finditer(r"(?<![\d.])(\d{1,4})\s*(gb|tb)\b", text, re.I))
    capacity = (
        max(sizes, key=lambda m: int(m.group(1)) * (1024 if m.group(2).lower() == "tb" else 1))
        if sizes
        else None
    )
    year = re.search(r"(20\d{2})\s*(?:年款|款|版)|(?:型号年份|机型年份)[：:]?\s*(20\d{2})", text)
    return ProductScope(
        model_keys(text),
        variant,
        normalize(capacity.group()) if capacity else "",
        int(next(g for g in year.groups() if g)) if year else 0,
    )


def matches(meta, scope):
    if scope.models and not set(scope.models).intersection(meta.get("model_keys", [])):
        return False
    # 未明确记录版本/容量/年份时仍可作为通用参数资料，充分性层会标出缺项。
    if scope.variant and meta.get("variant") and scope.variant != meta["variant"]:
        return False
    if scope.capacity and meta.get("capacities") and scope.capacity not in meta["capacities"]:
        return False
    return not (scope.year and meta.get("model_year") and scope.year != meta["model_year"])


def scalar_filter(scope, platform="all"):
    def quote(value):
        return json.dumps(value, ensure_ascii=False)

    parts = []
    if platform != "all":
        parts.append("platform == " + quote(platform))
    if scope.models:
        parts.append(
            "("
            + " or ".join("array_contains(model_keys, " + quote(m) + ")" for m in scope.models)
            + ")"
        )
    if scope.variant:
        parts.append("(variant == " + quote(scope.variant) + ' or variant == "")')
    if scope.capacity:
        parts.append(
            "(array_contains(capacities, "
            + quote(scope.capacity)
            + ") or array_length(capacities) == 0)"
        )
    if scope.year:
        parts.append(f"(model_year == {scope.year} or model_year == 0)")
    return " and ".join(parts)
