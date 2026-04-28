"""Whitelisted Telegram channels for the news pipeline.

Selection criteria: Russian-language financial news, MOEX-relevant coverage,
publicly accessible (no joined groups), reasonable signal-to-noise. Reviewed
manually — adjust during the hackathon as agents reveal which channels carry
information vs noise.

Each entry is the channel `@username` without the `@` prefix.
"""

from __future__ import annotations

CHANNELS: tuple[str, ...] = (
    "markettwits",      # Аггрегатор рыночных новостей в реальном времени
    "cbrstocks",        # CBR / макроновости / IMOEX
    "marketmoney",      # Российский рынок акций, разборы эмитентов
    "smartlab_news",    # SmartLab — крупный портал, активная лента
    "bcs_express",      # БКС — обзоры эмитентов, IPO, дивиденды
    "rbc_news",         # РБК Новости — общеделовая повестка
)
