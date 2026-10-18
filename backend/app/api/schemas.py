from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("user_id", "message", "session_id")
    @classmethod
    def reject_blank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("内容不能为空白")
        return value.strip() if value is not None else value


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    intents: list[str] = Field(default_factory=list)
    memory_hits: list[str] = Field(default_factory=list)
    degraded: bool = False
