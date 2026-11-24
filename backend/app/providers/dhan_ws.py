"""DhanHQ v2.5 Live Binary WebSocket Provider + Graceful MockFallback Router."""

from __future__ import annotations

import asyncio
import json
import math
import struct
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import websockets

from app.core.calendar import (
    IST,
    ExpiryInfo,
    InstrumentSpec,
    get_instrument_spec,
    round_to_tick,
    time_to_expiry_years,
    to_ist,
)
from app.core.contracts import (
    build_future_contract_id,
    build_option_contract_id,
    build_spot_contract_id,
    parse_contract_id,
)
from app.providers.mock_static import MockStaticProvider
from app.quant.black76 import (
    compute_synthetic_forward,
    greeks_black76_scalar,
    greeks_black76_vectorized,
    implied_volatility_black76,
)
from app.quant.mock_chain import DEFAULT_VIX, MockChainData, MockOptionRow
from app.schemas.domain import (
    FeedStatus,
    IndexSymbol,
    LegQuoteSchema,
    OptionChainRowSchema,
    WsTickFrameSchema,
)
from app.services.dhan_auth import DhanTokenManager
from app.services.dhan_scrip_master import BINARY_SEG_CODE_TO_NAME, DhanScripMaster

DHAN_FEED_WS_BASE = "wss://api-feed.dhan.co"

# Dhan binary packet formats (little-endian)
_HEADER_FMT = "<BHBI"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 8 bytes
_TICKER_BODY_FMT = "<fI"  # ltp, ltt
_OI_BODY_FMT = "<I"  # oi
_QUOTE_BODY_FMT = "<fHIfIIIffff"  # 42 bytes => 50 bytes total with 8-byte header
_FULL_BODY_FMT = "<fHIfIIIffff"  # base 50 bytes (+ optional I OI and 5x20 market depth)


@dataclass(frozen=True, slots=True)
class DecodedDhanPacket:
    feed_code: int
    message_length: int
    exchange_segment: str
    security_id: str
    ltp: float | None = None
    ltq: int | None = None
    ltt: int | None = None
    avg_price: float | None = None
    volume: int | None = None
    total_sell_qty: int | None = None
    total_buy_qty: int | None = None
    open: float | None = None
    close: float | None = None
    high: float | None = None
    low: float | None = None
    oi: int | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    disconnect_reason: int | None = None


def decode_dhan_binary_packet(packet: bytes) -> DecodedDhanPacket | None:
    """Decode DhanHQ v2 little-endian binary market feed packets."""
    if len(packet) < _HEADER_SIZE:
        return None

    feed_code, msg_len, seg_code, sec_id = struct.unpack(_HEADER_FMT, packet[:_HEADER_SIZE])
    seg_name = BINARY_SEG_CODE_TO_NAME.get(seg_code, str(seg_code))
    sec_str = str(sec_id)
    body = packet[_HEADER_SIZE:]

    if feed_code == 50 and len(body) >= 2:
        (reason,) = struct.unpack("<H", body[:2])
        return DecodedDhanPacket(
            feed_code=feed_code,
            message_length=msg_len,
            exchange_segment=seg_name,
            security_id=sec_str,
            disconnect_reason=reason,
        )

    if feed_code == 2 and len(body) >= struct.calcsize(_TICKER_BODY_FMT):
        ltp, ltt = struct.unpack(_TICKER_BODY_FMT, body[: struct.calcsize(_TICKER_BODY_FMT)])
        return DecodedDhanPacket(
            feed_code=feed_code,
            message_length=msg_len,
            exchange_segment=seg_name,
            security_id=sec_str,
            ltp=round(float(ltp), 2),
            ltt=int(ltt),
        )

    if feed_code == 5 and len(body) >= struct.calcsize(_OI_BODY_FMT):
        (oi_val,) = struct.unpack(_OI_BODY_FMT, body[: struct.calcsize(_OI_BODY_FMT)])
        return DecodedDhanPacket(
            feed_code=feed_code,
            message_length=msg_len,
            exchange_segment=seg_name,
            security_id=sec_str,
            oi=int(oi_val),
        )

    quote_sz = struct.calcsize(_QUOTE_BODY_FMT)
    if feed_code in (4, 8) and len(body) >= quote_sz:
        (
            ltp,
            ltq,
            ltt,
            avg_px,
            vol,
            tot_sell,
            tot_buy,
            open_px,
            close_px,
            high_px,
            low_px,
        ) = struct.unpack(_QUOTE_BODY_FMT, body[:quote_sz])

        oi_val: int | None = None
        best_bid: float | None = None
        best_ask: float | None = None
        rem = body[quote_sz:]
        if feed_code == 8 and len(rem) >= 4:
            (oi_val,) = struct.unpack("<I", rem[:4])
            depth_rem = rem[4:]
            # First depth level (20 bytes: int32 buy_qty, int32 sell_qty, int16 buy_orders, int16 sell_orders, float32 bid, float32 ask)
            if len(depth_rem) >= 20:
                _, _, _, _, bid_f, ask_f = struct.unpack("<IIHHff", depth_rem[:20])
                if bid_f > 0:
                    best_bid = round(float(bid_f), 2)
                if ask_f > 0:
                    best_ask = round(float(ask_f), 2)

        return DecodedDhanPacket(
            feed_code=feed_code,
            message_length=msg_len,
            exchange_segment=seg_name,
            security_id=sec_str,
            ltp=round(float(ltp), 2),
            ltq=int(ltq),
            ltt=int(ltt),
            avg_price=round(float(avg_px), 2),
            volume=int(vol),
            total_sell_qty=int(tot_sell),
            total_buy_qty=int(tot_buy),
            open=round(float(open_px), 2),
            close=round(float(close_px), 2),
            high=round(float(high_px), 2),
            low=round(float(low_px), 2),
            oi=oi_val,
            best_bid=best_bid,
            best_ask=best_ask,
        )

    return None


