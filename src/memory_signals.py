"""偏好 / 查单 / 记忆变更相关信号词，供 graph 与 long_term_memory 共用。"""
import re
from typing import Optional

TRANSFER_KEYWORDS = [
    "转人工", "人工客服", "找经理", "找主管", "投诉",
    "给我接人工", "我要和人说话", "找真人", "转接人工",
    "找你们经理", "找你们主管",
]

FAQ_KEYWORDS = [
    "退货", "退款", "保修", "发货时间", "客服电话",
    "怎么退", "如何退", "七天无理由", "质保", "发票",
    "续航", "无线充电", "电池", "快充", "屏幕",
    "新品手机", "蓝牙耳机", "机械键盘", "支持吗", "参数",
    "多久发货", "几天发货", "包邮", "什么快递", "发货用",
    "顺丰包邮", "下单后几天",
]

ORDER_KEYWORDS = [
    "订单", "物流", "快递", "发货了", "签收", "包裹",
    "到哪了", "催单", "取消订单", "改地址", "订单号",
    "买了什么", "买过什么", "购买了什么", "买的什么", "我买了",
    "下单", "换绑", "收货手机", "改手机号",
]

ORDER_LOOKUP_PHRASES = [
    "订单号", "到哪了", "催单", "催一下", "发货了吗", "发货了",
    "取消订单", "怎么取消", "订单怎么取消", "改地址", "改收货地址", "改一下收货",
    "查一下我的订单", "查一下订单", "查下我的订单", "查下订单", "查订单",
    "查询订单", "看看我的订单", "看看订单", "看下我的订单",
    "我的订单状态", "订单状态", "物流信息", "物流到哪", "物流在哪", "物流停",
    "所有订单", "看看所有订单", "订单到哪", "有个订单", "我的订单",
    "请告诉我我的订单", "告诉我我的订单", "告诉我订单",
    "买了什么", "买过什么", "购买了什么", "买的什么", "我买了",
    "什么时候能收到", "什么时候到", "何时能收到", "啥时候能收到",
    "跟踪一下包裹", "跟踪包裹", "看看包裹", "看看昨天的包裹",
    "包裹签收", "签收了吗", "申请退货", "要退货", "订单要退",
    "换绑", "收货手机号", "手机号填错", "改手机号", "改收货手机",
    "刚下单", "收货信息",
]

SHIPPING_POLICY_MARKERS = [
    "包邮", "发货时间", "多久发货", "几天发货", "用什么快递",
    "发货用什么", "一般多久发货", "下单后几天发货", "顺丰包邮",
]

PREF_MARKERS = [
    "记住", "偏好", "以后都", "以后我的", "希望以后", "在以后", "以后请",
    "别早上", "晚上收货", "早上送", "收货时间", "配送时间",
    "不要早上", "想晚上", "晚间收货", "晚上查收", "晚上送货", "晚上签收",
    "不要打电话", "别打电话", "打电话", "通知我", "请打电话", "打电话通知",
    "只用", "不接受", "指定快递", "用顺丰", "都用顺丰",
]

EXTRACT_TRIGGER = [
    "记住", "偏好", "以后都", "以后我的", "在以后", "希望以后",
    "别早上", "晚上收货", "早上送", "收货时间", "配送时间",
    "不要早上", "想晚上", "晚间收货", "晚上查收", "查收",
    "不要打电话", "别打电话", "不要短信", "打电话", "电话通知",
    "通知我", "请打电话", "打给我", "手机",
    "过敏", "不满意", "太吵", "降噪", "下次", "习惯",
    "顺丰", "只用", "都用", "不接受", "指定快递", "用顺丰",
]

PREFERENCE_QUERY_MARKERS = [
    "我的偏好", "收货偏好", "配送偏好", "偏好是什么",
    "记住了什么", "记得什么", "我的收货习惯", "指定什么快递",
    "有什么偏好", "有哪些偏好", "哪些偏好", "什么偏好",
    "记得我", "还记得我的", "我有什么偏好", "我有哪些偏好",
]

DELETE_MARKERS = [
    "不用记住", "取消偏好", "删除偏好", "别再记住", "不要记住",
    "取消电话通知", "不用电话通知", "不要打电话通知", "取消打电话",
    "不要顺丰了", "取消顺丰", "不用顺丰了", "废除偏好",
]

UPDATE_MARKERS = [
    "改成", "换成", "改为", "以后改成", "以后换成", "不要用", "别用",
]


