from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    # 仅用于旧客户端兼容校验，绝不作为授权身份；与登录身份不同会返回403。
    user_id: str | None = Field(default=None, min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("user_id", "message", "session_id", "request_id")
    @classmethod
    def reject_blank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("内容不能为空白")
        return value.strip() if value is not None else value


class ProductImage(BaseModel):
    """应用核验后的商品图片，独立于模型生成的Markdown。"""

    model: str
    url: str
    alt: str
    source_url: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    run_id: str = ""
    intents: list[str] = Field(default_factory=list)
    memory_hits: list[str] = Field(default_factory=list)
    degraded: bool = False
    retryable: bool = False
    tool_trace: list[dict] = Field(default_factory=list)
    stop_reason: str = ""
    product_images: list[ProductImage] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)
