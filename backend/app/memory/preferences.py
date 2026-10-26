"""偏好的当前有效值由结构化库管理；向量记忆只作为语义事实/旧资料补充。"""

import hashlib
import time

from fastapi import HTTPException

from backend.app.infrastructure.store import store
from backend.app.memory.policy import _normalize_memory_text, _topic_key


def list_preferences(user_id):
    with store.connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT topic,text,version,updated FROM preferences WHERE user_id=? ORDER BY updated DESC",
                (user_id,),
            )
        ]


def set_preference(user_id, text, expected_version=None):
    topic = (
        _topic_key(text)
        or "custom_" + hashlib.sha256(_normalize_memory_text(text).encode()).hexdigest()[:16]
    )
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM preferences WHERE user_id=? AND topic=?", (user_id, topic)
        ).fetchone()
        version = row["version"] if row else 0
        if expected_version is not None and version != expected_version:
            raise HTTPException(409, "偏好已被更新，请刷新后再修改")
        if row and row["text"] == text:
            return dict(row)
        db.execute(
            "INSERT INTO preferences VALUES(?,?,?,?,?) ON CONFLICT(user_id,topic) DO UPDATE SET text=excluded.text,version=excluded.version,updated=excluded.updated",
            (user_id, topic, text, version + 1, time.time()),
        )
        return dict(
            db.execute(
                "SELECT topic,text,version,updated FROM preferences WHERE user_id=? AND topic=?",
                (user_id, topic),
            ).fetchone()
        )


def delete_preference(user_id, topic, expected_version=None):
    with store.connect() as db:
        row = db.execute(
            "SELECT version FROM preferences WHERE user_id=? AND topic=?", (user_id, topic)
        ).fetchone()
        if not row:
            return 0
        if expected_version is not None and row["version"] != expected_version:
            raise HTTPException(409, "偏好版本已变化，请刷新")
        result = db.execute(
            "DELETE FROM preferences WHERE user_id=? AND topic=? AND version=?",
            (user_id, topic, row["version"]),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "偏好已更新，请刷新后重试")
    return 1
