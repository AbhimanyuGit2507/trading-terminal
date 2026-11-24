import type { GreeksResult } from "./types";

export const INV_SQRT_2PI = 1.0 / Math.sqrt(2.0 * Math.PI);
export const T_FLOOR = 1e-6;
export const SIGMA_FLOOR = 1e-4;
export const SECONDS_PER_CALENDAR_YEAR = 365.0 * 86400.0;

/**
 * High-precision complementary error function erfc(x) using W. J. Cody's
 * Chebyshev rational approximation (accurate to ~1e-15).
 */
export function erfcCody(x: number): number {
  const z = Math.abs(x);
  if (z === 0) return 1.0;

  let res: number;
  if (z <= 0.46875) {
    const z2 = z * z;
    const xnum =
      (((1.85777706184603153e-1 * z2 + 3.1611237438705656e0) * z2 + 1.13864154151050156e2) * z2 +
        3.77485237685302021e2) *
        z2 +
      3.20937758913846947e3;
    const xden =
      (((z2 + 2.36012909523441209e1) * z2 + 2.44024637934444173e2) * z2 + 1.28261652607737228e3) *
        z2 +
      2.84423683343917062e3;
    res = 1.0 - (z * xnum) / xden;
  } else if (z <= 4.0) {
    const xnum =
      (((((((2.15311535474403846e-8 * z + 5.64188496988670089e-1) * z + 8.88314979438837594e0) *
        z +
        6.61191906371416295e1) *
        z +
        2.98635138197400131e2) *
        z +
        8.8195222124176909e2) *
        z +
        1.71204761263407058e3) *
        z +
        2.05107837782607147e3) *
        z +
      1.23033935479799725e3;
    const xden =
      (((((((z + 1.57449261107098347e1) * z + 1.17693950891312499e2) * z + 5.37181101862009858e2) *
        z +
        1.62138957456669019e3) *
        z +
        3.29079923573345963e3) *
        z +
        4.36261909014324716e3) *
        z +
        3.43936767414372164e3) *
        z +
      1.23033935480374942e3;
    res = Math.exp(-z * z) * (xnum / xden);
  } else {
    if (z >= 26.6) {
      res = 0.0;
    } else {
      const z2 = 1.0 / (z * z);
      const xnum =
        ((((1.63153871373020978e-2 * z2 + 3.05326634961232344e-1) * z2 + 3.60344899949804439e-1) *
          z2 +
          1.25781726111229246e-1) *
          z2 +
          1.60837851487422766e-2) *
          z2 +
        6.58749161529837803e-4;
      const xden =
        ((((z2 + 2.5685201922898222e0) * z2 + 1.87295284992346047e0) * z2 + 5.27905102951428412e-1) *
          z2 +
          6.05183413124413191e-2) *
          z2 +
        2.33520497626869185e-3;
      const rVal = (z2 * xnum) / xden;
      res = (Math.exp(-z * z) * (0.56418958354775628695 - rVal)) / z;
    }
  }

  return x < 0 ? 2.0 - res : res;
}

export function normCdf(x: number): number {
  return 0.5 * erfcCody(-x * Math.SQRT1_2);
}

/**
 * Exact calendar-year fraction until 15:30 IST on expiryDate (0.0 if expired).
 */
export function timeToExpiryYears(evalIso: string, expiryDate: string): number {
  const evalMs = Date.parse(evalIso);
  const expMs = Date.parse(`${expiryDate}T15:30:00+05:30`);
  if (Number.isNaN(evalMs) || Number.isNaN(expMs) || evalMs >= expMs) {
    return 0.0;
  }
  return (expMs - evalMs) / 1000.0 / SECONDS_PER_CALENDAR_YEAR;
}

export function priceBlack76Scalar(
  forward: number,
  strike: number,
  tYears: number,
  sigma: number,
  optionType: "CE" | "PE",
  r = 0.0
): number {
  if (tYears <= 0.0) {
    return optionType === "CE" ? Math.max(forward - strike, 0.0) : Math.max(strike - forward, 0.0);
  }
  const f = Math.max(forward, 1e-8);
  const k = Math.max(strike, 1e-8);
  const tEff = Math.max(tYears, T_FLOOR);
  const sig = Math.max(sigma, SIGMA_FLOOR);
  const sqrtT = Math.sqrt(tEff);
  const df = Math.exp(-r * tEff);

  const d1 = (Math.log(f / k) + 0.5 * sig * sig * tEff) / (sig * sqrtT);
  const d2 = d1 - sig * sqrtT;
  const nd1 = normCdf(d1);
  const nd2 = normCdf(d2);

  if (optionType === "CE") {
    return df * (f * nd1 - k * nd2);
  }
  return df * (k * (1.0 - nd2) - f * (1.0 - nd1));
}

