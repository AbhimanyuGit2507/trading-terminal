import { describe, expect, it } from "vitest";
import type { OptionChainSnapshot } from "@/lib/api/types";
import { buildPresetLegs } from "@/lib/presets";
import { useMarketStore } from "@/stores/marketStore";
import { useStrategyStore } from "@/stores/strategyStore";

function makeMockChain(expiry: string, basePrice = 150): OptionChainSnapshot {
  const strikes = [24150, 24200, 24250, 24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650];
  return {
    symbol: "NIFTY",
    exchange: "NSE_FNO",
    expiry,
    as_of: "2026-11-25T10:00:00+05:30",
    spot: 24350,
    futures_price: 24372,
    forward_price: 24372,
    india_vix: 13.85,
    atm_strike: 24350,
    lot_size: 65,
    strike_step: 50,
    futures_contract_id: `NSE_FNO:NIFTY:${expiry}:FUT`,
    expiries: [
      {
        expiry_date: "2026-12-01",
        label: "01 Dec 26 (W)",
        is_weekly: true,
        is_monthly: false,
        dte: 6,
        lot_size: 65,
      },
      {
        expiry_date: "2026-12-29",
        label: "29 Dec 26 (M)",
        is_weekly: false,
        is_monthly: true,
        dte: 34,
        lot_size: 65,
      },
    ],
    rows: strikes.map((k) => ({
      strike: k,
      ce_contract_id: `NSE_FNO:NIFTY:${expiry}:${k}:CE`,
      pe_contract_id: `NSE_FNO:NIFTY:${expiry}:${k}:PE`,
      ce_ltp: basePrice,
      ce_bid: basePrice - 0.5,
      ce_ask: basePrice + 0.5,
      ce_iv: 14.2,
      ce_delta: 0.5,
      ce_gamma: 0.0005,
      ce_theta: -12,
      ce_vega: 14,
      ce_oi: 1500000,
      ce_oi_change: 25000,
      pe_ltp: basePrice - 10,
      pe_bid: basePrice - 10.5,
      pe_ask: basePrice - 9.5,
      pe_iv: 14.8,
      pe_delta: -0.5,
      pe_gamma: 0.0005,
      pe_theta: -11,
      pe_vega: 14,
      pe_oi: 1400000,
      pe_oi_change: 18000,
    })),
  };
}

describe("Presets and Multi-Expiry Zustand Store", () => {
  it("builds Short Straddle, Iron Condor, and multi-expiry Calendar Spread legs", () => {
    const near = makeMockChain("2026-12-01", 150);
    const far = makeMockChain("2026-12-29", 390);

    const straddle = buildPresetLegs("short_straddle", near, null, 2);
    expect(straddle).toHaveLength(2);
    expect(straddle[0].strike).toBe(24350);
    expect(straddle[0].side).toBe("SELL");
    expect(straddle[0].lots).toBe(2);

    const condor = buildPresetLegs("iron_condor", near, null, 1);
    expect(condor).toHaveLength(4);
    expect(condor.filter((l) => l.side === "SELL")).toHaveLength(2);
    expect(condor.filter((l) => l.side === "BUY")).toHaveLength(2);

    const calendar = buildPresetLegs("calendar_spread", near, far, 1);
    expect(calendar).toHaveLength(2);
    expect(calendar[0].expiry).toBe("2026-12-01");
    expect(calendar[0].side).toBe("SELL");
    expect(calendar[1].expiry).toBe("2026-12-29");
    expect(calendar[1].side).toBe("BUY");
    expect(calendar[1].entry_price).toBe(390);
  });

  it("preserves activeLegQuotes across non-viewed expiries on WS tick frames", () => {
    const market = useMarketStore.getState();
    const near = makeMockChain("2026-12-01", 150);
    const farCid = "NSE_FNO:NIFTY:2026-12-29:24350:CE";

    market.setSnapshot(near);
    market.mergeActiveLegQuotes({
      [farCid]: {
        contract_id: farCid,
        expiry: "2026-12-29",
        strike: 24350,
        option_type: "CE",
        ltp: 390,
        bid: 389,
        ask: 391,
        iv: 14.5,
        delta: 0.52,
        gamma: 0.0003,
        theta: -6,
        vega: 28,
        forward_price: 24490,
        updated_at: "2026-11-25T10:00:00+05:30",
      },
    });

    market.applyTickFrame({
      type: "tick",
      symbol: "NIFTY",
      chain_expiry: "2026-12-01",
      as_of: "2026-11-25T10:01:00+05:30",
      spot: 24365,
      futures_price: 24387,
      forward_price: 24387,
      india_vix: 13.9,
      atm_strike: 24350,
      chain_deltas: near.rows,
      leg_quotes: {
        [farCid]: {
          contract_id: farCid,
          expiry: "2026-12-29",
          strike: 24350,
          option_type: "CE",
          ltp: 398.5,
          bid: 398,
          ask: 399,
          iv: 14.6,
          delta: 0.53,
          gamma: 0.0003,
          theta: -6,
          vega: 28,
          forward_price: 24505,
          updated_at: "2026-11-25T10:01:00+05:30",
        },
      },
      message: null,
    });

    const updated = useMarketStore.getState();
    expect(updated.spot).toBe(24365);
    expect(updated.activeLegQuotes[farCid].ltp).toBe(398.5);
  });

  it("supports flip, lot updates, and toggle in strategyStore", () => {
    const store = useStrategyStore.getState();
    store.clearStrategy();
    const near = makeMockChain("2026-12-01", 150);
    const legs = buildPresetLegs("short_straddle", near, null, 1);
    store.replaceWithLegs(legs, "Test Straddle");

    const id0 = useStrategyStore.getState().legs[0].leg_id;
    store.flipLegSide(id0);
    expect(useStrategyStore.getState().legs[0].side).toBe("BUY");

    store.updateLegLots(id0, 4);
    expect(useStrategyStore.getState().legs[0].lots).toBe(4);

    store.toggleLegEnabled(id0);
    expect(useStrategyStore.getState().legs[0].enabled).toBe(false);
  });
});
