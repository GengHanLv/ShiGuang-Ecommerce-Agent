"""
查询实时订单状态，让 Agent 能获取动态业务数据。
"""

import asyncio
import logging
import time

from sqlalchemy import text

from backend.app.infrastructure.database import AsyncSessionLocal
from backend.app.infrastructure.store import store

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "pending": "待付款",
    "paid": "已付款",
    "shipped": "已发货",
    "delivered": "已签收",
    "cancelled": "已取消",
    "refunding": "退款中",
    "refunded": "已退款",
}


def _format_row(row) -> str:
    data = dict(row._mapping)
    oid = data.get("id")
    pid = data.get("product_id")
    status = data.get("status")
    status_cn = STATUS_MAP.get(str(status).lower(), status) if status is not None else "未知"
    return f"订单号={oid}, 商品ID={pid}, 状态={status_cn}"


def create_demo_order(user_id):
    with store.connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO demo_orders(user_id,product,status,amount,created) VALUES(?,?,?,?,?)",
            (user_id, "漫步者 W820NB 三金标版（虚构测试商品）", "shipped", "299.00", time.time()),
        )
        row = db.execute("SELECT * FROM demo_orders WHERE user_id=?", (user_id,)).fetchone()
    return {
        "order_id": -row["id"],
        "product": row["product"],
        "status": STATUS_MAP[row["status"]],
        "amount": row["amount"],
        "currency": "CNY",
        "simulated": True,
        "notice": "完全虚构的测试数据，不代表真实商品价格、购买或物流",
    }


def demo_order_text(user_id, order_id=None):
    with store.connect() as db:
        row = db.execute("SELECT * FROM demo_orders WHERE user_id=?", (user_id,)).fetchone()
    if not row or (order_id is not None and -row["id"] != order_id):
        return ""
    return (
        f"【模拟测试数据】订单号={-row['id']}, 商品={row['product']}, "
        f"状态={STATUS_MAP[row['status']]}, 虚构金额=CNY {row['amount']}。"
        "无真实物流单号、配送轨迹或预计到货时间；不能用于真实售后。"
    )


async def query_order(user_id: str, order_id: int | None = None) -> str:
    """按 user_id（及可选 order_id）查询订单，参数化防注入。"""
    if not user_id:
        return "缺少用户标识，无法查询订单"

    demo = await asyncio.to_thread(demo_order_text, user_id, order_id)
    if order_id is not None and order_id < 0:
        return demo or "未找到属于当前用户的模拟订单"
    try:
        async with AsyncSessionLocal() as session:
            if order_id is not None:
                sql = text(
                    "SELECT id, product_id, status FROM orders WHERE user_id=:uid AND id=:oid"
                )
                result = await session.execute(sql, {"uid": user_id, "oid": order_id})
            else:
                sql = text(
                    "SELECT id, product_id, status FROM orders "
                    "WHERE user_id=:uid ORDER BY id DESC LIMIT 20"
                )
                result = await session.execute(sql, {"uid": user_id})
            rows = result.fetchall()
    except Exception:
        # 保留完整异常日志，给用户返回可理解的失败说明。
        logger.exception("订单查询失败")
        return (demo + " | 真实订单服务暂不可用。") if demo else "订单查询失败，请稍后再试"

    if not rows and demo:
        return demo
    if not rows:
        if order_id is not None:
            return f"未找到用户 {user_id} 的订单 {order_id}"
        return f"未找到用户 {user_id} 的订单"

    lines = [_format_row(r) for r in rows]
    header = f"共 {len(lines)} 条订单：" if order_id is None else "订单详情："
    return header + " | ".join(lines + ([demo] if demo else []))
