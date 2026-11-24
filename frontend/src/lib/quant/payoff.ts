import {
  greeksBlack76Scalar,
  normCdf,
  priceBlack76GridInto,
  timeToExpiryYears,
} from "./black76";
import { estimateLegCharges } from "./charges";
import type {
  EChartsSplitSeries,
  PayoffCurvePoint,
  PayoffEvaluation,
  QuantLeg,
} from "./types";

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

function round4(v: number): number {
  return Math.round(v * 10000) / 10000;
}

function buildSpotGrid(
  spot: number,
  legs: QuantLeg[],
  atmIv: number,
  maxT: number,
  numPoints = 251
): Float64Array {
  const strikes = legs
    .map((l) => l.strike)
    .filter((s): s is number => s !== null && s !== undefined);

  const minRef = strikes.length > 0 ? Math.min(spot, ...strikes) : spot;
  const maxRef = strikes.length > 0 ? Math.max(spot, ...strikes) : spot;
  const volMove = 3.5 * spot * Math.max(atmIv, 0.08) * Math.sqrt(Math.max(maxT, 1.0 / 365.0));
  const pad = Math.max(volMove, 0.08 * spot);

  const low = Math.max(1.0, minRef - pad);
  const high = maxRef + pad;

  const raw: number[] = [];
  const step = (high - low) / (numPoints - 1);
  for (let i = 0; i < numPoints; i++) {
    raw.push(low + i * step);
  }
  for (const s of [...strikes, spot]) {
    if (s >= low && s <= high) {
      raw.push(s);
    }
  }
  raw.sort((a, b) => a - b);

  const unique: number[] = [];
  for (const val of raw) {
    if (unique.length === 0 || Math.abs(val - unique[unique.length - 1]) > 1e-12) {
      unique.push(val);
    }
  }
  return Float64Array.from(unique);
}

function findZeroCrossings(xs: Float64Array, ys: Float64Array): number[] {
  const roots: number[] = [];
  const n = xs.length;
  for (let i = 0; i < n - 1; i++) {
    const y0 = ys[i];
    const y1 = ys[i + 1];
    const x0 = xs[i];
    const x1 = xs[i + 1];
    if (y0 === 0.0) {
      const r = round2(x0);
      if (roots.length === 0 || Math.abs(roots[roots.length - 1] - r) > 1e-4) {
        roots.push(r);
      }
    } else if ((y0 < 0.0 && y1 > 0.0) || (y0 > 0.0 && y1 < 0.0)) {
      const frac = -y0 / (y1 - y0);
      const r = round2(x0 + frac * (x1 - x0));
      if (roots.length === 0 || Math.abs(roots[roots.length - 1] - r) > 1e-4) {
        roots.push(r);
      }
    }
  }
  if (n > 0 && ys[n - 1] === 0.0) {
    const xLast = round2(xs[n - 1]);
    if (roots.length === 0 || Math.abs(roots[roots.length - 1] - xLast) > 1e-4) {
      roots.push(xLast);
    }
  }
  return roots;
}

function evaluateLegsAtDatetime(
  spotGrid: Float64Array,
  legs: QuantLeg[],
  baseSpot: number,
  baseIso: string,
  evalIso: string,
  ivShiftPct: number,
  r = 0.0
): Float64Array {
  const n = spotGrid.length;
  const total = new Float64Array(n);
  const fwdGrid = new Float64Array(n);
  const legPrices = new Float64Array(n);
  const ivDelta = ivShiftPct / 100.0;

  for (const leg of legs) {
    if (!leg.enabled || leg.status !== "OPEN") continue;
    const signedQty = leg.lots * leg.lot_size * (leg.side === "BUY" ? 1 : -1);
    const tBase = timeToExpiryYears(baseIso, leg.expiry);
    const tEval = timeToExpiryYears(evalIso, leg.expiry);
    const baseFwd = leg.forward_at_base ?? baseSpot;
    const basis = baseFwd - baseSpot;
    const basisScale = tBase > 1e-9 ? tEval / tBase : 0.0;

    for (let i = 0; i < n; i++) {
      const f = spotGrid[i] + basis * basisScale;
      fwdGrid[i] = f > 0.01 ? f : 0.01;
    }

    if (leg.option_type === "FUT") {
      for (let i = 0; i < n; i++) {
        total[i] += signedQty * (fwdGrid[i] - leg.entry_price);
      }
    } else {
      const strike = leg.strike ?? baseSpot;
      const sigma = Math.max(leg.entry_iv + ivDelta, 0.005);
      priceBlack76GridInto(fwdGrid, strike, tEval, sigma, leg.option_type, legPrices, r);
      for (let i = 0; i < n; i++) {
        total[i] += signedQty * (legPrices[i] - leg.entry_price);
      }
    }
  }
  return total;
}

