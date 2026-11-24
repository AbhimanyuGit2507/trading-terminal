"""DhanHQ v2 /charts/rollingoption historical ingestion & Hive-partitioned Parquet writer."""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import duckdb
import httpx

from app.core.calendar import IST, get_expiries, get_instrument_spec, time_to_expiry_years, to_ist
from app.quant.black76 import implied_volatility_black76

DHAN_ROLLING_OPTION_URL = "https://api.dhan.co/v2/charts/rollingoption"

DHAN_INDEX_SECURITY_IDS: dict[str, str] = {
    "NIFTY": "13",
    "BANKNIFTY": "25",
    "FINNIFTY": "27",
    "SENSEX": "51",
}


@dataclass(frozen=True, slots=True)
class HistoricalOptionBar:
    timestamp_ist: datetime  # naive IST wall-clock YYYY-MM-DD HH:MM:00
    symbol: str
    expiry: date
    strike: float
    option_type: Literal["CE", "PE"]
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int
    iv: float  # annualized decimal e.g. 0.145
    spot_close: float
    futures_close: float


@dataclass(frozen=True, slots=True)
class IngestionStats:
    symbol: str
    bars_written: int
    files_written: int
    iv_backfilled: int
    requests_made: int


def chunk_date_windows(
    from_date: date, to_date: date, max_days: int = 30
) -> list[tuple[date, date]]:
    if to_date < from_date:
        return []
    windows: list[tuple[date, date]] = []
    cur = from_date
    while cur <= to_date:
        end = min(to_date, cur + timedelta(days=max_days - 1))
        windows.append((cur, end))
        cur = end + timedelta(days=1)
    return windows


