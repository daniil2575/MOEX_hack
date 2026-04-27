"""SQLAlchemy models — bot state of record.

Tables (audit-trail oriented; never UPDATE history rows in place):
    - instruments     : reference for tradable tickers (whitelist + sector + lot_size)
    - decisions       : Trader's TraderDecision output (immutable)
    - orders          : what was sent to broker; updated as broker reports state
    - fills           : executions per order; one order → N fills (partial fills)
    - equity          : daily NAV/cash/PnL snapshots for MDD/sharpe attribution

Money columns use `Decimal` (mapped to NUMERIC) — never float.
All timestamps are tz-aware (timestamptz).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class Instrument(Base):
    __tablename__ = "instruments"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    sector: Mapped[str] = mapped_column(String(32), nullable=False)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("lot_size > 0", name="ck_instruments_lot_size_positive"),
        CheckConstraint("char_length(currency) = 3", name="ck_instruments_currency_iso"),
    )


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(
        ForeignKey("instruments.ticker", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    qty_pct_nav: Mapped[Decimal] = mapped_column(nullable=False)
    stop_loss_pct: Mapped[Decimal] = mapped_column(nullable=False)
    take_profit_pct: Mapped[Decimal | None] = mapped_column(nullable=True)
    time_stop_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[str] = mapped_column(String(8), nullable=False)
    side_effect: Mapped[str | None] = mapped_column(String(16), nullable=True, default="speculative")
    decided_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    orders: Mapped[list[Order]] = relationship(back_populates="decision")

    __table_args__ = (
        CheckConstraint(
            "action IN ('BUY','SELL','HOLD')", name="ck_decisions_action_enum"
        ),
        CheckConstraint(
            "urgency IN ('MARKET','LIMIT')", name="ck_decisions_urgency_enum"
        ),
        CheckConstraint(
            "side_effect IS NULL OR side_effect IN ('speculative','hedge','rebalance')",
            name="ck_decisions_side_effect_enum",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_decisions_confidence_unit"
        ),
        Index("ix_decisions_decided_at", "decided_at"),
        Index("ix_decisions_ticker_decided_at", "ticker", "decided_at"),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(
        ForeignKey("instruments.ticker", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[Decimal] = mapped_column(nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(nullable=True)
    urgency: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    placed_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    decision: Mapped[Decision | None] = relationship(back_populates="orders")
    fills: Mapped[list[Fill]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("action IN ('BUY','SELL')", name="ck_orders_action_enum"),
        CheckConstraint("urgency IN ('MARKET','LIMIT')", name="ck_orders_urgency_enum"),
        CheckConstraint(
            "status IN ('PENDING','PARTIALLY_FILLED','FILLED','CANCELLED','REJECTED')",
            name="ck_orders_status_enum",
        ),
        CheckConstraint("qty > 0", name="ck_orders_qty_positive"),
        UniqueConstraint("broker_order_id", name="uq_orders_broker_order_id"),
        Index("ix_orders_decision_id", "decision_id"),
        Index("ix_orders_status_placed_at", "status", "placed_at"),
    )


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(nullable=False)
    commission_exchange: Mapped[Decimal] = mapped_column(nullable=False, default=0)
    commission_broker: Mapped[Decimal] = mapped_column(nullable=False, default=0)
    slippage: Mapped[Decimal | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    is_paper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    broker_fill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filled_at: Mapped[datetime] = mapped_column(nullable=False)

    order: Mapped[Order] = relationship(back_populates="fills")

    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_fills_qty_positive"),
        CheckConstraint("fill_price > 0", name="ck_fills_price_positive"),
        Index("ix_fills_order_id", "order_id"),
        Index("ix_fills_filled_at", "filled_at"),
    )


class Equity(Base):
    __tablename__ = "equity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_at: Mapped[datetime] = mapped_column(nullable=False)
    nav: Mapped[Decimal] = mapped_column(nullable=False)
    cash: Mapped[Decimal] = mapped_column(nullable=False)
    positions_value: Mapped[Decimal] = mapped_column(nullable=False)
    daily_pnl_pct: Mapped[Decimal] = mapped_column(nullable=False)
    daily_pnl_pct_intraday_peak: Mapped[Decimal] = mapped_column(nullable=False)
    is_paper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("nav >= 0", name="ck_equity_nav_nonneg"),
        Index("ix_equity_snapshot_at", "snapshot_at"),
    )
