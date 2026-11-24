"""Canonical Pydantic v2 API schemas exported to OpenAPI -> /shared/types/api.ts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

IndexSymbol = Literal["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
ExchangeSegment = Literal["NSE_FNO", "BSE_FNO"]
OptionSide = Literal["BUY", "SELL"]
LegOptionType = Literal["CE", "PE", "FUT"]
TradingMode = Literal[
    "SIMULATOR", "PAPER", "PAPER_LIVE", "SANDBOX", "DHAN_SANDBOX", "LIVE", "DHAN_LIVE"
]
ExecutionMode = Literal["SIMULATOR", "PAPER_LIVE", "DHAN_SANDBOX", "DHAN_LIVE"]
ProductType = Literal["MARGIN", "INTRADAY"]
BrokerOrderType = Literal["LIMIT", "MARKET"]
FeedStatus = Literal["LIVE_DHAN", "MOCK_FALLBACK", "TOKEN_EXPIRED", "DISCONNECTED"]
OrderLifecycleAction = Literal[
    "OPEN_LEGS",
    "ADD_LOTS",
    "PARTIAL_EXIT",
    "FLIP_SIDE",
    "SQUARE_OFF_ALL",
    "SETTLED_AT_EXPIRY",
]
SimulatorStepSize = Literal["-1d", "-30m", "-15m", "-5m", "-1m", "+1m", "+5m", "+15m", "+30m", "+1d"]


class InstrumentSpecSchema(BaseModel):
    symbol: IndexSymbol
    exchange: ExchangeSegment
    lot_size: int
    strike_step: int
    tick_size: float
    freeze_qty: int
    has_weekly: bool
    expiry_weekday: int
    effective_from: date


class ExpiryInfoSchema(BaseModel):
    expiry_date: date
    label: str
    is_weekly: bool
    is_monthly: bool
    dte: int
    lot_size: int


class LegQuoteSchema(BaseModel):
    """Live/simulated quote for any active leg contract (supports multi-expiry activeLegQuotes)."""

    contract_id: str
    expiry: date
    strike: float | None = None
    option_type: LegOptionType
    ltp: float
    bid: float
    ask: float
    iv: float  # percentage e.g. 14.25
    delta: float
    gamma: float
    theta: float  # per calendar day
    vega: float
    forward_price: float
    updated_at: datetime


class QuoteBatchRequest(BaseModel):
    contract_ids: list[str] = Field(min_length=1, max_length=100)
    as_of: datetime | None = None


class QuoteBatchResponse(BaseModel):
    as_of: datetime
    quotes: dict[str, LegQuoteSchema]


class OptionChainRowSchema(BaseModel):
    strike: float
    ce_contract_id: str
    pe_contract_id: str
    ce_ltp: float
    ce_bid: float
    ce_ask: float
    ce_iv: float
    ce_delta: float
    ce_gamma: float
    ce_theta: float
    ce_vega: float
    ce_oi: int
    ce_oi_change: int
    pe_ltp: float
    pe_bid: float
    pe_ask: float
    pe_iv: float
    pe_delta: float
    pe_gamma: float
    pe_theta: float
    pe_vega: float
    pe_oi: int
    pe_oi_change: int


class OptionChainSnapshotSchema(BaseModel):
    symbol: IndexSymbol
    exchange: ExchangeSegment
    expiry: date
    as_of: datetime
    spot: float
    futures_price: float
    forward_price: float
    india_vix: float
    atm_strike: float
    lot_size: int
    strike_step: int
    futures_contract_id: str
    feed_status: FeedStatus = "MOCK_FALLBACK"
    expiries: list[ExpiryInfoSchema]
    rows: list[OptionChainRowSchema]


class StrategyLegSchema(BaseModel):
    leg_id: str
    contract_id: str
    symbol: IndexSymbol
    exchange: ExchangeSegment = "NSE_FNO"
    expiry: date
    strike: float | None = None
    option_type: LegOptionType
    side: OptionSide
    lots: int = Field(ge=1)
    lot_size: int = Field(ge=1)
    entry_price: float = Field(ge=0.0)
    entry_iv: float = Field(ge=0.0)  # decimal e.g. 0.145
    forward_at_base: float | None = None
    enabled: bool = True
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    product_type: ProductType | None = None
    target_price: float | None = Field(default=None, ge=0.0)
    stop_loss_price: float | None = Field(default=None, ge=0.0)
    trailing_jump: float | None = Field(default=None, ge=0.0)


class ClosedLegRecordSchema(BaseModel):
    leg_id: str
    contract_id: str
    symbol: IndexSymbol
    expiry: date
    strike: float | None = None
    option_type: LegOptionType
    side: OptionSide
    lots_closed: int = Field(ge=1)
    lot_size: int = Field(ge=1)
    entry_price: float
    exit_price: float
    realized_pnl: float
    closed_at: datetime


class WhatIfParamsSchema(BaseModel):
    target_spot: float
    target_datetime: datetime
    iv_shift_pct: float = 0.0


class PayoffEvaluateRequest(BaseModel):
    symbol: IndexSymbol
    spot: float
    as_of: datetime
    legs: list[StrategyLegSchema]
    what_if: WhatIfParamsSchema | None = None
    realized_pnl: float = 0.0
    include_charges: bool = False
    atm_iv: float = 0.14


class PayoffPointSchema(BaseModel):
    spot: float
    expiry_pnl: float
    target_pnl: float


class NetGreeksSchema(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float


class MarginBreakdownSchema(BaseModel):
    span_proxy: float
    exposure_proxy: float
    total_margin: float
    hedge_benefit: float
    margin_source: str = "estimated_stress"


class PayoffEvaluateResponse(BaseModel):
    points: list[PayoffPointSchema]
    breakevens: list[float]
    target_breakevens: list[float]
    max_profit: float | None
    max_loss: float | None
    max_profit_unlimited: bool
    max_loss_unlimited: bool
    risk_reward: float | None
    pop: float
    net_greeks: NetGreeksSchema
    current_mtm_pnl: float
    estimated_charges: float
    margin: MarginBreakdownSchema
    sd_1_low: float
    sd_1_high: float
    sd_2_low: float
    sd_2_high: float


class OrderLegInstruction(BaseModel):
    leg_id: str | None = None
    contract_id: str
    side: OptionSide
    lots: int = Field(ge=1)
    lot_size: int | None = Field(default=None, ge=1)
    limit_price: Decimal | None = None
    entry_price: Decimal | None = None  # used to compute realized_pnl_delta on exits
    product_type: ProductType | None = None
    order_type: BrokerOrderType | None = None
    target_price: Decimal | None = Field(default=None, ge=Decimal(0))
    stop_loss_price: Decimal | None = Field(default=None, ge=Decimal(0))
    trailing_jump: Decimal | None = Field(default=None, ge=Decimal(0))


class BatchOrderRequest(BaseModel):
    idempotency_key: UUID | None = None
    strategy_id: UUID | None = None
    parent_order_id: UUID | None = None
    trading_mode: TradingMode = "SIMULATOR"
    action: OrderLifecycleAction = "OPEN_LEGS"
    product_type: ProductType | None = None
    order_type: BrokerOrderType | None = None
    limit_buffer_ticks: int | None = Field(default=None, ge=0, le=50)
    slice_if_frozen: bool = True
    as_of: datetime | None = None
    legs: list[OrderLegInstruction] = Field(min_length=1)


class OrderFillSchema(BaseModel):
    order_id: UUID
    parent_order_id: UUID | None = None
    slice_index: int
    total_slices: int
    is_parent: bool = False
    contract_id: str
    side: OptionSide
    action: str
    lots: int
    quantity: int
    fill_price: Decimal
    status: Literal["PENDING", "TRANSIT", "TRADED", "FILLED", "REJECTED", "CANCELLED"]
    broker_order_id: str | None = None
    is_super_order: bool = False
    oms_error: str | None = None
    executed_at: datetime


class ExecutionResultSchema(BaseModel):
    idempotency_key: UUID
    deduplicated: bool = False
    trading_mode: TradingMode
    action: OrderLifecycleAction
    realized_pnl_delta: Decimal = Decimal("0.00")
    fills: list[OrderFillSchema]


class OrderAuditLogSchema(BaseModel):
    id: UUID
    strategy_id: UUID | None = None
    idempotency_key: UUID
    parent_order_id: UUID | None = None
    slice_index: int
    total_slices: int
    trading_mode: str
    contract_id: str
    side: str
    action: str
    lots: int
    quantity: int
    limit_price: Decimal | None = None
    fill_price: Decimal | None = None
    status: str
    broker_order_id: str | None = None
    is_super_order: bool = False
    oms_error: str | None = None
    executed_at: datetime
    created_at: datetime


class StrategyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    symbol: IndexSymbol
    mode: Literal["builder", "simulator", "paper", "live"] = "builder"
    legs: list[StrategyLegSchema] = Field(default_factory=list)
    closed_legs: list[ClosedLegRecordSchema] = Field(default_factory=list)
    realized_pnl: Decimal = Decimal("0.00")
    metadata: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class StrategyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    symbol: IndexSymbol | None = None
    mode: Literal["builder", "simulator", "paper", "live"] | None = None
    legs: list[StrategyLegSchema] | None = None
    closed_legs: list[ClosedLegRecordSchema] | None = None
    realized_pnl: Decimal | None = None
    metadata: dict[str, Any] | None = None
    notes: str | None = None


class StrategyResponse(BaseModel):
    id: UUID
    name: str
    symbol: IndexSymbol
    mode: str
    legs: list[StrategyLegSchema]
    closed_legs: list[ClosedLegRecordSchema]
    realized_pnl: Decimal
    metadata: dict[str, Any]
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class SettledLegEventSchema(BaseModel):
    leg_id: str
    contract_id: str
    symbol: IndexSymbol
    expiry: date
    strike: float | None = None
    option_type: LegOptionType
    side: OptionSide
    lots_settled: int
    lot_size: int
    entry_price: float
    settlement_price: float
    realized_pnl: float
    settled_at: datetime
    order_id: UUID | None = None


class AvailableDatesResponse(BaseModel):
    symbol: IndexSymbol
    dates: list[date]
    expiry_dates: list[date]
    min_date: date | None = None
    max_date: date | None = None
    data_source: Literal["parquet", "mock_fallback"]


class SimulatorJumpRequest(BaseModel):
    symbol: IndexSymbol = "NIFTY"
    target_dt: datetime
    chain_expiry: date | None = None
    active_contracts: list[str] = Field(default_factory=list)
    open_legs: list[StrategyLegSchema] = Field(default_factory=list)


class SimulatorStepRequest(BaseModel):
    symbol: IndexSymbol = "NIFTY"
    current_as_of: datetime
    step: SimulatorStepSize
    chain_expiry: date | None = None
    active_contracts: list[str] = Field(default_factory=list)
    open_legs: list[StrategyLegSchema] = Field(default_factory=list)


class SimulatorStepResponse(BaseModel):
    symbol: IndexSymbol
    previous_as_of: datetime
    new_as_of: datetime
    data_source: Literal["parquet", "mock_fallback"] = "parquet"
    end_of_data: bool = False
    chain: OptionChainSnapshotSchema
    leg_quotes: dict[str, LegQuoteSchema]
    settled_legs: list[SettledLegEventSchema] = Field(default_factory=list)
    realized_pnl_delta: Decimal = Decimal("0.00")


class WsSubscribeMessage(BaseModel):
    action: Literal["subscribe", "unsubscribe", "ping"]
    symbol: IndexSymbol = "NIFTY"
    chain_expiry: date | None = None
    active_contracts: list[str] = Field(default_factory=list)


class WsTickFrameSchema(BaseModel):
    type: Literal["tick", "pong", "error"]
    feed_status: FeedStatus = "MOCK_FALLBACK"
    symbol: IndexSymbol | None = None
    chain_expiry: date | None = None
    as_of: datetime | None = None
    spot: float | None = None
    futures_price: float | None = None
    forward_price: float | None = None
    india_vix: float | None = None
    atm_strike: float | None = None
    chain_deltas: list[OptionChainRowSchema] = Field(default_factory=list)
    leg_quotes: dict[str, LegQuoteSchema] = Field(default_factory=dict)
    message: str | None = None


class DhanTokenSaveRequest(BaseModel):
    client_id: str = Field(min_length=2, max_length=64)
    access_token: str = Field(min_length=8)


class DhanTotpGenerateRequest(BaseModel):
    client_id: str = Field(min_length=2, max_length=64)
    pin: str = Field(min_length=4, max_length=12)
    totp: str = Field(min_length=6, max_length=8)


class DhanStatusResponse(BaseModel):
    connected: bool
    mode: FeedStatus
    client_id_masked: str | None = None
    account_name: str | None = None
    ucc: str | None = None
    expires_at: datetime | None = None
    seconds_remaining: int | None = None
    message: str | None = None


class RiskStateResponse(BaseModel):
    active_execution_mode: ExecutionMode = "PAPER_LIVE"
    daily_kill_switch_active: bool = False
    kill_switch_reason: str | None = None
    kill_switch_engaged_at: datetime | None = None
    daily_max_loss_inr: float = 25000.0
    max_lots_per_order: int = 50
    max_open_lots: int = 100
    max_daily_trades: int = 50
    product_type: ProductType = "MARGIN"
    limit_buffer_ticks: int = 2
    trades_today: int = 0
    net_mtm_inr: float = 0.0


class RiskConfigUpdateRequest(BaseModel):
    daily_max_loss_inr: float | None = Field(default=None, gt=0.0)
    max_lots_per_order: int | None = Field(default=None, ge=1, le=1000)
    max_open_lots: int | None = Field(default=None, ge=1, le=5000)
    max_daily_trades: int | None = Field(default=None, ge=1, le=1000)
    product_type: ProductType | None = None
    limit_buffer_ticks: int | None = Field(default=None, ge=0, le=50)


class ExecutionModeSwitchRequest(BaseModel):
    mode: ExecutionMode
    confirmed: bool = False


class KillSwitchTriggerRequest(BaseModel):
    reason: str = Field(default="Manual Emergency Exit triggered by user", max_length=256)


class KillSwitchUnlockRequest(BaseModel):
    confirmation_text: str = Field(min_length=4, max_length=64)


class KillSwitchTriggerResponse(BaseModel):
    kill_switch_active: bool
    cancelled_orders: int
    exited_positions: int
    fallback_exits: int
    errors: list[str] = Field(default_factory=list)
    triggered_at: datetime
    reason: str


class FundLimitResponse(BaseModel):
    available_balance: float
    utilized_amount: float = 0.0
    collateral_amount: float = 0.0
    environment: Literal["SANDBOX", "LIVE"] = "SANDBOX"
    source: str = "dhan_api"


class BrokerOrderRecordSchema(BaseModel):
    order_id: str
    correlation_id: str | None = None
    order_status: str
    transaction_type: str
    exchange_segment: str
    security_id: str
    trading_symbol: str | None = None
    product_type: str | None = None
    order_type: str | None = None
    quantity: int = 0
    filled_qty: int = 0
    price: float = 0.0
    average_traded_price: float = 0.0
    is_super_order: bool = False
    oms_error_description: str | None = None
    create_time: str | None = None


class BrokerPositionRecordSchema(BaseModel):
    trading_symbol: str
    exchange_segment: str
    security_id: str
    product_type: str
    net_qty: int
    buy_avg: float = 0.0
    sell_avg: float = 0.0
    realized_profit: float = 0.0
    unrealized_profit: float = 0.0
    multiplier: int = 1


class BrokerReconcileResponse(BaseModel):
    environment: Literal["SANDBOX", "LIVE"]
    updated_orders: int
    orders: list[BrokerOrderRecordSchema]
    positions: list[BrokerPositionRecordSchema]


class EgressIpResponse(BaseModel):
    public_ip: str | None = None
    provider: str = "api.ipify.org"
    checked_at: datetime
    error: str | None = None
