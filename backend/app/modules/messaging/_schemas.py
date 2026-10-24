from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Button(BaseModel):
    """An inline button: either a callback (handled by our bot) or a URL. A message whose
    buttons include `request_contact` gets a reply keyboard instead (Telegram's "share my phone"
    button); such buttons cannot be edited later."""

    text: str
    callback_data: str | None = None
    url: str | None = None
    request_contact: bool = False


class OutboxView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    kind: str
    chat_id: int
    text: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
