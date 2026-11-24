import type {
  ExchangeSegment,
  IndexSymbol,
  OptionChainRow,
  OptionChainSnapshot,
  OptionSide,
  StrategyLeg,
} from "./api/types";

export type PresetKey =
  | "short_straddle"
  | "long_straddle"
  | "short_strangle"
  | "iron_fly"
  | "iron_condor"
  | "bull_call_spread"
  | "bear_put_spread"
  | "calendar_spread";

export interface PresetDefinition {
  key: PresetKey;
  label: string;
  bias: "Neutral" | "Bullish" | "Bearish" | "Volatility";
}

export const STRATEGY_PRESETS: PresetDefinition[] = [
  { key: "short_straddle", label: "Short Straddle", bias: "Neutral" },
  { key: "long_straddle", label: "Long Straddle", bias: "Volatility" },
  { key: "short_strangle", label: "Short Strangle", bias: "Neutral" },
  { key: "iron_fly", label: "Iron Fly", bias: "Neutral" },
  { key: "iron_condor", label: "Iron Condor", bias: "Neutral" },
  { key: "bull_call_spread", label: "Bull Call Spread", bias: "Bullish" },
  { key: "bear_put_spread", label: "Bear Put Spread", bias: "Bearish" },
  { key: "calendar_spread", label: "Calendar Spread", bias: "Neutral" },
];

function makeLegFromRow(
  row: OptionChainRow,
  optionType: "CE" | "PE",
  side: OptionSide,
  lots: number,
  snapshot: {
    symbol: IndexSymbol;
    exchange: ExchangeSegment;
    expiry: string;
    lot_size: number;
    forward_price: number;
  }
): StrategyLeg {
  const isCall = optionType === "CE";
  return {
    leg_id: crypto.randomUUID(),
    contract_id: isCall ? row.ce_contract_id : row.pe_contract_id,
    symbol: snapshot.symbol,
    exchange: snapshot.exchange,
    expiry: snapshot.expiry,
    strike: row.strike,
    option_type: optionType,
    side,
    lots,
    lot_size: snapshot.lot_size,
    entry_price: isCall ? row.ce_ltp : row.pe_ltp,
    entry_iv: (isCall ? row.ce_iv : row.pe_iv) / 100.0,
    forward_at_base: snapshot.forward_price,
    enabled: true,
    status: "OPEN",
  };
}

export function buildPresetLegs(
  preset: PresetKey,
  chain: OptionChainSnapshot,
  farChain?: OptionChainSnapshot | null,
  lots = 1
): StrategyLeg[] {
  const rows = chain.rows;
  if (rows.length === 0) return [];

  let atmIdx = 0;
  let bestDiff = Infinity;
  for (let i = 0; i < rows.length; i++) {
    const d = Math.abs(rows[i].strike - chain.atm_strike);
    if (d < bestDiff) {
      bestDiff = d;
      atmIdx = i;
    }
  }

  const pickRow = (offset: number): OptionChainRow => {
    const idx = Math.max(0, Math.min(rows.length - 1, atmIdx + offset));
    return rows[idx];
  };

  const atm = pickRow(0);

  switch (preset) {
    case "short_straddle":
      return [
        makeLegFromRow(atm, "CE", "SELL", lots, chain),
        makeLegFromRow(atm, "PE", "SELL", lots, chain),
      ];
    case "long_straddle":
      return [
        makeLegFromRow(atm, "CE", "BUY", lots, chain),
        makeLegFromRow(atm, "PE", "BUY", lots, chain),
      ];
    case "short_strangle":
      return [
        makeLegFromRow(pickRow(2), "CE", "SELL", lots, chain),
        makeLegFromRow(pickRow(-2), "PE", "SELL", lots, chain),
      ];
    case "iron_fly":
      return [
        makeLegFromRow(atm, "CE", "SELL", lots, chain),
        makeLegFromRow(atm, "PE", "SELL", lots, chain),
        makeLegFromRow(pickRow(4), "CE", "BUY", lots, chain),
        makeLegFromRow(pickRow(-4), "PE", "BUY", lots, chain),
      ];
    case "iron_condor":
      return [
        makeLegFromRow(pickRow(2), "CE", "SELL", lots, chain),
        makeLegFromRow(pickRow(5), "CE", "BUY", lots, chain),
        makeLegFromRow(pickRow(-2), "PE", "SELL", lots, chain),
        makeLegFromRow(pickRow(-5), "PE", "BUY", lots, chain),
      ];
    case "bull_call_spread":
      return [
        makeLegFromRow(atm, "CE", "BUY", lots, chain),
        makeLegFromRow(pickRow(3), "CE", "SELL", lots, chain),
      ];
    case "bear_put_spread":
      return [
        makeLegFromRow(atm, "PE", "BUY", lots, chain),
        makeLegFromRow(pickRow(-3), "PE", "SELL", lots, chain),
      ];
    case "calendar_spread": {
      const legs = [makeLegFromRow(atm, "CE", "SELL", lots, chain)];
      if (farChain && farChain.rows.length > 0) {
        const farAtm = farChain.rows.reduce((best, r) =>
          Math.abs(r.strike - atm.strike) < Math.abs(best.strike - atm.strike) ? r : best
        );
        legs.push(makeLegFromRow(farAtm, "CE", "BUY", lots, farChain));
      }
      return legs;
    }
  }
}