function detectUnlimited(legs: QuantLeg[]): [boolean, boolean] {
  let upsideSlope = 0.0;
  for (const leg of legs) {
    if (!leg.enabled || leg.status !== "OPEN") continue;
    const q = leg.lots * leg.lot_size * (leg.side === "BUY" ? 1 : -1);
    if (leg.option_type === "CE" || leg.option_type === "FUT") {
      upsideSlope += q;
    }
  }
  return [upsideSlope > 1e-9, upsideSlope < -1e-9];
}

function interpGrid(x: number, xs: Float64Array, ys: Float64Array): number {
  const n = xs.length;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[n - 1]) return ys[n - 1];
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid;
    else hi = mid;
  }
  const t = (x - xs[lo]) / (xs[hi] - xs[lo]);
  return ys[lo] + t * (ys[hi] - ys[lo]);
}

function computePop(
  spot: number,
  breakevens: number[],
  expiryVals: Float64Array,
  spotGrid: Float64Array,
  atmIv: number,
  tYears: number
): number {
  if (spotGrid.length < 2 || tYears <= 1e-6) {
    let bestIdx = 0;
    let bestDiff = Infinity;
    for (let i = 0; i < spotGrid.length; i++) {
      const d = Math.abs(spotGrid[i] - spot);
      if (d < bestDiff) {
        bestDiff = d;
        bestIdx = i;
      }
    }
    return expiryVals[bestIdx] > 0 ? 100.0 : 0.0;
  }

  const sig = Math.max(atmIv, 0.05);
  const sqrtT = Math.sqrt(tYears);
  const cdfSpot = (x: number): number => {
    if (x <= 0.0) return 0.0;
    const z = (Math.log(x / spot) + 0.5 * sig * sig * tYears) / (sig * sqrtT);
    return normCdf(z);
  };

  const sortedBe = [...breakevens].sort((a, b) => a - b);
  const boundaries = [0.0, ...sortedBe, Infinity];
  let prob = 0.0;

  for (let i = 0; i < boundaries.length - 1; i++) {
    const lo = boundaries[i];
    const hi = boundaries[i + 1];
    let sampleX: number;
    if (hi === Infinity) {
      sampleX = Math.max(lo * 1.05 + 1.0, spotGrid[spotGrid.length - 1]);
    } else if (lo === 0.0) {
      sampleX = Math.min(hi * 0.95, spotGrid[0]);
    } else {
      sampleX = 0.5 * (lo + hi);
    }

    const val = interpGrid(sampleX, spotGrid, expiryVals);
    if (val > 0.0) {
      const pHi = hi === Infinity ? 1.0 : cdfSpot(hi);
      const pLo = lo === 0.0 ? 0.0 : cdfSpot(lo);
      prob += Math.max(0.0, pHi - pLo);
    }
  }
  return round2(Math.min(100.0, Math.max(0.0, prob * 100.0)));
}

export interface EvaluatePayoffInput {
  spot: number;
  legs: QuantLeg[];
  baseDtIso: string;
  targetSpot?: number;
  targetDtIso?: string;
  ivShiftPct?: number;
  realizedPnl?: number;
  includeCharges?: boolean;
  atmIv?: number;
  r?: number;
}