def extract_order_id(text: str) -> Optional[int]:
    patterns = [
        r"(?:订单号|订单ID|订单id|订单)\s*[:：#]?\s*(\d+)",
        r"(?:order\s*(?:id|no\.?|#)?)\s*[:：]?\s*(\d+)",
        r"\b(\d{6,})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text or "", re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def is_shipping_policy_question(msg: str) -> bool:
    return any(k in (msg or "") for k in SHIPPING_POLICY_MARKERS)


def is_order_lookup_intent(msg: str) -> bool:
    msg = (msg or "").strip()
    if not msg:
        return False
    if is_shipping_policy_question(msg) and not any(
        k in msg for k in ("我的订单", "订单号", "到哪了", "催单", "催一下", "包裹")
    ):
        return False
    if extract_order_id(msg) is not None:
        return True
    if any(kw in msg for kw in ORDER_LOOKUP_PHRASES):
        return True
    if re.search(
        r"(?:查一下|查下|查询|查我的|看看|看下|看一下|告诉我|说说|问一下|跟踪).{0,12}(?:订单|物流|包裹)",
        msg,
    ):
        return True
    if re.search(r"(?:订单|物流|包裹).{0,10}(?:怎么样|怎样|如何|到哪|状态|取消|签收|退)", msg):
        return True
    if re.search(r"^(?:请问)?(?:把)?(?:我的)?订单(?:信息|状态|情况)?(?:告诉我|发我)?$", msg):
        return True
    if re.search(r"(?:什么时候|何时|啥时候).{0,8}(?:收到|到货|送达)", msg):
        return True
    if re.search(r"(?:催|催一下).{0,8}订单", msg):
        return True
    if re.search(r"(?:改|更改).{0,6}(?:收货)?地址", msg):
        return True
    if re.search(r"(?:换绑|改|更改).{0,8}(?:手机号|电话|收货信息|收货手机)", msg):
        return True
    if re.search(r"(?:手机号|收货电话).{0,8}(?:填错|错了|改)", msg):
        return True
    if any(k in msg for k in ("订单", "包裹", "物流")) and any(
        k in msg for k in ("退货", "退款", "取消", "催", "签收", "跟踪", "到哪", "停更新")
    ):
        return True
    if re.search(r"(?:申请|帮我|我要).{0,6}退货", msg):
        return True
    return False


def has_soft_business_signal(msg: str) -> bool:
    msg = msg or ""
    return any(
        k in msg
        for k in (
            "下单", "订单", "包裹", "物流", "收货", "手机号", "换绑",
            "改地址", "签收", "催", "退货", "退款", "发票", "保修",
            "续航", "发货", "客服",
        )
    )


def has_preference_signal(msg: str) -> bool:
    msg = msg or ""
    if is_shipping_policy_question(msg):
        return False
    if any(kw in msg for kw in PREF_MARKERS):
        return True
    if "顺丰" in msg and any(
        k in msg for k in ("记住", "以后", "只用", "都用", "指定", "希望", "偏好")
    ):
        return True
    if any(t in msg for t in ("晚上", "早上", "晚间", "白天")) and any(
        r in msg for r in ("收货", "查收", "签收", "配送", "送货", "收快递")
    ):
        return True
    if any(k in msg for k in ("希望", "记住", "以后")) and any(
        r in msg for r in ("收货", "查收", "配送", "送货", "电话", "快递", "送")
    ):
        return True
    return False


def is_preference_query(msg: str) -> bool:
    msg = msg or ""
    if any(k in msg for k in PREFERENCE_QUERY_MARKERS):
        return True
    if re.search(r"(?:记得|记住|回忆).{0,12}偏好", msg):
        return True
    if re.search(r"偏好.{0,8}(?:什么|哪些|吗)", msg):
        return True
    return False


def is_preference_utterance(msg: str) -> bool:
    if not has_preference_signal(msg):
        return False
    if is_order_lookup_intent(msg):
        return False
    if is_shipping_policy_question(msg):
        return False
    return True


def is_stating_new_preference(msg: str) -> bool:
    return is_preference_utterance(msg) and not is_preference_query(msg)


def is_memory_delete(msg: str) -> bool:
    return any(k in (msg or "") for k in DELETE_MARKERS)


def is_memory_update(msg: str) -> bool:
    return any(k in (msg or "") for k in UPDATE_MARKERS)


def should_inject_memory(msg: str, has_hits: bool) -> bool:
    if not has_hits:
        return False
    if is_memory_delete(msg) or is_memory_update(msg):
        return False
    if is_stating_new_preference(msg):
        return False
    return True
