"""News parser tests — fixtures parser, contract validation, env factory.

Live Telethon parser is intentionally not tested here: it requires
credentials + a network round trip to Telegram MTProto. Smoke-test
manually after `TELEGRAM_API_ID/HASH` are obtained.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.news import CHANNELS, FixturesParser, NewsItem, TelethonParser, parser_from_env

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "news"


# ────────────────────────────── NewsItem contract ──────────────────────────────


class TestNewsItemContract:
    def test_minimal_valid(self) -> None:
        item = NewsItem(
            channel="rbc_news",
            message_id=1,
            posted_at=datetime(2026, 4, 27, tzinfo=UTC),
            text="hi",
            url=None,
            fetched_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        assert item.url is None

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(ValidationError):
            NewsItem(
                channel="rbc_news",
                message_id=1,
                posted_at=datetime(2026, 4, 27, tzinfo=UTC),
                text="",
                fetched_at=datetime(2026, 4, 27, tzinfo=UTC),
            )

    def test_rejects_negative_id(self) -> None:
        with pytest.raises(ValidationError):
            NewsItem(
                channel="rbc_news",
                message_id=-1,
                posted_at=datetime(2026, 4, 27, tzinfo=UTC),
                text="x",
                fetched_at=datetime(2026, 4, 27, tzinfo=UTC),
            )

    def test_immutable(self) -> None:
        item = NewsItem(
            channel="rbc_news",
            message_id=1,
            posted_at=datetime(2026, 4, 27, tzinfo=UTC),
            text="x",
            fetched_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        with pytest.raises(ValidationError):
            item.text = "y"  # type: ignore[misc]


# ────────────────────────────── Channel config ──────────────────────────────


class TestChannelConfig:
    def test_six_channels_no_dupes(self) -> None:
        assert len(CHANNELS) == 6
        assert len(set(CHANNELS)) == 6

    def test_lowercase_no_at_prefix(self) -> None:
        for ch in CHANNELS:
            assert ch == ch.lower()
            assert not ch.startswith("@")

    def test_each_channel_has_fixture_file(self) -> None:
        for ch in CHANNELS:
            assert (FIXTURES_ROOT / f"{ch}.jsonl").exists(), f"missing fixture for {ch}"


# ────────────────────────────── FixturesParser ──────────────────────────────


class TestFixturesParser:
    def test_loads_fixture_for_known_channel(self) -> None:
        parser = FixturesParser(root=FIXTURES_ROOT)
        items = asyncio.run(parser.fetch("markettwits", limit=100))
        assert len(items) > 0
        for item in items:
            assert item.channel == "markettwits"
            assert item.url and item.url.startswith("https://t.me/markettwits/")
            assert item.fetched_at.tzinfo is not None

    def test_empty_for_unknown_channel(self) -> None:
        parser = FixturesParser(root=FIXTURES_ROOT)
        items = asyncio.run(parser.fetch("does_not_exist_12345", limit=100))
        assert items == []

    def test_respects_limit(self) -> None:
        parser = FixturesParser(root=FIXTURES_ROOT)
        items = asyncio.run(parser.fetch("markettwits", limit=2))
        assert len(items) == 2

    def test_fetch_all_covers_all_channels(self) -> None:
        parser = FixturesParser(root=FIXTURES_ROOT)
        out = asyncio.run(parser.fetch_all(CHANNELS, limit=100))
        assert set(out.keys()) == set(CHANNELS)
        total = sum(len(v) for v in out.values())
        assert total >= 30, f"expected ≥30 fixture msgs across 6 channels, got {total}"


# ────────────────────────────── parser_from_env ──────────────────────────────


class TestParserFactory:
    def test_falls_back_to_fixtures_when_creds_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
        monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
        parser = parser_from_env()
        assert isinstance(parser, FixturesParser)

    def test_picks_telethon_when_creds_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_API_ID", "123456")
        monkeypatch.setenv("TELEGRAM_API_HASH", "fake_hash")
        parser = parser_from_env()
        assert isinstance(parser, TelethonParser)
