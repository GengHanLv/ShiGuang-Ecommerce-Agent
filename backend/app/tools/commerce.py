"""无用户身份、无外部写入的电商计算工具，可通过 MCP 复用。"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field


class CartItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    unit_price: Decimal = Field(ge=0, le=10000000, max_digits=12, decimal_places=2)
    quantity: int = Field(ge=1, le=10000)


def purchase_cost(
    items: list[CartItem], discount: str = "0", shipping: str = "0", budget: str | None = None
) -> dict:
    if not 1 <= len(items) <= 50:
        raise ValueError("商品数量需为1至50项")

    def money(value):
        result = Decimal(value)
        if not result.is_finite() or not 0 <= result <= 100000000000:
            raise ValueError("金额必须是有限非负数")
        if result != result.quantize(Decimal("0.01")):
            raise ValueError("金额最多保留两位小数")
        return result

    discount, shipping = money(discount), money(shipping)
    subtotal = sum((item.unit_price * item.quantity for item in items), Decimal(0))
    if discount > subtotal:
        raise ValueError("优惠金额不能超过商品小计")
    total = subtotal - discount + shipping

    def fmt(value):
        return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    return {
        "currency": "CNY",
        "subtotal": fmt(subtotal),
        "discount": fmt(discount),
        "shipping": fmt(shipping),
        "total": fmt(total),
        "within_budget": total <= money(budget) if budget is not None else None,
        "items": [
            {"name": i.name, "quantity": i.quantity, "line_total": fmt(i.unit_price * i.quantity)}
            for i in items
        ],
        "notice": "按输入金额估算；优惠应已确认可叠加，未自动核验优惠资格、税费和实际结算价。",
    }


class ProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=160)
    specifications: dict[str, str] = Field(max_length=30)
    source_url: str = Field(default="", max_length=2000)


def compare_candidates(products: list[ProductCandidate], dimensions: list[str]) -> dict:
    if not 2 <= len(products) <= 6 or not 1 <= len(dimensions) <= 12:
        raise ValueError("比较需要2至6款商品、1至12项参数")
    if len({p.model.casefold() for p in products}) != len(products):
        raise ValueError("商品型号/配置名称不可重复")
    if any(len(d) > 100 for d in dimensions) or any(
        len(k) > 100 or len(v) > 1000 for p in products for k, v in p.specifications.items()
    ):
        raise ValueError("参数内容过长")
    return {
        "models": [p.model for p in products],
        "rows": [
            {
                "parameter": d,
                "values": [p.specifications.get(d) or "当前资料无法确认" for p in products],
            }
            for d in dimensions
        ],
        "sources": [{"model": p.model, "url": p.source_url} for p in products],
        "notice": "只整理输入证据，不联网核实、不推断缺失参数、不将不同测试条件视为同等表现。",
    }


def service_window(start_date: str, days: int, include_start: bool = False) -> dict:
    if not 1 <= days <= 3660:
        raise ValueError("期限需为1至3660个自然日")
    start = date.fromisoformat(start_date)
    end = start + timedelta(days=days - int(include_start))
    return {
        "start_date": start.isoformat(),
        "days": days,
        "include_start": include_start,
        "end_date": end.isoformat(),
        "day_type": "calendar_days",
        "notice": "仅按给定起算日及自然日口径计算，不代表退货资格、法定期限或平台审核结论；起算口径需先核对规则。",
    }