def write_parquet_partitions(
    parquet_dir: str | Path,
    bars: list[HistoricalOptionBar],
) -> int:
    """Write/merge HistoricalOptionBar rows into Hive-partitioned Parquet via stateless DuckDB."""
    if not bars:
        return 0

    base_dir = Path(parquet_dir)
    grouped: dict[tuple[str, int, int], list[HistoricalOptionBar]] = defaultdict(list)
    for b in bars:
        grouped[(b.symbol.upper(), b.timestamp_ist.year, b.timestamp_ist.month)].append(b)

    files_written = 0
    for (sym, year, month), partition_bars in grouped.items():
        part_dir = base_dir / f"symbol={sym}" / f"year={year:04d}" / f"month={month:02d}"
        part_dir.mkdir(parents=True, exist_ok=True)
        out_path = part_dir / "data.parquet"
        tmp_path = part_dir / f".tmp_{os.getpid()}.parquet"

        rows_tuples = [
            (
                b.timestamp_ist.replace(tzinfo=None),
                b.symbol.upper(),
                b.expiry,
                float(b.strike),
                b.option_type,
                float(b.open),
                float(b.high),
                float(b.low),
                float(b.close),
                int(b.volume),
                int(b.oi),
                float(b.iv),
                float(b.spot_close),
                float(b.futures_close),
            )
            for b in partition_bars
        ]

        with duckdb.connect(":memory:") as con:
            con.execute(
                """
                CREATE TABLE incoming (
                    timestamp_ist TIMESTAMP,
                    symbol VARCHAR,
                    expiry DATE,
                    strike DOUBLE,
                    option_type VARCHAR,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume BIGINT,
                    oi BIGINT,
                    iv DOUBLE,
                    spot_close DOUBLE,
                    futures_close DOUBLE
                )
                """
            )
            con.executemany(
                "INSERT INTO incoming VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows_tuples,
            )

            if out_path.exists():
                existing_sql = str(out_path).replace("'", "''")
                con.execute(
                    f"""
                    CREATE TABLE merged AS
                    SELECT * FROM (
                        SELECT *, 1 AS _prio FROM incoming
                        UNION ALL
                        SELECT *, 2 AS _prio FROM read_parquet('{existing_sql}')
                    )
                    QUALIFY ROW_NUMBER() OVER (
                        PARTITION BY timestamp_ist, expiry, strike, option_type
                        ORDER BY _prio ASC
                    ) = 1
                    """
                )
                con.execute("ALTER TABLE merged DROP COLUMN _prio")
                target_table = "merged"
            else:
                target_table = "incoming"

            tmp_sql = str(tmp_path).replace("'", "''")
            con.execute(
                f"""
                COPY (
                    SELECT * FROM {target_table}
                    ORDER BY timestamp_ist, expiry, strike, option_type
                ) TO '{tmp_sql}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )

        os.replace(tmp_path, out_path)
        files_written += 1

    return files_written


def _parse_bar_timestamp(raw_ts: Any) -> datetime:
    if isinstance(raw_ts, (int, float)):
        # Dhan returns epoch seconds (or ms if > 1e11)
        sec = float(raw_ts) / 1000.0 if raw_ts > 1e11 else float(raw_ts)
        dt_utc = datetime.fromtimestamp(sec, tz=UTC)
        dt_ist = dt_utc.astimezone(IST)
        return dt_ist.replace(second=0, microsecond=0, tzinfo=None)
    if isinstance(raw_ts, str):
        parsed = datetime.fromisoformat(raw_ts)
        dt_ist = to_ist(parsed)
        return dt_ist.replace(second=0, microsecond=0, tzinfo=None)
    raise ValueError(f"Unsupported timestamp format: {raw_ts!r}")


def parse_dhan_rolling_payload(
    symbol: str,
    payload: dict[str, Any],
    option_type: Literal["CE", "PE"],
    expiry_flag: Literal["WEEK", "MONTH"] = "WEEK",
) -> tuple[list[HistoricalOptionBar], int]:
    """Normalize DhanHQ /charts/rollingoption payload into HistoricalOptionBar rows."""
    sym = symbol.upper()
    data = payload.get("data", payload)
    side_key = "ce" if option_type == "CE" else "pe"
    block = data.get(side_key, data)

    # Support both Dhan's parallel-array structure and list-of-dicts
    if isinstance(block, list):
        records = block
    elif isinstance(block, dict):
        timestamps = block.get("timestamp") or []
        n = len(timestamps)
        records = [
            {
                "timestamp": timestamps[i],
                "open": (block.get("open") or [0.0] * n)[i],
                "high": (block.get("high") or [0.0] * n)[i],
                "low": (block.get("low") or [0.0] * n)[i],
                "close": (block.get("close") or [0.0] * n)[i],
                "volume": (block.get("volume") or [0] * n)[i],
                "oi": (block.get("oi") or [0] * n)[i],
                "iv": (block.get("iv") or [0.0] * n)[i],
                "spot": (block.get("spot") or [0.0] * n)[i],
                "strike": (block.get("strike") or [0.0] * n)[i],
                "expiry": (block.get("expiry") or [None] * n)[i],
            }
            for i in range(n)
        ]
    else:
        return [], 0

    bars: list[HistoricalOptionBar] = []
    iv_backfilled = 0
    spec = get_instrument_spec(sym)

    for rec in records:
        ts_naive = _parse_bar_timestamp(rec["timestamp"])
        ts_ist = ts_naive.replace(tzinfo=IST)
        spot_val = float(rec.get("spot") or 0.0)
        close_px = float(rec.get("close") or 0.0)
        strike_val = float(rec.get("strike") or 0.0)
        if strike_val <= 0.0 and spot_val > 0.0:
            strike_val = float(round(spot_val / spec.strike_step) * spec.strike_step)

        raw_exp = rec.get("expiry")
        if raw_exp:
            exp_date = date.fromisoformat(str(raw_exp)[:10])
        else:
            expiries = get_expiries(sym, ts_ist, count=6)
            matched = [
                e for e in expiries if (e.is_monthly if expiry_flag == "MONTH" else True)
            ]
            exp_date = (matched[0] if matched else expiries[0]).expiry_date

        t_years = max(time_to_expiry_years(ts_ist, exp_date), 1.0 / (365.0 * 24.0))
        fut_close = float(rec.get("futures_close") or (spot_val * math.exp(0.065 * t_years)))

        raw_iv = float(rec.get("iv") or 0.0)
        # Dhan reports IV as percentage (e.g. 14.2) when present; normalize to decimal
        iv_dec = raw_iv / 100.0 if raw_iv > 1.5 else raw_iv
        if iv_dec <= 0.0 and close_px > 0.0 and fut_close > 0.0 and strike_val > 0.0:
            iv_dec = implied_volatility_black76(
                market_price=close_px,
                forward=fut_close,
                strike=strike_val,
                t_years=t_years,
                option_type=option_type,
                r=0.0,
            )
            iv_backfilled += 1

        bars.append(
            HistoricalOptionBar(
                timestamp_ist=ts_naive,
                symbol=sym,
                expiry=exp_date,
                strike=strike_val,
                option_type=option_type,
                open=float(rec.get("open") or close_px),
                high=float(rec.get("high") or close_px),
                low=float(rec.get("low") or close_px),
                close=close_px,
                volume=int(rec.get("volume") or 0),
                oi=int(rec.get("oi") or 0),
                iv=round(max(iv_dec, 0.0), 6),
                spot_close=round(spot_val, 2),
                futures_close=round(fut_close, 2),
            )
        )

    return bars, iv_backfilled


class DhanRollingOptionIngestor:
    """Async rate-limited DhanHQ v2 /charts/rollingoption ingestor writing Hive Parquet."""

    def __init__(
        self,
        client_id: str,
        access_token: str,
        parquet_dir: str | Path,
        max_req_per_sec: float = 2.0,
        max_retries: int = 4,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.access_token = access_token
        self.parquet_dir = Path(parquet_dir)
        self._min_interval = 1.0 / max(max_req_per_sec, 0.1)
        self._max_retries = max_retries
        self._external_client = http_client
        self._rate_lock = asyncio.Lock()
        self._last_req_ts = 0.0

    async def _throttle(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_req_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_req_ts = time.monotonic()

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "access-token": self.access_token,
            "client-id": self.client_id,
        }
        for attempt in range(self._max_retries):
            await self._throttle()
            try:
                resp = await client.post(DHAN_ROLLING_OPTION_URL, json=body, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt == self._max_retries - 1:
                        resp.raise_for_status()
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]
            except httpx.HTTPError:
                if attempt == self._max_retries - 1:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
        return {}

    async def ingest_symbol(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        strikes_each_side: int = 15,
        expiry_flag: Literal["WEEK", "MONTH"] = "WEEK",
    ) -> IngestionStats:
        sym = symbol.upper()
        if sym not in DHAN_INDEX_SECURITY_IDS:
            raise ValueError(f"Unsupported symbol for Dhan ingestion: {sym}")
        if not self.access_token or not self.client_id:
            raise RuntimeError(
                "DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN must be configured in .env before live ingestion."
            )

        spec = get_instrument_spec(sym, to_date)
        eff_flag: Literal["WEEK", "MONTH"] = expiry_flag if spec.has_weekly else "MONTH"
        windows = chunk_date_windows(from_date, to_date, max_days=30)
        strike_offsets = [
            "ATM" if off == 0 else (f"ATM+{off}" if off > 0 else f"ATM{off}")
            for off in range(-strikes_each_side, strikes_each_side + 1)
        ]

        all_bars: list[HistoricalOptionBar] = []
        iv_backfilled = 0
        requests_made = 0

        async def _run(client: httpx.AsyncClient) -> None:
            nonlocal iv_backfilled, requests_made
            for w_start, w_end in windows:
                for strike_label in strike_offsets:
                    for opt_side, drv_type in (("CE", "CALL"), ("PE", "PUT")):
                        body = {
                            "exchangeSegment": spec.exchange,
                            "interval": "1",
                            "securityId": DHAN_INDEX_SECURITY_IDS[sym],
                            "instrument": "OPTIDX",
                            "expiryFlag": eff_flag,
                            "expiryCode": 1,
                            "strike": strike_label,
                            "drvOptionType": drv_type,
                            "requiredData": [
                                "open",
                                "high",
                                "low",
                                "close",
                                "volume",
                                "oi",
                                "iv",
                                "spot",
                            ],
                            "fromDate": w_start.isoformat(),
                            "toDate": w_end.isoformat(),
                        }
                        payload = await self._post_with_retry(client, body)
                        requests_made += 1
                        parsed, filled = parse_dhan_rolling_payload(
                            sym, payload, opt_side, expiry_flag=eff_flag  # type: ignore[arg-type]
                        )
                        all_bars.extend(parsed)
                        iv_backfilled += filled

        if self._external_client is not None:
            await _run(self._external_client)
        else:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await _run(client)

        files_written = write_parquet_partitions(self.parquet_dir, all_bars)
        return IngestionStats(
            symbol=sym,
            bars_written=len(all_bars),
            files_written=files_written,
            iv_backfilled=iv_backfilled,
            requests_made=requests_made,
        )