@dataclass
class LiveQuoteCacheEntry:
    ltp: float
    bid: float
    ask: float
    oi: int = 0
    volume: int = 0
    updated_at: datetime | None = None


class DhanLiveMarketProvider:
    """MarketDataProvider backed by DhanHQ v2.5 WS with graceful MockStaticProvider fallback."""

    def __init__(
        self,
        token_manager: DhanTokenManager,
        scrip_master: DhanScripMaster,
        mock_fallback: MockStaticProvider,
    ) -> None:
        self.token_manager = token_manager
        self.scrip_master = scrip_master
        self.mock_fallback = mock_fallback

        self.ticks: dict[str, LiveQuoteCacheEntry] = {}
        self._subscribed_keys: set[tuple[str, str]] = set()
        self._desired_contracts: set[str] = set()
        self._ws: Any = None
        self._ws_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._connected_ws = False

        self.token_manager.register_reload_listener(self.hot_reload)

    @property
    def feed_status(self) -> FeedStatus:
        return self.token_manager.get_status().mode

    async def hot_reload(
        self,
        client_id: str | None,
        access_token: str | None,
        active: bool,
    ) -> None:
        """Stop any existing Dhan WS loop and reconnect cleanly if credentials are active."""
        await self.stop()
        if active and client_id and access_token:
            await self.scrip_master.ensure_loaded()
            self._stop_event.clear()
            self._ws_task = asyncio.create_task(self._ws_loop(client_id, access_token))

    async def stop(self) -> None:
        self._stop_event.set()
        self._connected_ws = False
        self._subscribed_keys.clear()
        if self._ws is not None:
            with suppress(websockets.WebSocketException, OSError):
                await self._ws.close()
            self._ws = None
        if self._ws_task is not None:
            self._ws_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None

    def compute_subscription_diff(
        self, desired_contracts: set[str]
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Compute Dhan RequestCode 21 (sub) and 22 (unsub) instrument diffs."""
        desired_keys: set[tuple[str, str]] = set()
        for cid in desired_contracts:
            mapped = self.scrip_master.to_dhan(cid)
            if mapped is not None:
                desired_keys.add(mapped)

        to_add = [
            {"ExchangeSegment": seg, "SecurityId": sec_id}
            for seg, sec_id in sorted(desired_keys - self._subscribed_keys)
        ]
        to_remove = [
            {"ExchangeSegment": seg, "SecurityId": sec_id}
            for seg, sec_id in sorted(self._subscribed_keys - desired_keys)
        ]
        return to_add, to_remove

    async def _send_subscription_diff(self, ws: Any, desired_contracts: set[str]) -> None:
        to_add, to_remove = self.compute_subscription_diff(desired_contracts)
        for batch_start in range(0, len(to_remove), 100):
            chunk = to_remove[batch_start : batch_start + 100]
            await ws.send(
                json.dumps(
                    {
                        "RequestCode": 22,
                        "InstrumentCount": len(chunk),
                        "InstrumentList": chunk,
                    }
                )
            )
            for item in chunk:
                self._subscribed_keys.discard((item["ExchangeSegment"], item["SecurityId"]))

        for batch_start in range(0, len(to_add), 100):
            chunk = to_add[batch_start : batch_start + 100]
            await ws.send(
                json.dumps(
                    {
                        "RequestCode": 21,
                        "InstrumentCount": len(chunk),
                        "InstrumentList": chunk,
                    }
                )
            )
            for item in chunk:
                self._subscribed_keys.add((item["ExchangeSegment"], item["SecurityId"]))

    def process_binary_message(self, payload: bytes) -> None:
        pkt = decode_dhan_binary_packet(payload)
        if pkt is None:
            return
        if pkt.feed_code == 50:
            # Auth/session disconnect
            if pkt.disconnect_reason in (805, 806, 807, 808, 809):
                self.token_manager.mark_token_expired(
                    f"Dhan WS disconnected (code {pkt.disconnect_reason})."
                )
            return

        cid = self.scrip_master.to_contract(pkt.exchange_segment, pkt.security_id)
        if cid is None:
            return

        prev = self.ticks.get(cid)
        ltp = pkt.ltp if pkt.ltp is not None and pkt.ltp > 0 else (prev.ltp if prev else 0.0)
        bid = pkt.best_bid if pkt.best_bid is not None else (prev.bid if prev else ltp)
        ask = pkt.best_ask if pkt.best_ask is not None else (prev.ask if prev else ltp)
        oi = pkt.oi if pkt.oi is not None else (prev.oi if prev else 0)
        vol = pkt.volume if pkt.volume is not None else (prev.volume if prev else 0)
        self.ticks[cid] = LiveQuoteCacheEntry(
            ltp=ltp,
            bid=bid,
            ask=ask,
            oi=oi,
            volume=vol,
            updated_at=datetime.now(IST),
        )

    async def _ws_loop(self, client_id: str, access_token: str) -> None:
        backoff = 1.0
        ws_url = f"{DHAN_FEED_WS_BASE}?version=2&token={access_token}&clientId={client_id}&authType=2"
        while not self._stop_event.is_set() and self.token_manager.has_live_credentials():
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    self._connected_ws = True
                    backoff = 1.0
                    await self._send_subscription_diff(ws, self._desired_contracts)
                    async for message in ws:
                        if isinstance(message, bytes):
                            self.process_binary_message(message)
                        if self._stop_event.is_set():
                            break
            except asyncio.CancelledError:
                raise
            except (websockets.WebSocketException, OSError, TimeoutError):
                self._connected_ws = False
                self._ws = None
                self._subscribed_keys.clear()
                if self._stop_event.is_set():
                    break
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2.0)

    def _update_desired_subscriptions(
        self, symbol: str, expiry: date, strikes: list[float], active_contracts: list[str]
    ) -> None:
        spec = get_instrument_spec(symbol, expiry)
        desired: set[str] = {
            build_spot_contract_id(symbol),
            "IDX_I:INDIAVIX:SPOT",
            build_future_contract_id(spec.exchange, symbol, expiry),
        }
        for k in strikes:
            desired.add(build_option_contract_id(spec.exchange, symbol, expiry, k, "CE"))
            desired.add(build_option_contract_id(spec.exchange, symbol, expiry, k, "PE"))
        desired.update(active_contracts)

        changed = desired != self._desired_contracts
        self._desired_contracts = desired
        if changed and self._ws is not None and self._connected_ws:
            asyncio.create_task(self._send_subscription_diff(self._ws, desired))

    async def get_instrument_spec(
        self, symbol: str, as_of: datetime | date | None = None
    ) -> InstrumentSpec:
        return get_instrument_spec(symbol, as_of)

    async def get_expiries(
        self, symbol: str, as_of: datetime | None = None, count: int = 8
    ) -> list[ExpiryInfo]:
        return await self.mock_fallback.get_expiries(symbol, as_of=as_of, count=count)

    async def get_option_chain(
        self, symbol: str, expiry: date | None = None, as_of: datetime | None = None
    ) -> tuple[MockChainData, list[ExpiryInfo]]:
        sym = symbol.upper()
        if not self.token_manager.has_live_credentials():
            return await self.mock_fallback.get_option_chain(sym, expiry=expiry, as_of=as_of)

        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        expiries = await self.get_expiries(sym, as_of=now_ist)
        chosen_expiry = expiry or expiries[0].expiry_date
        spec = get_instrument_spec(sym, chosen_expiry)

        spot_cid = build_spot_contract_id(sym)
        fut_cid = build_future_contract_id(spec.exchange, sym, chosen_expiry)
        vix_cid = "IDX_I:INDIAVIX:SPOT"

        spot_tick = self.ticks.get(spot_cid)
        if spot_tick is None or spot_tick.ltp <= 0:
            # Before first live spot packet arrives (or outside market hours), overlay mock baseline
            # and keep subscription armed
            base_chain, base_expiries = await self.mock_fallback.get_option_chain(
                sym, expiry=chosen_expiry, as_of=now_ist
            )
            self._update_desired_subscriptions(
                sym, chosen_expiry, [r.strike for r in base_chain.rows], []
            )
            return base_chain, base_expiries

        spot_val = spot_tick.ltp
        vix_val = self.ticks[vix_cid].ltp if vix_cid in self.ticks and self.ticks[vix_cid].ltp > 0 else DEFAULT_VIX
        t_years = max(time_to_expiry_years(now_ist, chosen_expiry), 1.0 / (365.0 * 24.0))
        fut_tick = self.ticks.get(fut_cid)
        fut_val = (
            fut_tick.ltp
            if fut_tick is not None and fut_tick.ltp > 0
            else round_to_tick(spot_val * math.exp(0.065 * t_years), spec.tick_size)
        )

        atm_strike = float(round(spot_val / spec.strike_step) * spec.strike_step)
        strikes = [atm_strike + i * spec.strike_step for i in range(-20, 21)]
        self._update_desired_subscriptions(sym, chosen_expiry, strikes, [])

        # Overlay live WS option ticks onto Black-76 theoretical baseline
        ce_ltps = np.zeros(len(strikes), dtype=np.float64)
        pe_ltps = np.zeros(len(strikes), dtype=np.float64)
        ce_bids = np.zeros(len(strikes), dtype=np.float64)
        ce_asks = np.zeros(len(strikes), dtype=np.float64)
        pe_bids = np.zeros(len(strikes), dtype=np.float64)
        pe_asks = np.zeros(len(strikes), dtype=np.float64)
        ce_ois = np.zeros(len(strikes), dtype=np.int64)
        pe_ois = np.zeros(len(strikes), dtype=np.int64)

        default_iv = max(vix_val / 100.0, 0.08)
        for i, k in enumerate(strikes):
            ce_cid = build_option_contract_id(spec.exchange, sym, chosen_expiry, k, "CE")
            pe_cid = build_option_contract_id(spec.exchange, sym, chosen_expiry, k, "PE")
            ce_t = self.ticks.get(ce_cid)
            pe_t = self.ticks.get(pe_cid)

            if ce_t and ce_t.ltp > 0:
                ce_ltps[i] = ce_t.ltp
                ce_bids[i] = ce_t.bid
                ce_asks[i] = ce_t.ask
                ce_ois[i] = ce_t.oi
            else:
                g = greeks_black76_scalar(fut_val, k, t_years, default_iv, "CE", r=0.0)
                px = round_to_tick(g.price, spec.tick_size)
                ce_ltps[i] = px
                ce_bids[i] = px
                ce_asks[i] = px

            if pe_t and pe_t.ltp > 0:
                pe_ltps[i] = pe_t.ltp
                pe_bids[i] = pe_t.bid
                pe_asks[i] = pe_t.ask
                pe_ois[i] = pe_t.oi
            else:
                g = greeks_black76_scalar(fut_val, k, t_years, default_iv, "PE", r=0.0)
                px = round_to_tick(g.price, spec.tick_size)
                pe_ltps[i] = px
                pe_bids[i] = px
                pe_asks[i] = px

        strikes_arr = np.asarray(strikes, dtype=np.float64)
        fwd_price, syn_atm = compute_synthetic_forward(
            strikes_arr, ce_ltps, pe_ltps, fut_val, r=0.0, t_years=t_years
        )

        ce_ivs = np.array(
            [
                implied_volatility_black76(float(ce_ltps[i]), fwd_price, float(k), t_years, "CE", r=0.0)
                for i, k in enumerate(strikes)
            ],
            dtype=np.float64,
        )
        pe_ivs = np.array(
            [
                implied_volatility_black76(float(pe_ltps[i]), fwd_price, float(k), t_years, "PE", r=0.0)
                for i, k in enumerate(strikes)
            ],
            dtype=np.float64,
        )

        ce_g = greeks_black76_vectorized(fwd_price, strikes_arr, t_years, ce_ivs, True, r=0.0)
        pe_g = greeks_black76_vectorized(fwd_price, strikes_arr, t_years, pe_ivs, False, r=0.0)

        rows: list[MockOptionRow] = []
        for i, k in enumerate(strikes):
            rows.append(
                MockOptionRow(
                    strike=float(k),
                    ce_contract_id=build_option_contract_id(spec.exchange, sym, chosen_expiry, k, "CE"),
                    pe_contract_id=build_option_contract_id(spec.exchange, sym, chosen_expiry, k, "PE"),
                    ce_ltp=float(ce_ltps[i]),
                    ce_bid=float(ce_bids[i]),
                    ce_ask=float(ce_asks[i]),
                    ce_iv=round(float(ce_ivs[i]) * 100.0, 2),
                    ce_delta=round(float(ce_g["delta"][i]), 4),
                    ce_gamma=round(float(ce_g["gamma"][i]), 6),
                    ce_theta=round(float(ce_g["theta"][i]), 2),
                    ce_vega=round(float(ce_g["vega"][i]), 2),
                    ce_oi=int(ce_ois[i]),
                    ce_oi_change=0,
                    pe_ltp=float(pe_ltps[i]),
                    pe_bid=float(pe_bids[i]),
                    pe_ask=float(pe_asks[i]),
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
                india_vix=round(vix_val, 2),
                atm_strike=syn_atm,
                lot_size=spec.lot_size,
                strike_step=spec.strike_step,
                futures_contract_id=fut_cid,
                rows=rows,
            ),
            expiries,
        )

    async def get_contract_quotes(
        self, contract_ids: list[str], as_of: datetime | None = None
    ) -> dict[str, LegQuoteSchema]:
        if not self.token_manager.has_live_credentials():
            return await self.mock_fallback.get_contract_quotes(contract_ids, as_of=as_of)

        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        quotes = await self.mock_fallback.get_contract_quotes(contract_ids, as_of=now_ist)
        # Overlay live Dhan WS ticks wherever present
        for cid in contract_ids:
            tick = self.ticks.get(cid)
            if tick is None or tick.ltp <= 0:
                continue
            parsed = parse_contract_id(cid)
            if parsed.expiry is None or parsed.kind == "SPOT":
                continue
            base_q = quotes.get(cid)
            if base_q is None:
                continue
            if parsed.kind == "FUT":
                quotes[cid] = base_q.model_copy(
                    update={"ltp": tick.ltp, "bid": tick.bid, "ask": tick.ask, "updated_at": now_ist}
                )
            else:
                t_years = max(time_to_expiry_years(now_ist, parsed.expiry), 1.0 / (365.0 * 24.0))
                fwd = base_q.forward_price
                iv_dec = implied_volatility_black76(
                    tick.ltp, fwd, float(parsed.strike or fwd), t_years, parsed.kind, r=0.0
                )
                g = greeks_black76_scalar(
                    fwd, float(parsed.strike or fwd), t_years, iv_dec, parsed.kind, r=0.0
                )
                quotes[cid] = base_q.model_copy(
                    update={
                        "ltp": tick.ltp,
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "iv": round(iv_dec * 100.0, 2),
                        "delta": round(g.delta, 4),
                        "gamma": round(g.gamma, 6),
                        "theta": round(g.theta, 2),
                        "vega": round(g.vega, 2),
                        "updated_at": now_ist,
                    }
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
        if self.token_manager.has_live_credentials():
            self._update_desired_subscriptions(
                symbol, chain.expiry, [r.strike for r in chain.rows], active_contracts
            )
        leg_quotes = (
            await self.get_contract_quotes(active_contracts, as_of=now_ist)
            if active_contracts
            else {}
        )
        return WsTickFrameSchema(
            type="tick",
            feed_status=self.feed_status,
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