export function evaluatePayoff(input: EvaluatePayoffInput): PayoffEvaluation {
  const {
    spot,
    legs,
    baseDtIso,
    targetSpot = spot,
    targetDtIso = baseDtIso,
    ivShiftPct = 0.0,
    realizedPnl = 0.0,
    includeCharges = false,
    atmIv = 0.14,
    r = 0.0,
  } = input;

  const activeLegs = legs.filter((l) => l.enabled && l.status === "OPEN");

  let charges = 0.0;
  if (includeCharges) {
    for (const leg of activeLegs) {
      charges += estimateLegCharges(
        leg.entry_price,
        leg.lots * leg.lot_size,
        leg.side,
        leg.option_type,
        leg.exchange ?? "NSE_FNO"
      );
    }
    charges = round2(charges);
  }
  const netOffset = realizedPnl - charges;

  if (activeLegs.length === 0) {
    const grid = buildSpotGrid(spot, [], atmIv, 7.0 / 365.0);
    const points: PayoffCurvePoint[] = Array.from(grid, (s) => ({
      spot: round2(s),
      expiry_pnl: round2(netOffset),
      target_pnl: round2(netOffset),
    }));
    const vol = spot * Math.max(atmIv, 0.05) * Math.sqrt(7.0 / 365.0);
    return {
      points,
      breakevens: [],
      target_breakevens: [],
      max_profit: round2(netOffset),
      max_loss: round2(netOffset),
      max_profit_unlimited: false,
      max_loss_unlimited: false,
      risk_reward: null,
      pop: netOffset > 0 ? 100.0 : 0.0,
      net_greeks: { delta: 0, gamma: 0, theta: 0, vega: 0 },
      current_mtm_pnl: round2(netOffset),
      estimated_charges: round2(charges),
      sd_1_low: round2(spot - vol),
      sd_1_high: round2(spot + vol),
      sd_2_low: round2(spot - 2.0 * vol),
      sd_2_high: round2(spot + 2.0 * vol),
    };
  }

  let nearestExpiry = activeLegs[0].expiry;
  let maxT = 0.0;
  for (const leg of activeLegs) {
    if (leg.expiry < nearestExpiry) nearestExpiry = leg.expiry;
    const t = timeToExpiryYears(baseDtIso, leg.expiry);
    if (t > maxT) maxT = t;
  }
  const nearestExpIso = `${nearestExpiry}T15:30:00+05:30`;
  const nearestT = Math.max(timeToExpiryYears(baseDtIso, nearestExpiry), 1.0 / 365.0);

  const grid = buildSpotGrid(spot, activeLegs, atmIv, maxT);
  const expiryVals = evaluateLegsAtDatetime(
    grid,
    activeLegs,
    spot,
    baseDtIso,
    nearestExpIso,
    ivShiftPct,
    r
  );
  const targetVals = evaluateLegsAtDatetime(
    grid,
    activeLegs,
    spot,
    baseDtIso,
    targetDtIso,
    ivShiftPct,
    r
  );

  for (let i = 0; i < grid.length; i++) {
    expiryVals[i] += netOffset;
    targetVals[i] += netOffset;
  }

  const breakevens = findZeroCrossings(grid, expiryVals);
  const targetBreakevens = findZeroCrossings(grid, targetVals);
  const [mpUnlim, mlUnlim] = detectUnlimited(activeLegs);

  const zeroArr = new Float64Array([0.0]);
  const valAtZero =
    evaluateLegsAtDatetime(zeroArr, activeLegs, spot, baseDtIso, nearestExpIso, ivShiftPct, r)[0] +
    netOffset;

  let rawMax = valAtZero;
  let rawMin = valAtZero;
  for (let i = 0; i < expiryVals.length; i++) {
    if (expiryVals[i] > rawMax) rawMax = expiryVals[i];
    if (expiryVals[i] < rawMin) rawMin = expiryVals[i];
  }

  const maxProfit = mpUnlim ? null : round2(rawMax);
  const maxLoss = mlUnlim ? null : round2(rawMin);
  const riskReward =
    maxProfit !== null && maxLoss !== null && maxLoss < 0.0
      ? round2(Math.abs(maxProfit / maxLoss))
      : null;

  let netDelta = 0.0;
  let netGamma = 0.0;
  let netTheta = 0.0;
  let netVega = 0.0;
  let mtmTotal = netOffset;
  const ivDelta = ivShiftPct / 100.0;

  for (const leg of activeLegs) {
    const signedQty = leg.lots * leg.lot_size * (leg.side === "BUY" ? 1 : -1);
    const tBase = timeToExpiryYears(baseDtIso, leg.expiry);
    const tEval = timeToExpiryYears(targetDtIso, leg.expiry);
    const baseFwd = leg.forward_at_base ?? spot;
    const basis = baseFwd - spot;
    const basisScale = tBase > 1e-9 ? tEval / tBase : 0.0;
    const fwd = Math.max(targetSpot + basis * basisScale, 0.01);

    if (leg.option_type === "FUT") {
      mtmTotal += signedQty * (fwd - leg.entry_price);
      netDelta += signedQty;
    } else {
      const g = greeksBlack76Scalar(
        fwd,
        leg.strike ?? targetSpot,
        tEval,
        Math.max(leg.entry_iv + ivDelta, 0.005),
        leg.option_type,
        r
      );
      mtmTotal += signedQty * (g.price - leg.entry_price);
      netDelta += signedQty * g.delta;
      netGamma += signedQty * g.gamma;
      netTheta += signedQty * g.theta;
      netVega += signedQty * g.vega;
    }
  }

  const avgIv =
    activeLegs.reduce((acc, l) => acc + l.entry_iv, 0.0) / activeLegs.length;
  const pop = computePop(spot, breakevens, expiryVals, grid, avgIv, nearestT);
  const vol = spot * Math.max(avgIv, 0.05) * Math.sqrt(nearestT);

  const points: PayoffCurvePoint[] = new Array(grid.length);
  for (let i = 0; i < grid.length; i++) {
    points[i] = {
      spot: round2(grid[i]),
      expiry_pnl: round2(expiryVals[i]),
      target_pnl: round2(targetVals[i]),
    };
  }

  return {
    points,
    breakevens,
    target_breakevens: targetBreakevens,
    max_profit: maxProfit,
    max_loss: maxLoss,
    max_profit_unlimited: mpUnlim,
    max_loss_unlimited: mlUnlim,
    risk_reward: riskReward,
    pop,
    net_greeks: {
      delta: round2(netDelta),
      gamma: round4(netGamma),
      theta: round2(netTheta),
      vega: round2(netVega),
    },
    current_mtm_pnl: round2(mtmTotal),
    estimated_charges: round2(charges),
    sd_1_low: round2(spot - vol),
    sd_1_high: round2(spot + vol),
    sd_2_low: round2(spot - 2.0 * vol),
    sd_2_high: round2(spot + 2.0 * vol),
  };
}

