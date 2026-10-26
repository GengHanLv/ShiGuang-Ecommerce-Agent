"""私有报告列表、显式导出与认证下载。"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.app.agent.journal import owned_run
from backend.app.api.dependencies import verify_token
from backend.app.tools.documents import create_report, list_documents, owned_document

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("")
async def documents(user=Depends(verify_token)):
    return {"documents": await asyncio.to_thread(list_documents, user.id)}


@router.get("/{identifier}/download")
async def download(identifier: str, user=Depends(verify_token)):
    row, path = await asyncio.to_thread(owned_document, identifier, user.id)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"consultation-{row['id'][:12]}.pdf",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/from-task/{identifier}")
async def export_reply(identifier: str, user=Depends(verify_token)):
    row = await asyncio.to_thread(owned_run, identifier, user.id)
    if row["status"] != "completed" or not row.get("result"):
        raise HTTPException(409, "仅能导出已完成的回复")
    result = json.loads(row["result"])
    document = await asyncio.to_thread(
        create_report,
        user.id,
        identifier,
        "电商咨询记录",
        [
            {"heading": "咨询问题", "content": row["question"]},
            {"heading": "咨询回复", "content": result["reply"]},
        ],
    )
    return {"document": document}
