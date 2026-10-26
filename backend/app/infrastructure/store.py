"""单机持久化控制库：身份、执行记录、历史与偏好分别建表；不保存模型密钥。"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.app.core.config import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT UNIQUE NOT NULL,
 product TEXT NOT NULL,status TEXT NOT NULL,amount TEXT NOT NULL,created REAL NOT NULL);

CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,run_id TEXT NOT NULL,title TEXT NOT NULL,created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS documents_owner ON documents(user_id,run_id,created);
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','user')), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY,attempts INTEGER,expires REAL);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,session_id TEXT NOT NULL,request_id TEXT NOT NULL,
 question TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,created REAL,updated REAL,
 result TEXT,error TEXT, UNIQUE(user_id,session_id,request_id));
CREATE TABLE IF NOT EXISTS tool_runs (
 run_id TEXT,call_id TEXT,name TEXT,args_hash TEXT,status TEXT,attempts INTEGER,
 retryable INTEGER,result TEXT,updated REAL,PRIMARY KEY(run_id,call_id));
CREATE TABLE IF NOT EXISTS history (
 user_id TEXT,session_id TEXT,run_id TEXT,role TEXT,content TEXT,created REAL,
 PRIMARY KEY(user_id,session_id,run_id,role));
CREATE INDEX IF NOT EXISTS history_lookup ON history(user_id,session_id,created);
CREATE TABLE IF NOT EXISTS preferences (
 user_id TEXT,topic TEXT,text TEXT,version INTEGER,updated REAL,PRIMARY KEY(user_id,topic));
CREATE TABLE IF NOT EXISTS leases (key TEXT PRIMARY KEY,token TEXT,expires REAL);
CREATE TABLE IF NOT EXISTS cache_versions (collection TEXT PRIMARY KEY,version INTEGER);
CREATE TABLE IF NOT EXISTS memory_events (run_id TEXT PRIMARY KEY,status TEXT);
CREATE TABLE IF NOT EXISTS web_assets (
 id TEXT PRIMARY KEY,url TEXT NOT NULL,source_url TEXT NOT NULL,model TEXT NOT NULL,
 alt TEXT NOT NULL,fetched_at TEXT NOT NULL);
"""


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DATA_DIR / "runtime/app.sqlite3")

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=30000")
        db.executescript(SCHEMA)
        try:
            with db:
                yield db
        finally:
            db.close()


store = Store()
