"""请求级任务台账与逐工具回执：恢复检查点时复用已完成结果，只重试允许的只读操作。"""

import hashlib
import json
import time
import uuid

from fastapi import HTTPException

from backend.app.infrastructure.store import store


def create_run(user_id, session_id, request_id, question):
    now = time.time()
    with store.connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO runs VALUES(?,?,?,?,?,'pending','prepare',?,?,NULL,NULL)",
            (uuid.uuid4().hex, user_id, session_id, request_id, question, now, now),
        )
        row = db.execute(
            "SELECT * FROM runs WHERE user_id=? AND session_id=? AND request_id=?",
            (user_id, session_id, request_id),
        ).fetchone()
        if row["question"] != question:
            raise HTTPException(409, "同一请求ID不能用于不同问题")
        return dict(row)


def owned_run(identifier, user_id):
    with store.connect() as db:
        row = db.execute(
            "SELECT * FROM runs WHERE id=? AND user_id=?", (identifier, user_id)
        ).fetchone()
    if not row:
        raise HTTPException(404, "任务不存在")
    return dict(row)


def update_run(identifier, status, stage, result=None, error=None):
    with store.connect() as db:
        db.execute(
            "UPDATE runs SET status=?,stage=?,updated=?,result=COALESCE(?,result),error=? WHERE id=?",
            (
                status,
                stage,
                time.time(),
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                error,
                identifier,
            ),
        )


def start_tool(run_id, call_id, name, args, retryable):
    digest = hashlib.sha256(
        json.dumps(args, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    with store.connect() as db:
        row = db.execute(
            "SELECT * FROM tool_runs WHERE run_id=? AND call_id=?", (run_id, call_id)
        ).fetchone()
        if row:
            if row["name"] != name or row["args_hash"] != digest:
                raise RuntimeError("工具调用ID与参数不一致")
            if row["status"] == "completed":
                return json.loads(row["result"])
            if not row["retryable"]:
                raise RuntimeError("该操作结果不确定，不允许自动重复执行")
        db.execute(
            "INSERT INTO tool_runs VALUES(?,?,?,?, 'running',1,?,NULL,?) ON CONFLICT(run_id,call_id) DO UPDATE SET status='running',attempts=attempts+1,updated=excluded.updated",
            (run_id, call_id, name, digest, int(retryable), time.time()),
        )
    return None


def finish_tool(run_id, call_id, result, success):
    with store.connect() as db:
        db.execute(
            "UPDATE tool_runs SET status=?,result=?,updated=? WHERE run_id=? AND call_id=?",
            (
                "completed" if success else "failed",
                json.dumps(result, ensure_ascii=False),
                time.time(),
                run_id,
                call_id,
            ),
        )


def public_tools(run_id):
    with store.connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT call_id,name,status,attempts,retryable,updated FROM tool_runs WHERE run_id=? ORDER BY updated",
                (run_id,),
            )
        ]


def retry_allowed(run_id):
    return not any(
        not row["retryable"] and row["status"] != "completed" for row in public_tools(run_id)
    )
