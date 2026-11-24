"""ParquetHistoricalProvider: stateless :memory: DuckDB reader over Hive-partitioned Parquet."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np

from app.core.calendar import (
    IST,
    ExpiryInfo,
    InstrumentSpec,
    get_instrument_spec,
    round_to_tick,
    time_to_expiry_years,
    to_ist,
)
from app.core.calendar import (
    get_expiries as calendar_get_expiries,
)
from app.core.contracts import (
    build_future_contract_id,
    build_option_contract_id,
    parse_contract_id,
)
from app.quant.black76 import (
    compute_synthetic_forward,
    greeks_black76_scalar,
    greeks_black76_vectorized,
    implied_volatility_black76,
)
from app.quant.mock_chain import DEFAULT_VIX, MockChainData, MockOptionRow, svi_skew_iv
from app.schemas.domain import IndexSymbol, LegQuoteSchema, OptionChainRowSchema, WsTickFrameSchema


class ParquetHistoricalProvider:
    """MarketDataProvider reading 1-minute historical bars from Hive-partitioned Parquet.

    Uses stateless `:memory:` DuckDB connections per query for zero write/read lock contention.
    """

    def __init__(self, parquet_dir: str | Path, forward_fill_minutes: int = 15) -> None:
        self.parquet_dir = Path(parquet_dir)
        self.forward_fill_minutes = forward_fill_minutes

    def _partition_path(self, symbol: str, d: date) -> Path:
        return (
            self.parquet_dir
            / f"symbol={symbol.upper()}"
            / f"year={d.year:04d}"
            / f"month={d.month:02d}"
            / "data.parquet"
        )

    def _symbol_glob(self, symbol: str) -> str:
        return str(self.parquet_dir / f"symbol={symbol.upper()}" / "year=*" / "month=*" / "*.parquet")

    def get_available_dates(self, symbol: str) -> list[date]:
        sym_dir = self.parquet_dir / f"symbol={symbol.upper()}"
        if not sym_dir.exists() or not any(sym_dir.rglob("*.parquet")):
            return []
        glob_sql = self._symbol_glob(symbol).replace("'", "''")
        with duckdb.connect(":memory:") as con:
            rows = con.execute(
                f"""
                SELECT DISTINCT CAST(timestamp_ist AS DATE) AS d
                FROM read_parquet('{glob_sql}', hive_partitioning=true)
                ORDER BY d ASC
                """
            ).fetchall()
        return [r[0] for r in rows]

    def has_data_for_date(self, symbol: str, d: date) -> bool:
        part_path = self._partition_path(symbol, d)
        if not part_path.exists():
            return False
        p_sql = str(part_path).replace("'", "''")
        with duckdb.connect(":memory:") as con:
            row = con.execute(
                f"""
                SELECT 1
                FROM read_parquet('{p_sql}')
                WHERE CAST(timestamp_ist AS DATE) = ?
                LIMIT 1
                """,
                [d],
            ).fetchone()
        return row is not None

    async def get_instrument_spec(
        self, symbol: str, as_of: datetime | date | None = None
    ) -> InstrumentSpec:
        return get_instrument_spec(symbol, as_of)

    async def get_expiries(
        self, symbol: str, as_of: datetime | None = None, count: int = 8
    ) -> list[ExpiryInfo]:
        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        today = now_ist.date()
        part_path = self._partition_path(symbol, today)
        cal_expiries = calendar_get_expiries(symbol, now_ist, count=count)
        if not part_path.exists():
            return cal_expiries

        p_sql = str(part_path).replace("'", "''")
        with duckdb.connect(":memory:") as con:
            rows = con.execute(
                f"""
                SELECT DISTINCT expiry
                FROM read_parquet('{p_sql}')
                WHERE CAST(timestamp_ist AS DATE) = ? AND expiry >= ?
                ORDER BY expiry ASC
                """,
                [today, today],
            ).fetchall()

        if not rows:
            return cal_expiries

        cal_by_date = {e.expiry_date: e for e in cal_expiries}
        merged: list[ExpiryInfo] = []
        seen: set[date] = set()
        for (exp_d,) in rows:
            seen.add(exp_d)
            if exp_d in cal_by_date:
                merged.append(cal_by_date[exp_d])
            else:
                spec = get_instrument_spec(symbol, exp_d)
                dte = max((exp_d - today).days, 0)
                merged.append(
                    ExpiryInfo(
                        expiry_date=exp_d,
                        label=f"{exp_d.strftime('%d %b %y')} (H)",
                        is_weekly=spec.has_weekly,
                        is_monthly=not spec.has_weekly,
                        dte=dte,
                        lot_size=spec.lot_size,
                    )
                )
        for e in cal_expiries:
            if e.expiry_date not in seen and len(merged) < count:
                merged.append(e)
        return sorted(merged, key=lambda e: e.expiry_date)[:count]

    async def get_option_chain(
        self, symbol: str, expiry: date | None = None, as_of: datetime | None = None
    ) -> tuple[MockChainData, list[ExpiryInfo]]:
        sym = symbol.upper()
        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        bar_date = now_ist.date()
        part_path = self._partition_path(sym, bar_date)
        if not part_path.exists():
            raise FileNotFoundError(f"No Parquet partition for {sym} on {bar_date.isoformat()}")

        expiries = await self.get_expiries(sym, as_of=now_ist)
        if not expiries:
            raise ValueError(f"No active expiries found for {sym} on {bar_date.isoformat()}")
        chosen_expiry = expiry or expiries[0].expiry_date

        # Clamp bar timestamp inside trading session [09:15, 15:29] for intra-session lookup
        session_open = datetime(bar_date.year, bar_date.month, bar_date.day, 9, 15, 0)
        session_last = datetime(bar_date.year, bar_date.month, bar_date.day, 15, 29, 0)
        bar_naive = now_ist.replace(second=0, microsecond=0, tzinfo=None)
        bar_naive = max(session_open, min(session_last, bar_naive))
        ff_start = max(session_open, bar_naive - timedelta(minutes=self.forward_fill_minutes))

        p_sql = str(part_path).replace("'", "''")
        with duckdb.connect(":memory:") as con:
            spot_row = con.execute(
                f"""
                SELECT spot_close, futures_close, timestamp_ist
                FROM read_parquet('{p_sql}')
                WHERE timestamp_ist >= ? AND timestamp_ist <= ?
                ORDER BY timestamp_ist DESC
                LIMIT 1
                """,
                [session_open, bar_naive],
            ).fetchone()

            if spot_row is None:
                raise FileNotFoundError(f"No Parquet bars for {sym} on {bar_date.isoformat()}")

            spot_val = float(spot_row[0])
            fut_val = float(spot_row[1])

            opt_rows = con.execute(
                f"""
                SELECT strike, option_type, close, oi, iv, timestamp_ist
                FROM read_parquet('{p_sql}')
                WHERE expiry = ?
                  AND timestamp_ist >= ?
                  AND timestamp_ist <= ?
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY strike, option_type
                    ORDER BY timestamp_ist DESC
                ) = 1
                ORDER BY strike ASC
                """,
                [chosen_expiry, ff_start, bar_naive],
            ).fetchall()

            if not opt_rows:
                # Sparse session fallback: use latest print in the same trading session up to bar_naive
                opt_rows = con.execute(
                    f"""
                    SELECT strike, option_type, close, oi, iv, timestamp_ist
                    FROM read_parquet('{p_sql}')
                    WHERE expiry = ?
                      AND timestamp_ist >= ?
                      AND timestamp_ist <= ?
                    QUALIFY ROW_NUMBER() OVER (
                        PARTITION BY strike, option_type
                        ORDER BY timestamp_ist DESC
                    ) = 1
                    ORDER BY strike ASC
                    """,
                    [chosen_expiry, session_open, bar_naive],
                ).fetchall()

        spec = get_instrument_spec(sym, chosen_expiry)
        t_years = time_to_expiry_years(now_ist, chosen_expiry)
        t_eff = max(t_years, 1.0 / (365.0 * 24.0))

        # Organize printed bars by strike
        ce_map: dict[float, tuple[float, int, float]] = {}
        pe_map: dict[float, tuple[float, int, float]] = {}
        strike_set: set[float] = set()
        for k_raw, opt_type, close_px, oi_val, iv_raw, _ts in opt_rows:
            k_f = float(k_raw)
            strike_set.add(k_f)
            tup = (float(close_px), int(oi_val), float(iv_raw))
            if opt_type == "CE":
                ce_map[k_f] = tup
            elif opt_type == "PE":
                pe_map[k_f] = tup

        if not strike_set:
            raise FileNotFoundError(
                f"No option bars in Parquet for {sym} expiry={chosen_expiry.isoformat()} at {bar_naive}"
            )

        strikes_sorted = sorted(strike_set)
        # Compute Synthetic Forward from strikes that have both CE and PE quotes
        both_k = [k for k in strikes_sorted if k in ce_map and k in pe_map]
        if both_k:
            fwd_price, syn_atm = compute_synthetic_forward(
                strikes=both_k,
                call_ltps=[ce_map[k][0] for k in both_k],
                put_ltps=[pe_map[k][0] for k in both_k],
                spot_fallback=fut_val,
                r=0.0,
                t_years=t_eff,
            )
        else:
            fwd_price = fut_val
            syn_atm = float(min(strikes_sorted, key=lambda k: abs(k - spot_val)))

        # Determine baseline ATM IV for missing-leg theoretical fallback
        atm_iv_candidates = [
            ce_map[k][2] for k in (syn_atm,) if k in ce_map and ce_map[k][2] > 0
        ] + [pe_map[k][2] for k in (syn_atm,) if k in pe_map and pe_map[k][2] > 0]
        atm_iv = float(np.mean(atm_iv_candidates)) if atm_iv_candidates else (DEFAULT_VIX / 100.0)
        vix_est = round(atm_iv * 100.0, 2)

        # Resolve LTP and IV for every strike (backfilling IV or missing single side via Black-76)
        strikes_arr = np.asarray(strikes_sorted, dtype=np.float64)
        fallback_ivs = svi_skew_iv(strikes_arr, fwd_price, atm_iv, t_eff)

        ce_ltps = np.empty(len(strikes_sorted), dtype=np.float64)
        pe_ltps = np.empty(len(strikes_sorted), dtype=np.float64)
        ce_ivs = np.empty(len(strikes_sorted), dtype=np.float64)
        pe_ivs = np.empty(len(strikes_sorted), dtype=np.float64)
        ce_ois = np.zeros(len(strikes_sorted), dtype=np.int64)
        pe_ois = np.zeros(len(strikes_sorted), dtype=np.int64)

        for i, k in enumerate(strikes_sorted):
            fb_iv = float(fallback_ivs[i])
            if k in ce_map:
                px, oi_v, iv_v = ce_map[k]
                if iv_v <= 0.0 and px > 0.0 and t_years > 0.0:
                    iv_v = implied_volatility_black76(px, fwd_price, k, t_eff, "CE", r=0.0)
                ce_ltps[i] = px
                ce_ivs[i] = iv_v if iv_v > 0.0 else fb_iv
                ce_ois[i] = oi_v
            else:
                g_fb = greeks_black76_scalar(fwd_price, k, t_years, fb_iv, "CE", r=0.0)
                ce_ltps[i] = round_to_tick(g_fb.price, spec.tick_size) if t_years > 0 else round(g_fb.price, 2)
                ce_ivs[i] = fb_iv

            if k in pe_map:
                px, oi_v, iv_v = pe_map[k]
                if iv_v <= 0.0 and px > 0.0 and t_years > 0.0:
                    iv_v = implied_volatility_black76(px, fwd_price, k, t_eff, "PE", r=0.0)
                pe_ltps[i] = px
                pe_ivs[i] = iv_v if iv_v > 0.0 else fb_iv
                pe_ois[i] = oi_v
            else:
                g_fb = greeks_black76_scalar(fwd_price, k, t_years, fb_iv, "PE", r=0.0)
                pe_ltps[i] = round_to_tick(g_fb.price, spec.tick_size) if t_years > 0 else round(g_fb.price, 2)
                pe_ivs[i] = fb_iv

        ce_g = greeks_black76_vectorized(fwd_price, strikes_arr, t_years, ce_ivs, True, r=0.0)
        pe_g = greeks_black76_vectorized(fwd_price, strikes_arr, t_years, pe_ivs, False, r=0.0)

        rows: list[MockOptionRow] = []
        for i, k in enumerate(strikes_sorted):
            ce_ltp = float(ce_ltps[i])
            pe_ltp = float(pe_ltps[i])
            ce_sp = max(spec.tick_size, round_to_tick(ce_ltp * 0.004, spec.tick_size))
            pe_sp = max(spec.tick_size, round_to_tick(pe_ltp * 0.004, spec.tick_size))
            rows.append(
                MockOptionRow(
                    strike=k,
                    ce_contract_id=build_option_contract_id(spec.exchange, sym, chosen_expiry, k, "CE"),
                    pe_contract_id=build_option_contract_id(spec.exchange, sym, chosen_expiry, k, "PE"),
                    ce_ltp=ce_ltp,
                    ce_bid=max(0.0, round(ce_ltp - ce_sp, 2)),
                    ce_ask=round(ce_ltp + ce_sp, 2),
                    ce_iv=round(float(ce_ivs[i]) * 100.0, 2),
                    ce_delta=round(float(ce_g["delta"][i]), 4),
                    ce_gamma=round(float(ce_g["gamma"][i]), 6),
                    ce_theta=round(float(ce_g["theta"][i]), 2),
                    ce_vega=round(float(ce_g["vega"][i]), 2),
                    ce_oi=int(ce_ois[i]),
                    ce_oi_change=0,
                    pe_ltp=pe_ltp,
                    pe_bid=max(0.0, round(pe_ltp - pe_sp, 2)),
                    pe_ask=round(pe_ltp + pe_sp, 2),
                    pe_iv=round(float(pe_ivs[i]) * 100.0, 2),
                    pe_delta=round(float(pe_g["delta"][i]), 4),
                    pe_gamma=round(float(pe_g["gamma"][i]), 6),
                    pe_theta=round(float(pe_g["theta"][i]), 2),
                    pe_vega=round(float(pe_g["vega"][i]), 2),
                    pe_oi=int(pe_ois[i]),
                    pe_oi_change=0,
                )
            )

        return (
            MockChainData(
                symbol=sym,
                exchange=spec.exchange,
                expiry=chosen_expiry,
                as_of=now_ist,
                spot=round(spot_val, 2),
                futures_price=round(fut_val, 2),
                forward_price=round(fwd_price, 2),
                india_vix=vix_est,
                atm_strike=syn_atm,
                lot_size=spec.lot_size,
                strike_step=spec.strike_step,
                futures_contract_id=build_future_contract_id(spec.exchange, sym, chosen_expiry),
                rows=rows,
            ),
            expiries,
        )

    async def get_contract_quotes(
        self, contract_ids: list[str], as_of: datetime | None = None
    ) -> dict[str, LegQuoteSchema]:
        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        grouped: dict[tuple[str, date], list[tuple[str, str, float | None]]] = defaultdict(list)
        for cid in contract_ids:
            parsed = parse_contract_id(cid)
            if parsed.kind == "SPOT" or parsed.expiry is None:
                continue
            grouped[(parsed.symbol, parsed.expiry)].append((cid, parsed.kind, parsed.strike))

        quotes: dict[str, LegQuoteSchema] = {}
        for (sym, exp_date), items in grouped.items():
            try:
                chain, _ = await self.get_option_chain(sym, expiry=exp_date, as_of=now_ist)
            except FileNotFoundError:
                # If far-expiry (e.g., Calendar far leg) doesn't have its own bars at this minute,
                # derive spot/VIX from primary chain and price theoretically via Black-76
                chain, _ = await self.get_option_chain(sym, expiry=None, as_of=now_ist)

            by_strike = {r.strike: r for r in chain.rows}
            spec = get_instrument_spec(sym, exp_date)
            t_years = time_to_expiry_years(now_ist, exp_date)
            t_eff = max(t_years, 1.0 / (365.0 * 24.0))
            fwd_for_exp = (
                chain.forward_price
                if chain.expiry == exp_date
                else round(chain.spot * math.exp(0.065 * t_eff), 2)
            )

            for cid, kind, strike in items:
                if kind == "FUT":
                    fut_px = chain.futures_price if chain.expiry == exp_date else fwd_for_exp
                    sp = max(spec.tick_size, round_to_tick(fut_px * 0.0002, spec.tick_size))
                    quotes[cid] = LegQuoteSchema(
                        contract_id=cid,
                        expiry=exp_date,
                        strike=None,
                        option_type="FUT",
                        ltp=fut_px,
                        bid=round(fut_px - sp, 2),
                        ask=round(fut_px + sp, 2),
                        iv=0.0,
                        delta=1.0,
                        gamma=0.0,
                        theta=0.0,
                        vega=0.0,
                        forward_price=fwd_for_exp,
                        updated_at=now_ist,
                    )
                    continue

                assert strike is not None
                row = by_strike.get(float(strike)) if chain.expiry == exp_date else None
                if row is not None:
                    is_ce = kind == "CE"
                    quotes[cid] = LegQuoteSchema(
                        contract_id=cid,
                        expiry=exp_date,
                        strike=row.strike,
                        option_type="CE" if is_ce else "PE",
                        ltp=row.ce_ltp if is_ce else row.pe_ltp,
                        bid=row.ce_bid if is_ce else row.pe_bid,
                        ask=row.ce_ask if is_ce else row.pe_ask,
                        iv=row.ce_iv if is_ce else row.pe_iv,
                        delta=row.ce_delta if is_ce else row.pe_delta,
                        gamma=row.ce_gamma if is_ce else row.pe_gamma,
                        theta=row.ce_theta if is_ce else row.pe_theta,
                        vega=row.ce_vega if is_ce else row.pe_vega,
                        forward_price=chain.forward_price,
                        updated_at=now_ist,
                    )
                else:
                    # Black-76 theoretical fallback for illiquid/missing print or non-printed far expiry
                    atm_iv = max(chain.india_vix / 100.0, 0.08)
                    iv_val = float(
                        svi_skew_iv(
                            np.array([strike], dtype=np.float64),
                            fwd_for_exp,
                            atm_iv,
                            t_eff,
                        )[0]
                    )
                    g = greeks_black76_scalar(
                        forward=fwd_for_exp,
                        strike=strike,
                        t_years=t_years,
                        sigma=iv_val,
                        option_type="CE" if kind == "CE" else "PE",
                        r=0.0,
                    )
                    ltp = (
                        round_to_tick(g.price, spec.tick_size)
                        if t_years > 0
                        else round(g.price, 2)
                    )
                    sp = max(spec.tick_size, round_to_tick(ltp * 0.004, spec.tick_size))
                    quotes[cid] = LegQuoteSchema(
                        contract_id=cid,
                        expiry=exp_date,
                        strike=strike,
                        option_type="CE" if kind == "CE" else "PE",
                        ltp=ltp,
                        bid=max(0.0, round(ltp - sp, 2)),
                        ask=round(ltp + sp, 2),
                        iv=round(iv_val * 100.0, 2),
                        delta=round(g.delta, 4),
                        gamma=round(g.gamma, 6),
                        theta=round(g.theta, 2),
                        vega=round(g.vega, 2),
                        forward_price=fwd_for_exp,
                        updated_at=now_ist,
                    )
        return quotes

    async def build_tick_frame(
        self,
        symbol: IndexSymbol,
        chain_expiry: date | None,
        active_contracts: list[str],
        as_of: datetime | None = None,
    ) -> WsTickFrameSchema:
        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        chain, _ = await self.get_option_chain(symbol, expiry=chain_expiry, as_of=now_ist)
        leg_quotes = (
            await self.get_contract_quotes(active_contracts, as_of=now_ist)
            if active_contracts
            else {}
        )
        return WsTickFrameSchema(
            type="tick",
            symbol=symbol,
            chain_expiry=chain.expiry,
            as_of=chain.as_of,
            spot=chain.spot,
            futures_price=chain.futures_price,
            forward_price=chain.forward_price,
            india_vix=chain.india_vix,
            atm_strike=chain.atm_strike,
            chain_deltas=[
                OptionChainRowSchema.model_validate(r, from_attributes=True)
                for r in chain.rows
            ],
            leg_quotes=leg_quotes,
        )
