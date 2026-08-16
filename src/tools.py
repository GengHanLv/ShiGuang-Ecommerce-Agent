"""
查询实时订单状态，让 Agent 能获取动态业务数据。
"""
from typing import Optional

from sqlalchemy import text

from database import AsyncSessionLocal

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


async def query_order(user_id: str, order_id: Optional[int] = None) -> str:
    """按 user_id（及可选 order_id）查询订单，参数化防注入。"""
    if not user_id:
        return "缺少用户标识，无法查询订单"

    try:
        async with AsyncSessionLocal() as session:
            if order_id is not None:
                sql = text(
                    "SELECT id, product_id, status FROM orders "
                    "WHERE user_id=:uid AND id=:oid"
                )
                result = await session.execute(sql, {"uid": user_id, "oid": order_id})
            else:
                sql = text(
                    "SELECT id, product_id, status FROM orders "
                    "WHERE user_id=:uid ORDER BY id DESC LIMIT 20"
                )
                result = await session.execute(sql, {"uid": user_id})
            rows = result.fetchall()
    except Exception as e:
        # 把异常类型带上，便于日志与模型区分失败与无数据
        return f"订单查询失败：{type(e).__name__}: {e}"

    if not rows:
        if order_id is not None:
            return f"未找到用户 {user_id} 的订单 {order_id}"
        return f"未找到用户 {user_id} 的订单"

    lines = [_format_row(r) for r in rows]
    header = f"共 {len(lines)} 条订单：" if order_id is None else "订单详情："
    return header + " | ".join(lines)
