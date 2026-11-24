export type IndexSymbol = "NIFTY" | "BANKNIFTY" | "FINNIFTY" | "SENSEX";
export type ExchangeSegment = "NSE_FNO" | "BSE_FNO";
export type OptionSide = "BUY" | "SELL";
export type LegOptionType = "CE" | "PE" | "FUT";

export interface QuantLeg {
  leg_id: string;
  symbol: IndexSymbol;
  expiry: string; // YYYY-MM-DD
  option_type: LegOptionType;
  side: OptionSide;
  lots: number;
  lot_size: number;
  entry_price: number;
  entry_iv: number; // decimal e.g. 0.14
  strike: number | null;
  forward_at_base?: number | null;
  enabled: boolean;
  status: "OPEN" | "CLOSED";
  exchange?: ExchangeSegment;
}

export interface GreeksResult {
  price: number;
  delta: number;
  gamma: number;
  theta: number; // per calendar day
  vega: number; // per 1% IV change
}

export interface PayoffCurvePoint {
  spot: number;
  expiry_pnl: number;
  target_pnl: number;
}

export interface NetGreeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

export interface PayoffEvaluation {
  points: PayoffCurvePoint[];
  breakevens: number[];
  target_breakevens: number[];
  max_profit: number | null;
  max_loss: number | null;
  max_profit_unlimited: boolean;
  max_loss_unlimited: boolean;
  risk_reward: number | null;
  pop: number;
  net_greeks: NetGreeks;
  current_mtm_pnl: number;
  estimated_charges: number;
  sd_1_low: number;
  sd_1_high: number;
  sd_2_low: number;
  sd_2_high: number;
}

export interface EChartsSplitSeries {
  positiveExpiry: Array<[number, number | null]>;
  negativeExpiry: Array<[number, number | null]>;
  targetCurve: Array<[number, number]>;
}

