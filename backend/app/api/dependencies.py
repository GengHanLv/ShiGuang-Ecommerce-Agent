import secrets
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from backend.app.core.config import API_KEY

api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_token(api_key: str | None = Depends(api_key_scheme)):
    if not api_key or not secrets.compare_digest(api_key.encode(), API_KEY.encode()):
        raise HTTPException(status_code=401, detail="API Key 无效，请检查连接设置")
