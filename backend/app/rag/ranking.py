"""独立BM25召回与RRF融合；不把排序分数当作余弦相似度。"""

import math
import re
from collections import Counter

STOP = {
    "京东",
    "天猫",
    "多多",
    "怎么",
    "什么",
    "是否",
    "商品",
    "问题",
    "资料",
    "知识",
    "支持",
    "一下",
    "可以",
    "多少",
    "的是",
    "如何",
    "请问",
    "这个",
}


def tokenize(text):
    # 型号统一连字符/空格写法，中文使用二字词，完全离线可复现。
    text = re.sub(r"(?<=[a-z0-9])[- ](?=[a-z0-9])", "", text.lower())
    parts = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text)
    tokens = []
    for part in parts:
        if re.fullmatch(r"[a-z0-9]+", part):
            tokens.append(part)
        elif len(part) == 1:
            continue
        else:
            tokens.extend(part[i : i + 2] for i in range(len(part) - 1))
    return [token for token in tokens if token not in STOP]


def bm25(query, rows, limit=15):
    terms = set(tokenize(query))
    if not terms or not rows:
        return []
    docs = [Counter(tokenize(row["text"].split("来源：")[0])) for row in rows]
    lengths = [sum(doc.values()) for doc in docs]
    average = sum(lengths) / max(len(docs), 1) or 1
    df = {t: sum(t in doc for doc in docs) for t in terms}
    scored = []
    for row, doc, length in zip(rows, docs, lengths):
        score = 0
        for term in terms:
            frequency = doc.get(term, 0)
            if frequency:
                idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
                score += (
                    idf * (frequency * 2.5) / (frequency + 1.5 * (0.25 + 0.75 * length / average))
                )
        if score > 0:
            scored.append((str(row["vector_id"]), score))
    return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]


def reciprocal_rank_fusion(dense, sparse, k=60):
    scores = {}
    for listing in [dense, sparse]:
        for rank, (identifier, _) in enumerate(listing, 1):
            scores[identifier] = scores.get(identifier, 0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