/**
 * Split PayoffCurvePoint[] into zero-crossing-exact green/red ECharts series
 * so positive and negative area fills meet cleanly at y=0 without visual bleed.
 */
export function splitSeriesForECharts(points: PayoffCurvePoint[]): EChartsSplitSeries {
  const positiveExpiry: Array<[number, number | null]> = [];
  const negativeExpiry: Array<[number, number | null]> = [];
  const targetCurve: Array<[number, number]> = [];

  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    targetCurve.push([p.spot, p.target_pnl]);

    if (p.expiry_pnl >= 0) {
      positiveExpiry.push([p.spot, p.expiry_pnl]);
      negativeExpiry.push([p.spot, p.expiry_pnl === 0 ? 0 : null]);
    } else {
      positiveExpiry.push([p.spot, null]);
      negativeExpiry.push([p.spot, p.expiry_pnl]);
    }

    if (i < points.length - 1) {
      const next = points[i + 1];
      if (
        (p.expiry_pnl < 0 && next.expiry_pnl > 0) ||
        (p.expiry_pnl > 0 && next.expiry_pnl < 0)
      ) {
        const frac = -p.expiry_pnl / (next.expiry_pnl - p.expiry_pnl);
        const xZero = round2(p.spot + frac * (next.spot - p.spot));
        positiveExpiry.push([xZero, 0]);
        negativeExpiry.push([xZero, 0]);
      }
    }
  }

  return { positiveExpiry, negativeExpiry, targetCurve };
}

