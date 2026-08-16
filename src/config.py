import os
from pathlib import Path


def _load_dotenv_safe() -> None:
    """兼容 utf-8 / gbk 的 .env；解码失败的行跳过，避免进程无法启动。"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    raw = env_path.read_bytes()
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_safe()

_DEFAULT_BGE_PATH = r"D:\BaiduNetdiskDownload\2.资料\bge-m3"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
# 对话 / 抽取 / 评测用 Chat 模型
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
# 本地 BGE-M3（稠密向量维度 1024）
_bge_from_env = os.getenv("BGE_M3_MODEL_PATH", _DEFAULT_BGE_PATH)
BGE_M3_MODEL_PATH = (
    _bge_from_env if Path(_bge_from_env).exists() else _DEFAULT_BGE_PATH
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
MILVUS_HOST = os.getenv("MILVUS_HOST")
MILVUS_PORT = os.getenv("MILVUS_PORT")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
API_KEY = os.getenv("API_KEY", "demo-key")