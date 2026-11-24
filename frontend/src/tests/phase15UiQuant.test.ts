import { describe, expect, it } from "vitest";
import { formatPnl } from "@/lib/format";
import {
  buildPayoffTableRows,
  computeLegGreeksBreakdown,
  convertPnlByUnit,
  evaluatePayoff,
  inrToPoints,
  type QuantLeg,
} from "@/lib/quant";
import { getEffectiveLegs, useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";

const BASE_DT = "2026-11-18T10:00:00+05:30";
const EXPIRY = "2026-11-23";

function makeStraddleLegs(): QuantLeg[] {
  return [
    {
      leg_id: "c1",
      symbol: "NIFTY",
      expiry: EXPIRY,
      option_type: "CE",
      side: "SELL",
      lots: 1,
      lot_size: 65,
      entry_price: 150.0,
      entry_iv: 0.14,
      strike: 24350,
      forward_at_base: 24350,
      enabled: true,
      status: "OPEN",
      exchange: "NSE_FNO",
    },
    {
      leg_id: "p1",
      symbol: "NIFTY",
      expiry: EXPIRY,
      option_type: "PE",
      side: "SELL",
      lots: 1,
      lot_size: 65,
      entry_price: 140.0,
      entry_iv: 0.14,
      strike: 24350,
      forward_at_base: 24350,
      enabled: true,
      status: "OPEN",
      exchange: "NSE_FNO",
    },
  ];
}

describe("Phase 1.5 UI Parity: Multiplier, Points, Payoff Table, Leg Greeks & SD Bands", () => {
  it("keeps uiStore defaults aligned with StockMock parity (light theme, INR, graph tab, charges OFF)", () => {
    const ui = useUiStore.getState();
    expect(ui.theme).toBe("light");
    expect(ui.pnlUnit).toBe("INR");
    expect(ui.rightTab).toBe("graph");
    expect(ui.includeCharges).toBe(false);
    expect(ui.chartOverlays).toEqual({
      expiryPayoff: true,
      targetMtm: true,
      sdBands: true,
      oiOverlay: false,
    });
  });

  it("scales effective legs non-destructively via global lotMultiplier and restores base lots at 1x", () => {
    const store = useStrategyStore.getState();
    store.clearStrategy();
    const baseLegs = makeStraddleLegs().map((l) => ({
      ...l,
      contract_id: `NSE_FNO:NIFTY:${l.expiry}:${l.strike}:${l.option_type}`,
      exchange: "NSE_FNO" as const,
    }));
    store.replaceWithLegs(baseLegs, "Straddle");

    store.setLotMultiplier(3);
    const scaled = getEffectiveLegs(useStrategyStore.getState().legs, useStrategyStore.getState().lotMultiplier);
    expect(scaled.every((l) => l.lots === 3)).toBe(true);
    // Base legs remain untouched at 1 lot
    expect(useStrategyStore.getState().legs.every((l) => l.lots === 1)).toBe(true);

    // Clamp below 1
    store.setLotMultiplier(0);
    expect(useStrategyStore.getState().lotMultiplier).toBe(1);

    const eval3x = evaluatePayoff({
      spot: 24350,
      legs: getEffectiveLegs(baseLegs, 3).map((l) => ({
        ...l,
        strike: l.strike ?? null,
      })),
      baseDtIso: BASE_DT,
    });
    const eval1x = evaluatePayoff({
      spot: 24350,
      legs: makeStraddleLegs(),
      baseDtIso: BASE_DT,
    });
    expect(eval3x.max_profit).toBeCloseTo((eval1x.max_profit ?? 0) * 3, 2);
  });

  it("converts INR <-> Index Points accurately (150 + 140 = +290.00 pts)", () => {
    const lotSize = 65;
    const maxProfitInr = (150 + 140) * lotSize; // 18850 INR
    expect(inrToPoints(maxProfitInr, lotSize)).toBe(290);
    expect(convertPnlByUnit(maxProfitInr, "POINTS", lotSize)).toBe(290);
    expect(convertPnlByUnit(maxProfitInr, "INR", lotSize)).toBe(18850);
    expect(formatPnl(maxProfitInr, "POINTS", lotSize, { signed: true })).toBe("+290.00 pts");
    expect(formatPnl(maxProfitInr, "INR", lotSize, { signed: true, decimals: 0 })).toBe("+₹18,850");
  });

  it("generates Payoff Table rows from -5% to +5% with Current Spot & Breakeven highlights", () => {
    const legs = makeStraddleLegs();
    const evalRes = evaluatePayoff({
      spot: 24350,
      legs,
      baseDtIso: BASE_DT,
    });
    const rows = buildPayoffTableRows({
      spot: 24350,
      legs,
      baseDtIso: BASE_DT,
      breakevens: evalRes.breakevens,
    });

    // 21 percentage grid points + 2 exact breakeven rows (24060, 24640)
    expect(rows.length).toBeGreaterThanOrEqual(21);
    expect(rows[0].pctChange).toBeCloseTo(-5.0, 2);
    expect(rows[rows.length - 1].pctChange).toBeCloseTo(5.0, 2);

    const spotRow = rows.find((r) => r.isCurrentSpot);
    expect(spotRow).toBeDefined();
    expect(spotRow?.spot).toBe(24350);
    expect(spotRow?.expiryPnl).toBe(18850);

    const beRows = rows.filter((r) => r.isBreakeven);
    expect(beRows).toHaveLength(2);
    for (const be of beRows) {
      expect(Math.abs(be.expiryPnl)).toBeLessThanOrEqual(1);
    }
  });

  it("computes per-leg Greeks breakdown and exact ±1σ / ±2σ SD bands", () => {
    const legs = makeStraddleLegs();
    const breakdown = computeLegGreeksBreakdown({
      spot: 24350,
      targetSpot: 24350,
      legs,
      baseDtIso: BASE_DT,
      targetDtIso: BASE_DT,
      ivShiftPct: 0,
      lotMultiplier: 2,
    });

    expect(breakdown.rows).toHaveLength(2);
    expect(breakdown.rows[0].effectiveLots).toBe(2);
    expect(breakdown.rows[0].effectiveQty).toBe(130);
    // ATM Short Straddle has near-zero net delta and positive daily theta
    expect(Math.abs(breakdown.totals.delta)).toBeLessThan(10);
    expect(breakdown.totals.theta).toBeGreaterThan(0);

    const evalRes = evaluatePayoff({
      spot: 24350,
      legs,
      baseDtIso: BASE_DT,
    });
    const oneSdWidth = evalRes.sd_1_high - 24350;
    const twoSdWidth = evalRes.sd_2_high - 24350;
    expect(evalRes.sd_1_low).toBeCloseTo(24350 - oneSdWidth, 1);
    expect(twoSdWidth).toBeCloseTo(2 * oneSdWidth, 1);
    expect(evalRes.sd_2_low).toBeCloseTo(24350 - 2 * oneSdWidth, 1);
  });
});