export function greeksBlack76Scalar(
  forward: number,
  strike: number,
  tYears: number,
  sigma: number,
  optionType: "CE" | "PE",
  r = 0.0
): GreeksResult {
  if (tYears <= 0.0) {
    if (optionType === "CE") {
      return {
        price: Math.max(forward - strike, 0.0),
        delta: forward > strike ? 1.0 : 0.0,
        gamma: 0.0,
        theta: 0.0,
        vega: 0.0,
      };
    }
    return {
      price: Math.max(strike - forward, 0.0),
      delta: forward < strike ? -1.0 : 0.0,
      gamma: 0.0,
      theta: 0.0,
      vega: 0.0,
    };
  }

  const f = Math.max(forward, 1e-8);
  const k = Math.max(strike, 1e-8);
  const tEff = Math.max(tYears, T_FLOOR);
  const sig = Math.max(sigma, SIGMA_FLOOR);
  const sqrtT = Math.sqrt(tEff);
  const df = Math.exp(-r * tEff);

  const d1 = (Math.log(f / k) + 0.5 * sig * sig * tEff) / (sig * sqrtT);
  const d2 = d1 - sig * sqrtT;

  const nd1 = normCdf(d1);
  const nd2 = normCdf(d2);
  const pdf1 = INV_SQRT_2PI * Math.exp(-0.5 * d1 * d1);

  let price: number;
  let delta: number;
  if (optionType === "CE") {
    price = df * (f * nd1 - k * nd2);
    delta = df * nd1;
  } else {
    price = df * (k * (1.0 - nd2) - f * (1.0 - nd1));
    delta = df * (nd1 - 1.0);
  }

  const thetaAnnual = -(df * f * pdf1 * sig) / (2.0 * sqrtT) + r * price;
  const gamma = (df * pdf1) / (f * sig * sqrtT);
  const vega = df * f * pdf1 * sqrtT * 0.01;
  const theta = thetaAnnual / 365.0;

  return { price, delta, gamma, theta, vega };
}

/**
 * Zero-allocation Float64Array vectorized Black-76 pricing for 120fps slider drags.
 */
export function priceBlack76GridInto(
  forwards: Float64Array,
  strike: number,
  tYears: number,
  sigma: number,
  optionType: "CE" | "PE",
  outPrices: Float64Array,
  r = 0.0
): void {
  const n = forwards.length;
  if (tYears <= 0.0) {
    if (optionType === "CE") {
      for (let i = 0; i < n; i++) {
        const diff = forwards[i] - strike;
        outPrices[i] = diff > 0 ? diff : 0;
      }
    } else {
      for (let i = 0; i < n; i++) {
        const diff = strike - forwards[i];
        outPrices[i] = diff > 0 ? diff : 0;
      }
    }
    return;
  }

  const k = Math.max(strike, 1e-8);
  const tEff = Math.max(tYears, T_FLOOR);
  const sig = Math.max(sigma, SIGMA_FLOOR);
  const sqrtT = Math.sqrt(tEff);
  const sigSqrtT = sig * sqrtT;
  const halfVarT = 0.5 * sig * sig * tEff;
  const df = Math.exp(-r * tEff);
  const isCall = optionType === "CE";

  for (let i = 0; i < n; i++) {
    const f = forwards[i] > 1e-8 ? forwards[i] : 1e-8;
    const d1 = (Math.log(f / k) + halfVarT) / sigSqrtT;
    const d2 = d1 - sigSqrtT;
    const nd1 = normCdf(d1);
    const nd2 = normCdf(d2);
    outPrices[i] = isCall
      ? df * (f * nd1 - k * nd2)
      : df * (k * (1.0 - nd2) - f * (1.0 - nd1));
  }
}
