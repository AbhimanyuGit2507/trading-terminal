"""Strict Provider Adapter protocols decoupling UI/services from data & broker implementations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar import ExpiryInfo, InstrumentSpec
from app.quant.margin import MarginBreakdown
from app.quant.mock_chain import MockChainData
from app.quant.payoff import PayoffLeg
from app.schemas.domain import (
    BatchOrderRequest,
    ExecutionResultSchema,
    IndexSymbol,
    LegQuoteSchema,
    WsTickFrameSchema,
)


class MarketDataProvider(Protocol):
    async def get_instrument_spec(
        self, symbol: str, as_of: datetime | date | None = None
    ) -> InstrumentSpec: ...

    async def get_expiries(
        self, symbol: str, as_of: datetime | None = None, count: int = 8
    ) -> list[ExpiryInfo]: ...

    async def get_option_chain(
        self, symbol: str, expiry: date | None = None, as_of: datetime | None = None
    ) -> tuple[MockChainData, list[ExpiryInfo]]: ...

    async def get_contract_quotes(
        self, contract_ids: list[str], as_of: datetime | None = None
    ) -> dict[str, LegQuoteSchema]: ...

    async def build_tick_frame(
        self,
        symbol: IndexSymbol,
        chain_expiry: date | None,
        active_contracts: list[str],
        as_of: datetime | None = None,
    ) -> WsTickFrameSchema: ...


class ExecutionProvider(Protocol):
    async def execute_orders(
        self,
        session: AsyncSession,
        req: BatchOrderRequest,
        idempotency_key: UUID,
    ) -> ExecutionResultSchema: ...


class MarginProvider(Protocol):
    async def estimate_margin(
        self,
        legs: list[PayoffLeg],
        spot: float,
        as_of: datetime,
    ) -> MarginBreakdown: ...

