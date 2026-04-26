"""Shared Pydantic contracts between agents, risk manager and execution.

Single source of truth — no duplicated models in submodules.
"""

from src.contracts.trader import TraderDecision

__all__ = ["TraderDecision"]
