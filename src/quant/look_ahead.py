"""Look-ahead guards for backtests and live runs.

Five guards documented in `notes/look_ahead_guards.md` (created Sprint 1):

    G1. Frame end-time guard      — no row in `frame.index` may be > `as_of`
    G2. Train/test isolation      — train/test windows must not overlap
    G3. Indicator warm-up guard   — first N values of an N-period indicator
                                    must be NaN (not back-filled)
    G4. Fill-time guard           — order placed at bar T fills no earlier
                                    than the OPEN of bar T+1
    G5. News-time guard           — news visible at `as_of` had `posted_at <= as_of`

These are runtime *assertions* — fast, cheap, and fail loudly. The intent
is that backtests refuse to silently use future data. Live trading also
benefits: an upstream bug that staples future bars onto the feature frame
will trip the same check.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from src.news.contracts import NewsItem


class LookAheadError(AssertionError):
    """Raised when a look-ahead invariant is violated."""


# G1
def assert_frame_no_future(frame: pd.DataFrame, as_of: datetime, *, name: str) -> None:
    if frame.empty:
        return
    last = frame.index.max()
    if isinstance(last, pd.Timestamp):
        last_dt = last.to_pydatetime()
        if last_dt.tzinfo is None and as_of.tzinfo is not None:
            last_dt = last_dt.replace(tzinfo=as_of.tzinfo)
        if last_dt > as_of:
            raise LookAheadError(
                f"{name}: last bar {last_dt.isoformat()} > as_of {as_of.isoformat()}"
            )


# G2
def assert_disjoint_windows(
    train_start: datetime,
    train_end: datetime,
    test_start: datetime,
    test_end: datetime,
) -> None:
    if not (train_start <= train_end and test_start <= test_end):
        raise LookAheadError("window endpoints must be ordered: start <= end")
    if train_end >= test_start:
        raise LookAheadError(
            f"train [{train_start}, {train_end}] overlaps test [{test_start}, {test_end}]"
        )


# G3
def assert_indicator_warmup_nan(series: pd.Series, period: int, *, name: str) -> None:
    if period < 1:
        raise LookAheadError(f"{name}: period must be >= 1")
    head = series.iloc[: period - 1]
    if not head.isna().all():
        raise LookAheadError(
            f"{name}: warm-up window of length {period - 1} must be all NaN; "
            f"found {int(head.notna().sum())} non-NaN value(s)"
        )


# G4
def assert_fill_after_decision(decision_at: datetime, fill_at: datetime, *, bar_seconds: int) -> None:
    delta = (fill_at - decision_at).total_seconds()
    if delta < bar_seconds:
        raise LookAheadError(
            f"fill at {fill_at.isoformat()} is {delta:.0f}s after decision at "
            f"{decision_at.isoformat()}; minimum is one bar ({bar_seconds}s)"
        )


# G5
def assert_news_no_future(items: Sequence[NewsItem], as_of: datetime) -> None:
    for item in items:
        if item.posted_at > as_of:
            raise LookAheadError(
                f"news item {item.channel}#{item.message_id} posted at "
                f"{item.posted_at.isoformat()} > as_of {as_of.isoformat()}"
            )
