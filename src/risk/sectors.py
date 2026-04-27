"""IMOEX sector classification — single source of truth for Risk Manager.

Coverage: ~30 most-liquid IMOEX constituents as of Apr 2026. Sector taxonomy
is intentionally coarse (Banking / Energy / Metals / Tech / Retail / Telecom /
Financial / Chemicals / Transport / RealEstate / Utilities / Consumer) so that
`SectorExposureRule` aggregates meaningfully even if the index reshuffles.

Update procedure: when adding a ticker, also extend the trading whitelist via
`TRADING_WHITELIST` so `MarketState.whitelist` stays in sync.
"""

from __future__ import annotations

SECTOR_MAP: dict[str, str] = {
    # Banking
    "SBER": "Banking",
    "SBERP": "Banking",
    "VTBR": "Banking",
    "T": "Banking",  # ex-TCSG (T-Bank rebrand 2024)
    # Energy (oil & gas)
    "GAZP": "Energy",
    "LKOH": "Energy",
    "ROSN": "Energy",
    "NVTK": "Energy",
    "TATN": "Energy",
    "TATNP": "Energy",
    "SNGS": "Energy",
    "SNGSP": "Energy",
    "BANE": "Energy",
    # Metals & mining
    "GMKN": "Metals",
    "CHMF": "Metals",
    "NLMK": "Metals",
    "MAGN": "Metals",
    "PLZL": "Metals",
    "ALRS": "Metals",
    "RUAL": "Metals",
    # Tech
    "YNDX": "Tech",
    "VKCO": "Tech",
    "POSI": "Tech",
    "OZON": "Tech",
    "HEAD": "Tech",
    # Retail / Consumer
    "MGNT": "Retail",
    "FIVE": "Retail",
    "FIXP": "Retail",
    "BELU": "Consumer",
    # Telecom
    "MTSS": "Telecom",
    "RTKM": "Telecom",
    # Financial (exchange / brokers / insurance)
    "MOEX": "Financial",
    "RENI": "Financial",
    # Chemicals / fertilisers
    "PHOR": "Chemicals",
    "AKRN": "Chemicals",
    # Transport
    "AFLT": "Transport",
    "FLOT": "Transport",
    # Real estate / development
    "PIKK": "RealEstate",
    "LSRG": "RealEstate",
    "SMLT": "RealEstate",
    # Utilities (electricity)
    "IRAO": "Utilities",
    "HYDR": "Utilities",
    "FEES": "Utilities",
}

TRADING_WHITELIST: frozenset[str] = frozenset(SECTOR_MAP.keys())


def sector_of(ticker: str) -> str | None:
    return SECTOR_MAP.get(ticker)
