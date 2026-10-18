"""统一环境配置；所有相对路径均以项目根目录为基准。"""

import os
from pathlib import Path
from dotenv import dotenv_values

ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT_DIR / ".env"
if ENV_PATH.is_file():
    for encoding in ("utf-8-sig", "gbk"):
        try:
            values = dotenv_values(ENV_PATH, encoding=encoding)
            for key, value in values.items():
                if value is not None:
                    os.environ.setdefault(key, value)
            break
        except UnicodeDecodeError:
            continue

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
_model_path = Path(os.getenv("BGE_M3_MODEL_PATH", "Models/bge-m3"))
BGE_M3_MODEL_PATH = str(_model_path if _model_path.is_absolute() else ROOT_DIR / _model_path)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "ecommerce")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6380"))
API_KEY = os.getenv("API_KEY", "")
CORS_ORIGINS = [
    x.strip()
    for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if x.strip()
]
DATA_DIR = ROOT_DIR / "data"
