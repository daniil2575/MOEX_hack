"""Declarative base for all SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import DateTime, Numeric
from sqlalchemy.orm import DeclarativeBase, mapped_column
from sqlalchemy.orm import Mapped as Mapped


class Base(DeclarativeBase):
    """Project-wide declarative base. Imported by Alembic env.py for autogenerate."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        Decimal: Numeric(20, 8),
        datetime: DateTime(timezone=True),
    }


__all__ = ["Base", "mapped_column"]
