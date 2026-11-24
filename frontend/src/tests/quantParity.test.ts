import { describe, expect, it } from "vitest";
import golden from "@shared/golden/quant_vectors.json";
import { greeksBlack76Scalar } from "@/lib/quant/black76";
import { evaluatePayoff, splitSeriesForECharts } from "@/lib/quant/payoff";
import type { QuantLeg } from "@/lib/quant/types";

describe("Python <-> TypeScript Quant Parity (< 1e-5)", () => {
  it("matches Black-76 price and all Greeks within 1e-5", () => {
    for (const vec of golden.black76) {
      const res = greeksBlack76Scalar(
        vec.forward,
        vec.strike,
        vec.t_years,
        vec.sigma,
        vec.option_type as "CE" | "PE",
        0.0
      );
      expect(Math.abs(res.price - vec.expected.price)).toBeLessThan(1e-5);
      expect(Math.abs(res.delta - vec.expected.delta)).toBeLessThan(1e-5);
      expect(Math.abs(res.gamma - vec.expected.gamma)).toBeLessThan(1e-5);
      expect(Math.abs(res.theta - vec.expected.theta)).toBeLessThan(1e-5);
      expect(Math.abs(res.vega - vec.expected.vega)).toBeLessThan(1e-5);
    }
  });

  it("matches multi-expiry Payoff, Breakevens, POP, Charges & Net Greeks within 1e-5", () => {
    for (const sc of golden.payoff) {
      const res = evaluatePayoff({
        spot: sc.spot,
        legs: sc.legs as QuantLeg[],
        baseDtIso: sc.base_dt,
        targetSpot: sc.target_spot,
        targetDtIso: sc.target_dt,
        ivShiftPct: sc.iv_shift_pct,
        realizedPnl: sc.realized_pnl,
        includeCharges: sc.include_charges,
        atmIv: sc.atm_iv,
        r: 0.0,
      });

      expect(res.max_profit_unlimited).toBe(sc.expected.max_profit_unlimited);
      expect(res.max_loss_unlimited).toBe(sc.expected.max_loss_unlimited);

      if (sc.expected.max_profit === null) {
        expect(res.max_profit).toBeNull();
      } else {
        expect(Math.abs((res.max_profit ?? 0) - sc.expected.max_profit)).toBeLessThanOrEqual(0.01);
      }

      if (sc.expected.max_loss === null) {
        expect(res.max_loss).toBeNull();
      } else {
        expect(Math.abs((res.max_loss ?? 0) - sc.expected.max_loss)).toBeLessThanOrEqual(0.01);
      }

      expect(res.breakevens.length).toBe(sc.expected.breakevens.length);
      for (let i = 0; i < res.breakevens.length; i++) {
        expect(Math.abs(res.breakevens[i] - sc.expected.breakevens[i])).toBeLessThanOrEqual(0.02);
      }

      expect(Math.abs(res.current_mtm_pnl - sc.expected.current_mtm_pnl)).toBeLessThanOrEqual(0.01);
      expect(Math.abs(res.estimated_charges - sc.expected.estimated_charges)).toBeLessThanOrEqual(0.01);
      expect(Math.abs(res.pop - sc.expected.pop)).toBeLessThanOrEqual(0.02);

      expect(Math.abs(res.net_greeks.delta - sc.expected.net_greeks.delta)).toBeLessThan(1e-2);
      expect(Math.abs(res.net_greeks.gamma - sc.expected.net_greeks.gamma)).toBeLessThan(1e-4);
      expect(Math.abs(res.net_greeks.theta - sc.expected.net_greeks.theta)).toBeLessThan(1e-2);
      expect(Math.abs(res.net_greeks.vega - sc.expected.net_greeks.vega)).toBeLessThan(1e-2);

      // Verify sampled curve points match
      for (const sp of sc.expected.sample_points) {
        const match = res.points.find((p) => Math.abs(p.spot - sp.spot) < 0.02);
        expect(match).toBeDefined();
        if (match) {
          expect(Math.abs(match.expiry_pnl - sp.expiry_pnl)).toBeLessThanOrEqual(0.02);
          expect(Math.abs(match.target_pnl - sp.target_pnl)).toBeLessThanOrEqual(0.02);
        }
      }
    }
  });

  it("splits ECharts positive/negative series with exact zero-crossing vertices", () => {
    const sample = [
      { spot: 24000, expiry_pnl: -1000, target_pnl: -800 },
      { spot: 24200, expiry_pnl: 1000, target_pnl: 900 },
      { spot: 24400, expiry_pnl: -1000, target_pnl: -700 },
    ];
    const split = splitSeriesForECharts(sample);
    expect(split.positiveExpiry).toContainEqual([24100, 0]);
    expect(split.negativeExpiry).toContainEqual([24100, 0]);
    expect(split.positiveExpiry).toContainEqual([24300, 0]);
    expect(split.negativeExpiry).toContainEqual([24300, 0]);
  });
});

