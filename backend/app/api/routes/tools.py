import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.dependencies import require_admin
from backend.app.tools.business import TOOLS
from backend.app.tools.registry import CONFIG, read_config, registry

router = APIRouter(prefix="/tools", tags=["MCP management"], dependencies=[Depends(require_admin)])


@router.get("")
async def tool_status():
    return {
        "servers": registry.status,
        "native_tools": [
            {
                "name": t.name,
                "description": t.description,
                "read_only": (t.metadata or {}).get("read_only", True),
                "retryable": (t.metadata or {}).get("retryable", True),
            }
            for t in TOOLS
        ],
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "read_only": True,
                "retryable": bool((t.metadata or {}).get("retryable")),
            }
            for t in registry.tools
        ],
    }


@router.post("/reload")
async def reload_tools():
    return {"servers": await registry.reload()}


class Enabled(BaseModel):
    enabled: bool


@router.put("/servers/{name}")
async def enable_server(name: str, body: Enabled):
    values = read_config()
    if name not in values.get("servers", {}):
        raise HTTPException(404, "只允许管理本机已配置的服务")
    values["servers"][name]["enabled"] = body.enabled
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CONFIG)
    return {"servers": await registry.reload()}
