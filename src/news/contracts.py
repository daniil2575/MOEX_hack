"""Pydantic contract for parsed news items."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NewsItem(BaseModel):
    """A single parsed message from a Telegram financial channel.

    `posted_at` and `fetched_at` are tz-aware UTC. `url` is None for
    fixture-mode rows where no public link exists.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: str = Field(..., min_length=1, max_length=64)
    message_id: int = Field(..., ge=0)
    posted_at: datetime
    text: str = Field(..., min_length=1)
    url: str | None = None
    fetched_at: datetime
