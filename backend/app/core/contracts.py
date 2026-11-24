"""Canonical ContractId formatting and parsing across all providers."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

ExchangeSegment = Literal["NSE_FNO", "BSE_FNO", "IDX_I"]
InstrumentKind = Literal["CE", "PE", "FUT", "SPOT"]


def _format_strike(strike: float) -> str:
    if float(strike).is_integer():
        return str(int(strike))
    return f"{strike:g}"


@dataclass(frozen=True, slots=True)
class ParsedContractId:
    exchange: ExchangeSegment
    symbol: str
    kind: InstrumentKind
    expiry: date | None = None
    strike: float | None = None

    @property
    def canonical(self) -> str:
        if self.kind == "SPOT":
            return f"{self.exchange}:{self.symbol}:SPOT"
        if self.expiry is None:
            raise ValueError(f"Expiry required for {self.kind} contract")
        exp_str = self.expiry.isoformat()
        if self.kind == "FUT":
            return f"{self.exchange}:{self.symbol}:{exp_str}:FUT"
        if self.strike is None:
            raise ValueError(f"Strike required for option contract {self.kind}")
        return f"{self.exchange}:{self.symbol}:{exp_str}:{_format_strike(self.strike)}:{self.kind}"


def build_option_contract_id(
    exchange: ExchangeSegment,
    symbol: str,
    expiry: date,
    strike: float,
    option_type: Literal["CE", "PE"],
) -> str:
    return ParsedContractId(
        exchange=exchange,
        symbol=symbol.upper(),
        kind=option_type,
        expiry=expiry,
        strike=float(strike),
    ).canonical


def build_future_contract_id(
    exchange: ExchangeSegment,
    symbol: str,
    expiry: date,
) -> str:
    return ParsedContractId(
        exchange=exchange,
        symbol=symbol.upper(),
        kind="FUT",
        expiry=expiry,
    ).canonical


def build_spot_contract_id(symbol: str) -> str:
    return ParsedContractId(
        exchange="IDX_I",
        symbol=symbol.upper(),
        kind="SPOT",
    ).canonical


def parse_contract_id(contract_id: str) -> ParsedContractId:
    parts = contract_id.strip().split(":")
    if len(parts) == 3 and parts[2] == "SPOT" and parts[0] == "IDX_I":
        return ParsedContractId(exchange="IDX_I", symbol=parts[1].upper(), kind="SPOT")
    if len(parts) == 4 and parts[3] == "FUT":
        exch = parts[0]
        if exch not in ("NSE_FNO", "BSE_FNO"):
            raise ValueError(f"Invalid F&O exchange in contract_id: {contract_id}")
        return ParsedContractId(
            exchange=exch,  # type: ignore[arg-type]
            symbol=parts[1].upper(),
            kind="FUT",
            expiry=date.fromisoformat(parts[2]),
        )
    if len(parts) == 5 and parts[4] in ("CE", "PE"):
        exch = parts[0]
        if exch not in ("NSE_FNO", "BSE_FNO"):
            raise ValueError(f"Invalid F&O exchange in contract_id: {contract_id}")
        return ParsedContractId(
            exchange=exch,  # type: ignore[arg-type]
            symbol=parts[1].upper(),
            kind=parts[4],  # type: ignore[arg-type]
            expiry=date.fromisoformat(parts[2]),
            strike=float(parts[3]),
        )
    raise ValueError(f"Unrecognized canonical contract_id format: {contract_id}")

