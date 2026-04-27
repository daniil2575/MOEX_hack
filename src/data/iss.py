"""MOEX ISS API client — OHLCV candles for shares.

Reference: https://iss.moex.com/iss/reference/

Endpoint used here:
    /iss/engines/stock/markets/shares/securities/{ticker}/candles.json
        ?from=YYYY-MM-DD&till=YYYY-MM-DD&interval={1|10|60|24}&start={offset}

Pagination: ISS returns at most 500 rows per request — we walk forward by
the size of the previous page until an empty page is returned.

Intervals: 1 = 1m, 10 = 10m, 60 = 60m, 24 = 1d.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import httpx
import pandas as pd

Interval = Literal[1, 10, 60, 24]

BASE_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/securities"
PAGE_SIZE = 500
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)


async def fetch_candles(
    ticker: str,
    *,
    start: date,
    end: date,
    interval: Interval = 1,
    client: httpx.AsyncClient | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV candles for `ticker` over [start, end] at the given interval.

    Returns a DataFrame indexed by `begin` (UTC-naive in MSK as ISS reports it),
    with columns: open, high, low, close, value (RUB), volume (lots).

    Empty range → empty DataFrame with the canonical schema (avoids `KeyError`
    on downstream feature pipelines).
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    try:
        rows: list[list[object]] = []
        columns: list[str] = []
        offset = 0
        while True:
            assert client is not None
            r = await client.get(
                f"{BASE_URL}/{ticker}/candles.json",
                params={
                    "from": start.isoformat(),
                    "till": end.isoformat(),
                    "interval": int(interval),
                    "start": offset,
                },
            )
            r.raise_for_status()
            payload = r.json()["candles"]
            columns = payload["columns"]
            page = payload["data"]
            if not page:
                break
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                break
            offset += len(page)
    finally:
        if own_client and client is not None:
            await client.aclose()

    if not rows:
        return _empty_frame()

    df = pd.DataFrame(rows, columns=columns)
    df["begin"] = pd.to_datetime(df["begin"])
    df["end"] = pd.to_datetime(df["end"])
    for c in ("open", "close", "high", "low", "value", "volume"):
        df[c] = pd.Series([Decimal(str(v)) for v in df[c]], index=df.index, dtype="object")
    return df.set_index("begin").sort_index()


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["end", "open", "close", "high", "low", "value", "volume"],
        index=pd.DatetimeIndex([], name="begin"),
    )


def to_float_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Cast Decimal columns to float64 — convenience for indicator math.

    Risk-Manager and book-keeping must stay in Decimal; only feature pipelines
    are allowed to use float arithmetic where speed matters more than ULP.
    """
    out = df.copy()
    for c in ("open", "close", "high", "low", "value", "volume"):
        if c in out.columns:
            out[c] = out[c].astype(float)
    return out


def utc_naive_now() -> datetime:
    """Helper for tests that need a deterministic 'today' anchor in MSK."""
    return datetime.utcnow().replace(microsecond=0)
