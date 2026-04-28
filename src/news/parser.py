"""News parsers — Telethon (live) + Fixtures (offline / dev) behind a Protocol.

Live mode requires `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` from
https://my.telegram.org. When those are unset, `parser_from_env()` falls back
to the on-disk fixtures parser so the rest of the pipeline can run without
Telegram credentials (useful for CI, smoke tests, and the hackathon-day
fixture-fallback path documented in the risk register).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Protocol

from src.news.contracts import NewsItem

if TYPE_CHECKING:
    from telethon import TelegramClient


# Module-level so tests can patch the path without subclassing.
DEFAULT_FIXTURES_PATH = Path("data/fixtures/news")
INTER_CHANNEL_PAUSE_SEC = 1.0  # gentle on Telegram rate limits


class NewsParser(Protocol):
    async def fetch(self, channel: str, limit: int = 100) -> list[NewsItem]: ...
    async def fetch_all(
        self, channels: tuple[str, ...], limit: int = 100
    ) -> dict[str, list[NewsItem]]: ...


class TelethonParser:
    """Live parser. Use as an async context manager so the session closes cleanly."""

    def __init__(self, api_id: int, api_hash: str, session_name: str = "moex_bot_parser") -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_name = session_name
        self._client: TelegramClient | None = None

    async def __aenter__(self) -> TelethonParser:
        from telethon import TelegramClient

        self._client = TelegramClient(self._session_name, self._api_id, self._api_hash)
        await self._client.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def fetch(self, channel: str, limit: int = 100) -> list[NewsItem]:
        if self._client is None:
            raise RuntimeError("TelethonParser used outside `async with` block")
        now = datetime.now(UTC)
        items: list[NewsItem] = []
        async for msg in self._client.iter_messages(channel, limit=limit):
            text = (msg.message or "").strip()
            if not text:
                continue
            posted_at = msg.date if msg.date is not None else now
            items.append(
                NewsItem(
                    channel=channel,
                    message_id=int(msg.id),
                    posted_at=posted_at,
                    text=text,
                    url=f"https://t.me/{channel}/{msg.id}",
                    fetched_at=now,
                )
            )
        return items

    async def fetch_all(
        self, channels: tuple[str, ...], limit: int = 100
    ) -> dict[str, list[NewsItem]]:
        out: dict[str, list[NewsItem]] = {}
        for ch in channels:
            out[ch] = await self.fetch(ch, limit=limit)
            await asyncio.sleep(INTER_CHANNEL_PAUSE_SEC)
        return out


class FixturesParser:
    """Reads JSONL fixtures from disk. One file per channel: `{channel}.jsonl`.

    Each line is a single message JSON dict matching `NewsItem` (minus
    `fetched_at`, which the parser stamps at read time).
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or DEFAULT_FIXTURES_PATH

    async def fetch(self, channel: str, limit: int = 100) -> list[NewsItem]:
        path = self._root / f"{channel}.jsonl"
        if not path.exists():
            return []
        now = datetime.now(UTC)
        items: list[NewsItem] = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                payload.setdefault("channel", channel)
                payload["fetched_at"] = now.isoformat()
                items.append(NewsItem.model_validate(payload))
                if len(items) >= limit:
                    break
        return items

    async def fetch_all(
        self, channels: tuple[str, ...], limit: int = 100
    ) -> dict[str, list[NewsItem]]:
        return {ch: await self.fetch(ch, limit=limit) for ch in channels}


def parser_from_env() -> NewsParser:
    """Pick parser based on env. TELEGRAM_API_ID/HASH set → Telethon, else fixtures."""
    api_id_raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session = os.environ.get("TELEGRAM_SESSION_NAME", "moex_bot_parser")
    if api_id_raw and api_hash:
        return TelethonParser(int(api_id_raw), api_hash, session)
    return FixturesParser()
