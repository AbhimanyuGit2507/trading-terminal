import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import { getBatchQuotes, getOptionChain } from "@/lib/api/client";
import type { WsConnectionStatus } from "@/lib/api/wsClient";
import type {
  DhanStatusResponse,
  ExchangeSegment,
  ExpiryInfo,
  FeedStatus,
  IndexSymbol,
  InstrumentSpec,
  LegQuote,
  OptionChainRow,
  OptionChainSnapshot,
  WsTickFrame,
} from "@/lib/api/types";

export interface MarketState {
  instruments: InstrumentSpec[];
  symbol: IndexSymbol;
  exchange: ExchangeSegment;
  selectedChainExpiry: string;
  expiries: ExpiryInfo[];
  asOfIso: string;
  spot: number;
  futuresPrice: number;
  forwardPrice: number;
  indiaVix: number;
  atmStrike: number;
  lotSize: number;
  strikeStep: number;
  futuresContractId: string;
  strikes: number[];
  rowsByStrike: Record<number, OptionChainRow>;
  maxOi: number;
  /** Multi-expiry quote cache so Calendar/Diagonal legs stay live across expiry switches */
  activeLegQuotes: Record<string, LegQuote>;
  feedStatus: FeedStatus;
  dhanStatus: DhanStatusResponse | null;
  wsStatus: WsConnectionStatus;
  isLoadingChain: boolean;
  error: string | null;

  setInstruments: (specs: InstrumentSpec[]) => void;
  setWsStatus: (status: WsConnectionStatus) => void;
  setDhanStatus: (status: DhanStatusResponse) => void;
  setSnapshot: (snapshot: OptionChainSnapshot) => void;
  applyTickFrame: (frame: WsTickFrame) => void;
  mergeActiveLegQuotes: (quotes: Record<string, LegQuote>) => void;
  loadChain: (symbol: IndexSymbol, expiry?: string, asOf?: string) => Promise<OptionChainSnapshot>;
  refreshActiveLegQuotes: (contractIds: string[], asOf?: string) => Promise<void>;
  getCurrentSnapshot: () => OptionChainSnapshot | null;
}

function buildRowMap(rows: OptionChainRow[]): {
  strikes: number[];
  rowsByStrike: Record<number, OptionChainRow>;
  maxOi: number;
} {
  const strikes: number[] = new Array(rows.length);
  const rowsByStrike: Record<number, OptionChainRow> = {};
  let maxOi = 1;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    strikes[i] = r.strike;
    rowsByStrike[r.strike] = r;
    if (r.ce_oi > maxOi) maxOi = r.ce_oi;
    if (r.pe_oi > maxOi) maxOi = r.pe_oi;
  }
  return { strikes, rowsByStrike, maxOi };
}

