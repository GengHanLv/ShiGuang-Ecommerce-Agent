"""
长期记忆回归用例：规则层可本地跑，不依赖 LLM/Milvus。
"""
from __future__ import annotations

import sys

from long_term_memory import _is_noise_memory_text, _should_attempt_extract, _topic_key
from memory_signals import (
    is_memory_delete,
    is_memory_update,
    is_order_lookup_intent,
    is_preference_query,
    is_preference_utterance,
    is_stating_new_preference,
    should_inject_memory,
)


CASES = [
    {"id": "W1", "msg": "记住我以后都晚上收货", "expect": {"extract": True, "inject": False}},
    {"id": "W2", "msg": "快递到了请打电话通知我", "expect": {"extract": True, "inject": False}},
    {"id": "W3", "msg": "以后我的快递都用顺丰", "expect": {"extract": True, "inject": False}},
    {"id": "W4", "msg": "别早上送，我想晚间收货", "expect": {"extract": True, "inject": False}},
    {
        "id": "W5",
        "msg": "以后我的快递到了请打电话给我，防止我漏看订单信息",
        "expect": {"extract": True, "inject": False, "pref": True, "order": False},
    },
    {"id": "S1", "msg": "查一下我的订单", "expect": {"extract": False, "order": True, "inject": True}},
    {"id": "S2", "msg": "订单号 123456 到哪了", "expect": {"extract": False, "order": True}},
    {"id": "S3", "msg": "讲个笑话", "expect": {"extract": False, "order": False, "inject": True}},
    {"id": "S4", "msg": "怎么退货", "expect": {"extract": False}},
    {"id": "S5", "msg": "你好", "expect": {"extract": False}},
    {"id": "Q1", "msg": "我的收货偏好是什么", "expect": {"inject": True, "extract": False}},
    {"id": "Q2", "msg": "你记住了什么", "expect": {"inject": True, "extract": False}},
    {"id": "Q3", "msg": "我指定什么快递", "expect": {"inject": True, "extract": False}},
    {"id": "Q4", "msg": "你记得我有什么偏好吗？", "expect": {"inject": True, "extract": False, "pref_query": True}},
    {"id": "O1", "msg": "我的订单状态", "expect": {"inject": True, "order": True}},
    {"id": "O2", "msg": "你知道我买了什么吗", "expect": {"inject": True, "order": True}},
    {"id": "O3", "msg": "请告诉我我的订单信息", "expect": {"order": True, "pref": False, "inject": True}},
    {"id": "O4", "msg": "什么时候能收到货？", "expect": {"order": True, "inject": True, "stating_new": False}},
    {"id": "U1", "msg": "以后改成早上收货", "expect": {"update": True, "inject": False, "extract": True}},
    {"id": "U2", "msg": "换成顺丰快递", "expect": {"update": True, "inject": False}},
    {"id": "U3", "msg": "不要用圆通了，改成顺丰", "expect": {"update": True, "inject": False}},
    {"id": "D1", "msg": "取消电话通知", "expect": {"delete": True, "inject": False}},
    {"id": "D2", "msg": "不用记住我的偏好了", "expect": {"delete": True, "inject": False}},
    {"id": "D3", "msg": "不要顺丰了", "expect": {"delete": True, "inject": False}},
    {"id": "D4", "msg": "删除偏好", "expect": {"delete": True, "inject": False}},
]

NOISE_TEXTS = [
    ("用户查询了订单状态", True),
    ("订单号123已发货", True),
    ("用户偏好晚间收货", False),
    ("快递到货请电话通知", False),
]

TOPIC_CASES = [
    ("用户偏好晚间收货", "recv_time"),
    ("用户偏好白天收货", "recv_time"),
    ("用户偏好快递白天送达", "recv_time"),
    ("希望快递以后都是晚上送达", "recv_time"),
    ("快递到达时请打电话通知我", "phone_notify"),
    ("快递到达时不需要电话通知", "phone_notify"),
    ("以后只用顺丰快递", "express_co"),
]


def run() -> int:
    failed = []
    for c in CASES:
        msg = c["msg"]
        exp = c["expect"]
        got = {
            "extract": _should_attempt_extract(msg) or is_memory_update(msg),
            "inject": should_inject_memory(msg, True),
            "delete": is_memory_delete(msg),
            "update": is_memory_update(msg),
            "pref_query": is_preference_query(msg),
            "stating_new": is_stating_new_preference(msg),
            "pref": is_preference_utterance(msg),
            "order": is_order_lookup_intent(msg),
        }
        for k, v in exp.items():
            if got.get(k) is not v:
                failed.append((c["id"], msg, k, v, got.get(k)))

    for text, is_noise in NOISE_TEXTS:
        got = _is_noise_memory_text(text)
        if got is not is_noise:
            failed.append(("NOISE", text, "noise", is_noise, got))

    for text, topic in TOPIC_CASES:
        got = _topic_key(text)
        if got != topic:
            failed.append(("TOPIC", text, "topic", topic, got))
    if _topic_key("晚间收货") == _topic_key("打电话通知"):
        failed.append(("TOPIC", "cross", "distinct", True, False))

    total = len(CASES) + len(NOISE_TEXTS) + len(TOPIC_CASES) + 1
    print(f"cases={total} failed={len(failed)}")
    for item in failed:
        print("FAIL", item)
    if not failed:
        print("ALL PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
