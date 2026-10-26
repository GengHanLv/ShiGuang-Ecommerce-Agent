"""显式创建当前登录用户的隔离模拟订单，真实业务库不写入。"""

import asyncio

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import verify_token
from backend.app.tools.orders import create_demo_order

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("/demo")
async def demo(user=Depends(verify_token)):
    return await asyncio.to_thread(create_demo_order, user.id)
