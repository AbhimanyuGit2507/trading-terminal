import type { ExchangeSegment, LegOptionType, OptionSide } from "./types";

const BROKERAGE_PER_ORDER = 20.0;
const STT_OPTION_SELL = 0.001;
const STT_FUT_SELL = 0.0002;
const EXCHANGE_TXN_NSE_OPT = 0.0003503;
const EXCHANGE_TXN_BSE_OPT = 0.000325;
const EXCHANGE_TXN_FUT = 0.0000173;
const SEBI_TURNOVER_FEE = 0.000001;
const STAMP_DUTY_OPT_BUY = 0.00003;
const STAMP_DUTY_FUT_BUY = 0.00002;
const GST_RATE = 0.18;

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

export function estimateLegCharges(
  price: number,
  quantity: number,
  side: OptionSide,
  optionType: LegOptionType,
  exchange: ExchangeSegment = "NSE_FNO",
  ordersCount = 1
): number {
  const turnover = Math.max(price, 0.0) * Math.abs(quantity);
  const brokerage = BROKERAGE_PER_ORDER * ordersCount;

  let stt = 0.0;
  let exch = 0.0;
  let stamp = 0.0;

  if (optionType === "FUT") {
    stt = side === "SELL" ? turnover * STT_FUT_SELL : 0.0;
    exch = turnover * EXCHANGE_TXN_FUT;
    stamp = side === "BUY" ? turnover * STAMP_DUTY_FUT_BUY : 0.0;
  } else {
    stt = side === "SELL" ? turnover * STT_OPTION_SELL : 0.0;
    const exchRate = exchange === "BSE_FNO" ? EXCHANGE_TXN_BSE_OPT : EXCHANGE_TXN_NSE_OPT;
    exch = turnover * exchRate;
    stamp = side === "BUY" ? turnover * STAMP_DUTY_OPT_BUY : 0.0;
  }

  const sebiFee = turnover * SEBI_TURNOVER_FEE;
  const gst = GST_RATE * (brokerage + exch + sebiFee);
  return round2(brokerage + stt + exch + sebiFee + stamp + gst);
}
