"""DhanHQ Security Master CSV cache and O(1) ContractId <-> (ExchangeSegment, SecurityId) mapper."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

import httpx

from app.core.calendar import IST, to_ist
from app.core.contracts import (
    build_future_contract_id,
    build_option_contract_id,
    build_spot_contract_id,
)

DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

# Fallback canonical Spot/Index security IDs on Dhan IDX_I
DEFAULT_INDEX_SECURITY_IDS: dict[str, tuple[str, str]] = {
    "IDX_I:NIFTY:SPOT": ("IDX_I", "13"),
    "IDX_I:BANKNIFTY:SPOT": ("IDX_I", "25"),
    "IDX_I:FINNIFTY:SPOT": ("IDX_I", "27"),
    "IDX_I:SENSEX:SPOT": ("IDX_I", "51"),
    "IDX_I:INDIAVIX:SPOT": ("IDX_I", "21"),
}

_SUPPORTED_UNDERLYINGS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"})

# Dhan numeric ExchangeSegment codes in binary WS packets -> string segment
BINARY_SEG_CODE_TO_NAME: dict[int, str] = {
    0: "IDX_I",
    1: "NSE_EQ",
    2: "NSE_FNO",
    3: "NSE_CURRENCY",
    4: "BSE_EQ",
    5: "MCX_COMM",
    7: "BSE_CURRENCY",
    8: "BSE_FNO",
}


def _normalize_segment(exch: str, seg: str) -> str:
    e = exch.strip().upper()
    s = seg.strip().upper()
    if s in ("I", "IDX_I", "INDEX"):
        return "IDX_I"
    if e == "NSE" and s in ("D", "FNO", "NSE_FNO"):
        return "NSE_FNO"
    if e == "BSE" and s in ("D", "FNO", "BSE_FNO"):
        return "BSE_FNO"
    if e == "NSE" and s in ("E", "EQ", "NSE_EQ"):
        return "NSE_EQ"
    return f"{e}_{s}" if s else e


def _parse_underlying(trading_sym: str, custom_sym: str) -> str | None:
    for raw in (trading_sym, custom_sym):
        up = raw.strip().upper()
        for sym in ("BANKNIFTY", "FINNIFTY", "NIFTY", "SENSEX"):
            if up == sym or up.startswith((f"{sym}-", f"{sym} ")):
                return sym
    return None


class DhanScripMaster:
    """Bidirectional O(1) lookup between canonical ContractId and Dhan (ExchangeSegment, SecurityId)."""

    def __init__(self, cache_path: str | Path) -> None:
        self.cache_path = Path(cache_path)
        self.contract_to_dhan: dict[str, tuple[str, str]] = dict(DEFAULT_INDEX_SECURITY_IDS)
        self.dhan_to_contract: dict[tuple[str, str], str] = {
            v: k for k, v in DEFAULT_INDEX_SECURITY_IDS.items()
        }
        self.loaded_at: datetime | None = None

    def is_fresh_today(self) -> bool:
        if not self.cache_path.exists():
            return False
        mtime_ist = datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=IST)
        today_ist = datetime.now(IST).date()
        return mtime_ist.date() == today_ist and len(self.contract_to_dhan) > len(
            DEFAULT_INDEX_SECURITY_IDS
        )

    def load_from_csv_text(self, csv_text: str) -> int:
        c2d: dict[str, tuple[str, str]] = dict(DEFAULT_INDEX_SECURITY_IDS)
        d2c: dict[tuple[str, str], str] = {
            v: k for k, v in DEFAULT_INDEX_SECURITY_IDS.items()
        }

        reader = csv.DictReader(io.StringIO(csv_text))
        count = 0
        for row in reader:
            exch = (row.get("SEM_EXM_EXCH_ID") or row.get("EXCH_ID") or "").strip().upper()
            seg = (row.get("SEM_SEGMENT") or row.get("SEGMENT") or "").strip().upper()
            sec_id = (row.get("SEM_SMST_SECURITY_ID") or row.get("SECURITY_ID") or "").strip()
            instr = (row.get("SEM_INSTRUMENT_NAME") or row.get("INSTRUMENT") or "").strip().upper()
            t_sym = (row.get("SEM_TRADING_SYMBOL") or row.get("UNDERLYING_SYMBOL") or "").strip()
            c_sym = (row.get("SEM_CUSTOM_SYMBOL") or row.get("SYMBOL_NAME") or "").strip()
            exp_raw = (row.get("SEM_EXPIRY_DATE") or row.get("SM_EXPIRY_DATE") or "").strip()
            strike_raw = (row.get("SEM_STRIKE_PRICE") or row.get("STRIKE_PRICE") or "").strip()
            opt_raw = (row.get("SEM_OPTION_TYPE") or row.get("OPTION_TYPE") or "").strip().upper()

            if not sec_id:
                continue

            norm_seg = _normalize_segment(exch, seg)
            if norm_seg == "IDX_I" or instr == "INDEX":
                up_sym = t_sym.upper().replace(" ", "")
                if "INDIAVIX" in up_sym:
                    cid = "IDX_I:INDIAVIX:SPOT"
                else:
                    sym = _parse_underlying(t_sym, c_sym)
                    if sym is None:
                        continue
                    cid = build_spot_contract_id(sym)
                key = ("IDX_I", sec_id)
                c2d[cid] = key
                d2c[key] = cid
                count += 1
                continue

            if norm_seg not in ("NSE_FNO", "BSE_FNO") or instr not in ("FUTIDX", "OPTIDX"):
                continue

            underlying = _parse_underlying(t_sym, c_sym)
            if underlying not in _SUPPORTED_UNDERLYINGS or not exp_raw:
                continue

            try:
                exp_date = date.fromisoformat(exp_raw[:10])
            except ValueError:
                continue

            exch_seg = "NSE_FNO" if norm_seg == "NSE_FNO" else "BSE_FNO"
            if instr == "FUTIDX":
                cid = build_future_contract_id(exch_seg, underlying, exp_date)  # type: ignore[arg-type]
            else:
                if opt_raw not in ("CE", "PE"):
                    continue
                try:
                    strike_val = float(strike_raw)
                except ValueError:
                    continue
                cid = build_option_contract_id(
                    exch_seg, underlying, exp_date, strike_val, opt_raw  # type: ignore[arg-type]
                )

            key = (exch_seg, sec_id)
            c2d[cid] = key
            d2c[key] = cid
            count += 1

        self.contract_to_dhan = c2d
        self.dhan_to_contract = d2c
        self.loaded_at = datetime.now(IST)
        return count

    async def ensure_loaded(
        self,
        force_refresh: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ) -> int:
        """Load cached CSV if fresh today; otherwise download from Dhan and cache locally."""
        today_ist = datetime.now(IST).date()
        if (
            not force_refresh
            and self.loaded_at is not None
            and self.loaded_at.date() == today_ist
            and len(self.contract_to_dhan) > len(DEFAULT_INDEX_SECURITY_IDS)
        ):
            return len(self.contract_to_dhan)

        if not force_refresh and self.cache_path.exists():
            mtime_ist = to_ist(datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=IST))
            if mtime_ist.date() == today_ist:
                if len(self.contract_to_dhan) > len(DEFAULT_INDEX_SECURITY_IDS):
                    return len(self.contract_to_dhan)
                text = self.cache_path.read_text(encoding="utf-8", errors="ignore")
                return self.load_from_csv_text(text)

        try:
            if http_client is not None:
                resp = await http_client.get(DHAN_SCRIP_MASTER_URL)
                resp.raise_for_status()
                csv_text = resp.text
            else:
                async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
                    resp = await client.get(DHAN_SCRIP_MASTER_URL)
                    resp.raise_for_status()
                    csv_text = resp.text

            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(csv_text, encoding="utf-8")
            return self.load_from_csv_text(csv_text)
        except (httpx.HTTPError, OSError, ValueError):
            if self.cache_path.exists():
                text = self.cache_path.read_text(encoding="utf-8", errors="ignore")
                return self.load_from_csv_text(text)
            return len(self.contract_to_dhan)

    def to_dhan(self, contract_id: str) -> tuple[str, str] | None:
        return self.contract_to_dhan.get(contract_id)

    def to_contract(self, exchange_segment: str | int, security_id: str | int) -> str | None:
        seg = (
            BINARY_SEG_CODE_TO_NAME.get(exchange_segment, str(exchange_segment))
            if isinstance(exchange_segment, int)
            else str(exchange_segment)
        )
        return self.dhan_to_contract.get((seg, str(security_id)))
