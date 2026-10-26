from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api.dependencies import verify_token
from backend.app.memory.policy import _filter_items
from backend.app.memory.preferences import delete_preference, list_preferences, set_preference

router = APIRouter(prefix="/preferences", tags=["Preferences"])


class PreferenceInput(BaseModel):
    text: str = Field(min_length=2, max_length=300)
    expected_version: int | None = Field(default=None, ge=0)


@router.get("")
def preferences(user=Depends(verify_token)):
    return {"preferences": list_preferences(user.id)}


@router.post("")
def update(body: PreferenceInput, user=Depends(verify_token)):
    if not _filter_items([{"type": "preference", "text": body.text}]):
        raise HTTPException(422, "该内容不适合保存为长期偏好")
    return set_preference(user.id, body.text, body.expected_version)


@router.delete("/{topic}")
def delete(topic: str, expected_version: int | None = None, user=Depends(verify_token)):
    return {"deleted": delete_preference(user.id, topic, expected_version)}
