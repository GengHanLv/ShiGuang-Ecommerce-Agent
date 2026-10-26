"""SQLite保存文档任务与可重建的Milvus文本镜像，不存用户长期记忆。"""

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from backend.app.core.config import DATA_DIR
from backend.app.rag.metadata import SCALAR_FIELDS, metadata


class Catalog:
    def __init__(self, path=None):
        self.path = Path(path or DATA_DIR / "rag/catalog.sqlite3")
        self.lock = threading.RLock()

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS chunks (collection TEXT, vector_id TEXT, text TEXT, metadata TEXT, PRIMARY KEY(collection,vector_id))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS snapshots (collection TEXT PRIMARY KEY,generation TEXT,updated REAL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY,collection TEXT,name TEXT,status TEXT,chunks INTEGER,updated REAL,error TEXT)"
        )
        try:
            with db:
                yield db
        finally:
            db.close()

    def fresh(self, collection, generation, ttl=60):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM snapshots WHERE collection=?", (collection,)).fetchone()
            return bool(
                row and row["generation"] == str(generation) and time.time() - row["updated"] < ttl
            )

    def replace_snapshot(self, collection, rows, generation):
        """只有完整读取Milvus成功后才替换镜像，失败不覆盖已有快照。"""
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM chunks WHERE collection=?", (collection,))
            db.executemany(
                "INSERT INTO chunks VALUES(?,?,?,?)",
                [
                    (
                        collection,
                        str(r["id"]),
                        r["text"],
                        json.dumps(
                            metadata(r["text"]) | {k: r[k] for k in SCALAR_FIELDS if k in r},
                            ensure_ascii=False,
                        ),
                    )
                    for r in rows
                ],
            )
            db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES(?,?,?)",
                (collection, str(generation), time.time()),
            )

    def rows(self, collection):
        with self.lock, self.connect() as db:
            return [
                dict(row) | {"metadata": json.loads(row["metadata"])}
                for row in db.execute("SELECT * FROM chunks WHERE collection=?", (collection,))
            ]

    def job(self, identifier):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (identifier,)).fetchone()
            return dict(row) if row else None

    def save_job(self, identifier, collection, name, status, chunks=0, error=""):
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?)",
                (identifier, collection, name, status, chunks, time.time(), error),
            )

    def jobs(self):
        with self.lock, self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,collection,name,status,chunks,updated FROM documents ORDER BY updated DESC LIMIT 100"
                )
            ]


catalog = Catalog()