export const useMarketStore = create<MarketState>()(
  subscribeWithSelector((set, get) => ({
    instruments: [],
    symbol: "NIFTY",
    exchange: "NSE_FNO",
    selectedChainExpiry: "",
    expiries: [],
    asOfIso: "",
    spot: 24350,
    futuresPrice: 24372,
    forwardPrice: 24372,
    indiaVix: 13.85,
    atmStrike: 24350,
    lotSize: 65,
    strikeStep: 50,
    futuresContractId: "",
    strikes: [],
    rowsByStrike: {},
    maxOi: 1,
    activeLegQuotes: {},
    feedStatus: "MOCK_FALLBACK",
    dhanStatus: null,
    wsStatus: "disconnected",
    isLoadingChain: false,
    error: null,

    setInstruments: (instruments) => set({ instruments }),
    setWsStatus: (wsStatus) => set({ wsStatus }),
    setDhanStatus: (dhanStatus) => set({ dhanStatus, feedStatus: dhanStatus.mode }),

    setSnapshot: (snapshot) => {
      const { strikes, rowsByStrike, maxOi } = buildRowMap(snapshot.rows);
      set((prev) => {
        const nextQuotes = { ...prev.activeLegQuotes };
        // Also refresh any matching active contracts present in the viewed snapshot
        for (const row of snapshot.rows) {
          if (nextQuotes[row.ce_contract_id]) {
            nextQuotes[row.ce_contract_id] = {
              contract_id: row.ce_contract_id,
              expiry: snapshot.expiry,
              strike: row.strike,
              option_type: "CE",
              ltp: row.ce_ltp,
              bid: row.ce_bid,
              ask: row.ce_ask,
              iv: row.ce_iv,
              delta: row.ce_delta,
              gamma: row.ce_gamma,
              theta: row.ce_theta,
              vega: row.ce_vega,
              forward_price: snapshot.forward_price,
              updated_at: snapshot.as_of,
            };
          }
          if (nextQuotes[row.pe_contract_id]) {
            nextQuotes[row.pe_contract_id] = {
              contract_id: row.pe_contract_id,
              expiry: snapshot.expiry,
              strike: row.strike,
              option_type: "PE",
              ltp: row.pe_ltp,
              bid: row.pe_bid,
              ask: row.pe_ask,
              iv: row.pe_iv,
              delta: row.pe_delta,
              gamma: row.pe_gamma,
              theta: row.pe_theta,
              vega: row.pe_vega,
              forward_price: snapshot.forward_price,
              updated_at: snapshot.as_of,
            };
          }
        }
        return {
          symbol: snapshot.symbol,
          exchange: snapshot.exchange,
          selectedChainExpiry: snapshot.expiry,
          expiries: snapshot.expiries,
          asOfIso: snapshot.as_of,
          spot: snapshot.spot,
          futuresPrice: snapshot.futures_price,
          forwardPrice: snapshot.forward_price,
          indiaVix: snapshot.india_vix,
          atmStrike: snapshot.atm_strike,
          lotSize: snapshot.lot_size,
          strikeStep: snapshot.strike_step,
          futuresContractId: snapshot.futures_contract_id,
          strikes,
          rowsByStrike,
          maxOi,
          feedStatus: snapshot.feed_status ?? prev.feedStatus,
          activeLegQuotes: nextQuotes,
          error: null,
        };
      });
    },

    applyTickFrame: (frame) => {
      if (frame.type !== "tick" || !frame.symbol) return;
      const cur = get();
      if (frame.symbol !== cur.symbol) return;

      const updates: Partial<MarketState> = {
        asOfIso: frame.as_of ?? cur.asOfIso,
        spot: frame.spot ?? cur.spot,
        futuresPrice: frame.futures_price ?? cur.futuresPrice,
        forwardPrice: frame.forward_price ?? cur.forwardPrice,
        indiaVix: frame.india_vix ?? cur.indiaVix,
        atmStrike: frame.atm_strike ?? cur.atmStrike,
        feedStatus: frame.feed_status ?? cur.feedStatus,
      };

      if (
        frame.chain_deltas &&
        frame.chain_deltas.length > 0 &&
        (!frame.chain_expiry || frame.chain_expiry === cur.selectedChainExpiry)
      ) {
        const { strikes, rowsByStrike, maxOi } = buildRowMap(frame.chain_deltas);
        updates.strikes = strikes;
        updates.rowsByStrike = rowsByStrike;
        updates.maxOi = maxOi;
      }

      if (frame.leg_quotes && Object.keys(frame.leg_quotes).length > 0) {
        updates.activeLegQuotes = {
          ...cur.activeLegQuotes,
          ...frame.leg_quotes,
        };
      }

      set(updates);
    },

    mergeActiveLegQuotes: (quotes) =>
      set((prev) => ({
        activeLegQuotes: { ...prev.activeLegQuotes, ...quotes },
      })),

    loadChain: async (symbol, expiry, asOf) => {
      set({ isLoadingChain: true, error: null });
      try {
        const snapshot = await getOptionChain(symbol, expiry, asOf);
        get().setSnapshot(snapshot);
        set({ isLoadingChain: false });
        return snapshot;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to load option chain";
        set({ isLoadingChain: false, error: msg });
        throw err;
      }
    },

    refreshActiveLegQuotes: async (contractIds, asOf) => {
      if (contractIds.length === 0) return;
      try {
        const quotes = await getBatchQuotes(contractIds, asOf);
        get().mergeActiveLegQuotes(quotes);
      } catch {
        // Non-fatal: activeLegQuotes retains last known quotes if backend is offline
      }
    },

    getCurrentSnapshot: () => {
      const s = get();
      if (!s.selectedChainExpiry || s.strikes.length === 0) return null;
      return {
        feed_status: s.feedStatus,
        symbol: s.symbol,
        exchange: s.exchange,
        expiry: s.selectedChainExpiry,
        as_of: s.asOfIso,
        spot: s.spot,
        futures_price: s.futuresPrice,
        forward_price: s.forwardPrice,
        india_vix: s.indiaVix,
        atm_strike: s.atmStrike,
        lot_size: s.lotSize,
        strike_step: s.strikeStep,
        futures_contract_id: s.futuresContractId,
        expiries: s.expiries,
        rows: s.strikes.map((k) => s.rowsByStrike[k]),
      };
    },
  }))
);
