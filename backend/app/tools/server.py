"""内置只读电商 MCP 服务：联网与确定性计算；协议走 stdout，日志走 stderr。"""

from datetime import UTC, datetime

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from backend.app.tools.commerce import (
    CartItem,
    ProductCandidate,
    compare_candidates,
    purchase_cost,
    service_window,
)
from backend.app.tools.web import fetch_product_page as fetch_page
from backend.app.tools.web import web_search as search

server = FastMCP("ShiGuang Commerce Tools")
readonly = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


@server.tool(annotations=readonly)
async def web_search(query: str, max_results: int = 5) -> dict:
    """联网查找品牌规格、平台商品及第三方测评资料。返回搜索摘要；需读取网页才能核实参数、价格与图片。"""
    return await search(query, max_results)


@server.tool(annotations=readonly)
async def fetch_product_page(url: str, model: str = "") -> dict:
    """读取品牌、平台商品或测评网页正文与来源图片。model填完整型号和版本；只读公网，不登录、不绕过验证码。"""
    return await fetch_page(url, model)


@server.tool(annotations=readonly)
def current_time() -> dict:
    """读取当前UTC时间，仅用于说明获取时间，不能代替页面发布日期或规则生效日期。"""
    return {"utc": datetime.now(UTC).isoformat()}


@server.tool(annotations=readonly)
def calculate_purchase_cost(
    items: list[CartItem], discount: str = "0", shipping: str = "0", budget: str | None = None
) -> dict:
    """按已知单价、数量、已确认可叠加优惠与运费计算CNY预算。金额用十进制字符串，不猜测促销资格。"""
    return purchase_cost(items, discount, shipping, budget)


@server.tool(annotations=readonly)
def compare_products(products: list[ProductCandidate], dimensions: list[str]) -> dict:
    """把已经查证的2至6款商品整理为同维度比较表。缺少字段标为无法确认，不补写事实或评定虚假优劣。"""
    return compare_candidates(products, dimensions)


@server.tool(annotations=readonly)
def calculate_service_window(start_date: str, days: int, include_start: bool = False) -> dict:
    """按明确起始日期YYYY-MM-DD及自然日数算截止日期，include_start说明首日是否计入。仅做日期算术，不判定退货资格或承诺平台受理。"""
    return service_window(start_date, days, include_start)


if __name__ == "__main__":
    server.run(transport="stdio")
