import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import { executeOrders } from "@/lib/api/client";
import type {
  ClosedLegRecord,
  IndexSymbol,
  MarginBreakdown,
  OptionSide,
  SettledLegEvent,
  StrategyLeg,
  StrategyResponse,
} from "@/lib/api/types";
import { useMarketStore } from "./marketStore";

export interface WhatIfState {
  targetSpot: number;
  targetDatetimeIso: string;
  ivShiftPct: number;
}

export interface ModeWorkspaceSnapshot {
  strategyId: string | null;
  strategyName: string;
  legs: StrategyLeg[];
  closedLegs: ClosedLegRecord[];
  realizedPnl: number;
  lotMultiplier: number;
  margin: MarginBreakdown | null;
  whatIf: WhatIfState;
}

function createEmptyWorkspace(): ModeWorkspaceSnapshot {
  return {
    strategyId: null,
    strategyName: "Untitled Strategy",
    legs: [],
    closedLegs: [],
    realizedPnl: 0,
    lotMultiplier: 1,
    margin: null,
    whatIf: {
      targetSpot: 24350,
      targetDatetimeIso: new Date().toISOString(),
      ivShiftPct: 0,
    },
  };
}

export interface StrategyState {
  strategyId: string | null;
  strategyName: string;
  legs: StrategyLeg[];
  closedLegs: ClosedLegRecord[];
  realizedPnl: number;
  lotMultiplier: number;
  margin: MarginBreakdown | null;
  isLoadingMargin: boolean;
  isExecuting: boolean;
  lastExecutionNotice: string | null;
  whatIf: WhatIfState;
  workspacesByMode: Record<"builder" | "simulator", ModeWorkspaceSnapshot>;

  setStrategyName: (name: string) => void;
  setLotMultiplier: (factor: number) => void;
  setMargin: (margin: MarginBreakdown | null) => void;
  setIsLoadingMargin: (loading: boolean) => void;
  setWhatIf: (patch: Partial<WhatIfState>) => void;
  resetWhatIf: (spot?: number, dtIso?: string) => void;
  switchWorkspaceMode: (fromMode: "builder" | "simulator", toMode: "builder" | "simulator") => void;

  addLeg: (leg: StrategyLeg) => void;
  replaceWithLegs: (legs: StrategyLeg[], strategyName?: string) => void;
  toggleLegEnabled: (legId: string) => void;
  flipLegSide: (legId: string) => void;
  updateLegLots: (legId: string, lots: number) => void;
  removeLeg: (legId: string) => void;
  partialExitLeg: (legId: string, lotsToExit: number, exitPriceOverride?: number) => Promise<void>;
  squareOffAll: () => Promise<void>;
  applySettledLegs: (events: SettledLegEvent[], realizedDelta: number) => void;
  clearStrategy: () => void;
  loadSavedStrategy: (saved: StrategyResponse) => void;
  setLastExecutionNotice: (msg: string | null) => void;
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

export function getEffectiveLegs(legs: StrategyLeg[], lotMultiplier: number): StrategyLeg[] {
  const mult = Math.max(1, Math.floor(lotMultiplier));
  if (mult === 1) return legs;
  return legs.map((l) => ({ ...l, lots: l.lots * mult }));
}

export const useStrategyStore = create<StrategyState>()(
  subscribeWithSelector((set, get) => ({
    strategyId: null,
    strategyName: "Untitled Strategy",
    legs: [],
    closedLegs: [],
    realizedPnl: 0,
    lotMultiplier: 1,
    margin: null,
    isLoadingMargin: false,
    isExecuting: false,
    lastExecutionNotice: null,
    whatIf: {
      targetSpot: 24350,
      targetDatetimeIso: new Date().toISOString(),
      ivShiftPct: 0,
    },
    workspacesByMode: {
      builder: createEmptyWorkspace(),
      simulator: createEmptyWorkspace(),
    },

    setStrategyName: (strategyName) => set({ strategyName }),
    setLotMultiplier: (factor) => {
      const safe = Math.max(1, Math.floor(Number.isFinite(factor) ? factor : 1));
      set({ lotMultiplier: safe });
    },
    setMargin: (margin) => set({ margin }),
    setIsLoadingMargin: (isLoadingMargin) => set({ isLoadingMargin }),
    setLastExecutionNotice: (lastExecutionNotice) => set({ lastExecutionNotice }),

    switchWorkspaceMode: (fromMode, toMode) => {
      if (fromMode === toMode) return;
      const cur = get();
      const savedFrom: ModeWorkspaceSnapshot = {
        strategyId: cur.strategyId,
        strategyName: cur.strategyName,
        legs: cur.legs,
        closedLegs: cur.closedLegs,
        realizedPnl: cur.realizedPnl,
        lotMultiplier: cur.lotMultiplier,
        margin: cur.margin,
        whatIf: cur.whatIf,
      };
      const target = cur.workspacesByMode[toMode];
      set({
        strategyId: target.strategyId,
        strategyName: target.strategyName,
        legs: target.legs,
        closedLegs: target.closedLegs,
        realizedPnl: target.realizedPnl,
        lotMultiplier: target.lotMultiplier,
        margin: target.margin,
        whatIf: target.whatIf,
        lastExecutionNotice: null,
        workspacesByMode: {
          ...cur.workspacesByMode,
          [fromMode]: savedFrom,
        },
      });
    },

    setWhatIf: (patch) =>
      set((state) => ({
        whatIf: { ...state.whatIf, ...patch },
      })),

    resetWhatIf: (spot, dtIso) => {
      const m = useMarketStore.getState();
      set({
        whatIf: {
          targetSpot: spot ?? m.spot,
          targetDatetimeIso: dtIso ?? (m.asOfIso || new Date().toISOString()),
          ivShiftPct: 0,
        },
      });
    },

    addLeg: (leg) => {
      set((state) => {
        const existingIdx = state.legs.findIndex(
          (l) =>
            l.status === "OPEN" &&
            l.contract_id === leg.contract_id &&
            l.side === leg.side
        );
        if (existingIdx >= 0) {
          const next = [...state.legs];
          const cur = next[existingIdx];
          const totalLots = cur.lots + leg.lots;
          const weightedEntry =
            (cur.entry_price * cur.lots + leg.entry_price * leg.lots) / totalLots;
          next[existingIdx] = {
            ...cur,
            lots: totalLots,
            entry_price: round2(weightedEntry),
            enabled: true,
          };
          return { legs: next };
        }
        return { legs: [...state.legs, leg] };
      });
      void useMarketStore.getState().refreshActiveLegQuotes([leg.contract_id]);
    },

    replaceWithLegs: (legs, strategyName) => {
      set((state) => ({
        strategyId: null,
        strategyName: strategyName ?? state.strategyName,
        legs,
        closedLegs: [],
        realizedPnl: 0,
        lastExecutionNotice: null,
      }));
      const cids = legs.map((l) => l.contract_id);
      if (cids.length > 0) {
        void useMarketStore.getState().refreshActiveLegQuotes(cids);
      }
    },

    toggleLegEnabled: (legId) =>
      set((state) => ({
        legs: state.legs.map((l) =>
          l.leg_id === legId ? { ...l, enabled: !l.enabled } : l
        ),
      })),

    flipLegSide: (legId) =>
      set((state) => ({
        legs: state.legs.map((l) =>
          l.leg_id === legId
            ? { ...l, side: (l.side === "BUY" ? "SELL" : "BUY") as OptionSide }
            : l
        ),
      })),

    updateLegLots: (legId, lots) => {
      const safeLots = Math.max(1, Math.floor(lots));
      set((state) => ({
        legs: state.legs.map((l) =>
          l.leg_id === legId ? { ...l, lots: safeLots } : l
        ),
      }));
    },

    removeLeg: (legId) =>
      set((state) => ({
        legs: state.legs.filter((l) => l.leg_id !== legId),
      })),

    partialExitLeg: async (legId, lotsToExit, exitPriceOverride) => {
      const state = get();
      const leg = state.legs.find((l) => l.leg_id === legId);
      if (!leg || lotsToExit < 1) return;

      const mult = Math.max(1, state.lotMultiplier);
      const effectiveOpenLots = leg.lots * mult;
      const clampedExitLots = Math.min(effectiveOpenLots, Math.floor(lotsToExit));
      const market = useMarketStore.getState();
      const liveQuote = market.activeLegQuotes[leg.contract_id];
      const closingSide: OptionSide = leg.side === "BUY" ? "SELL" : "BUY";

      set({ isExecuting: true });
      try {
        const res = await executeOrders({
          strategy_id: state.strategyId,
          trading_mode: "SIMULATOR",
          action: clampedExitLots === effectiveOpenLots ? "SQUARE_OFF_ALL" : "PARTIAL_EXIT",
          slice_if_frozen: true,
          as_of: market.asOfIso || null,
          legs: [
            {
              leg_id: leg.leg_id,
              contract_id: leg.contract_id,
              side: closingSide,
              lots: clampedExitLots,
              lot_size: leg.lot_size,
              limit_price:
                exitPriceOverride !== undefined
                  ? String(exitPriceOverride)
                  : liveQuote
                    ? String(liveQuote.ltp)
                    : String(leg.entry_price),
              entry_price: String(leg.entry_price),
            },
          ],
        });

        const fillPx = Number(res.fills[0]?.fill_price ?? liveQuote?.ltp ?? leg.entry_price);
        const delta = Number(res.realized_pnl_delta);

        const closedRecord: ClosedLegRecord = {
          leg_id: leg.leg_id,
          contract_id: leg.contract_id,
          symbol: leg.symbol as IndexSymbol,
          expiry: leg.expiry,
          strike: leg.strike ?? null,
          option_type: leg.option_type,
          side: leg.side,
          lots_closed: clampedExitLots,
          lot_size: leg.lot_size,
          entry_price: leg.entry_price,
          exit_price: fillPx,
          realized_pnl: delta,
          closed_at: res.fills[0]?.executed_at ?? new Date().toISOString(),
        };

        set((cur) => {
          const remainingEffective = effectiveOpenLots - clampedExitLots;
          let nextMultiplier = cur.lotMultiplier;
          let nextLegs: StrategyLeg[];

          if (remainingEffective <= 0) {
            nextLegs = cur.legs.filter((l) => l.leg_id !== legId);
          } else if (remainingEffective % mult === 0) {
            nextLegs = cur.legs.map((l) =>
              l.leg_id === legId ? { ...l, lots: remainingEffective / mult } : l
            );
          } else {
            // Normalize all open legs to base 1x when partial exit splits a multiplied block unevenly
            nextMultiplier = 1;
            nextLegs = cur.legs.map((l) =>
              l.leg_id === legId
                ? { ...l, lots: remainingEffective }
                : { ...l, lots: l.lots * mult }
            );
          }

          return {
            legs: nextLegs,
            lotMultiplier: nextMultiplier,
            closedLegs: [closedRecord, ...cur.closedLegs],
            realizedPnl: round2(cur.realizedPnl + delta),
            isExecuting: false,
            lastExecutionNotice: `Exited ${clampedExitLots} lot(s) @ ₹${fillPx.toFixed(2)} (${delta >= 0 ? "+" : ""}₹${delta.toFixed(2)})`,
          };
        });
      } catch (err) {
        set({
          isExecuting: false,
          lastExecutionNotice:
            err instanceof Error ? `Exit failed: ${err.message}` : "Partial exit failed",
        });
      }
    },

    squareOffAll: async () => {
      const state = get();
      const mult = Math.max(1, state.lotMultiplier);
      const openLegs = state.legs.filter((l) => l.status === "OPEN" && l.enabled);
      if (openLegs.length === 0) return;

      const market = useMarketStore.getState();
      set({ isExecuting: true });
      try {
        const res = await executeOrders({
          strategy_id: state.strategyId,
          trading_mode: "SIMULATOR",
          action: "SQUARE_OFF_ALL",
          slice_if_frozen: true,
          as_of: market.asOfIso || null,
          legs: openLegs.map((leg) => {
            const q = market.activeLegQuotes[leg.contract_id];
            return {
              leg_id: leg.leg_id,
              contract_id: leg.contract_id,
              side: (leg.side === "BUY" ? "SELL" : "BUY") as OptionSide,
              lots: leg.lots * mult,
              lot_size: leg.lot_size,
              limit_price: q ? String(q.ltp) : String(leg.entry_price),
              entry_price: String(leg.entry_price),
            };
          }),
        });

        const delta = Number(res.realized_pnl_delta);
        const nowIso = new Date().toISOString();
        const newClosed: ClosedLegRecord[] = openLegs.map((leg) => {
          const fill = res.fills.find((f) => f.contract_id === leg.contract_id);
          const exitPx = Number(
            fill?.fill_price ?? market.activeLegQuotes[leg.contract_id]?.ltp ?? leg.entry_price
          );
          const effLots = leg.lots * mult;
          const qty = effLots * leg.lot_size;
          const legPnl =
            leg.side === "BUY"
              ? (exitPx - leg.entry_price) * qty
              : (leg.entry_price - exitPx) * qty;
          return {
            leg_id: leg.leg_id,
            contract_id: leg.contract_id,
            symbol: leg.symbol as IndexSymbol,
            expiry: leg.expiry,
            strike: leg.strike ?? null,
            option_type: leg.option_type,
            side: leg.side,
            lots_closed: effLots,
            lot_size: leg.lot_size,
            entry_price: leg.entry_price,
            exit_price: exitPx,
            realized_pnl: round2(legPnl),
            closed_at: fill?.executed_at ?? nowIso,
          };
        });

        set((cur) => ({
          legs: [],
          lotMultiplier: 1,
          closedLegs: [...newClosed, ...cur.closedLegs],
          realizedPnl: round2(cur.realizedPnl + delta),
          isExecuting: false,
          margin: null,
          lastExecutionNotice: `Squared off ${openLegs.length} leg(s) · Realized ${delta >= 0 ? "+" : ""}₹${delta.toFixed(2)}`,
        }));
      } catch (err) {
        set({
          isExecuting: false,
          lastExecutionNotice:
            err instanceof Error ? `Square-off failed: ${err.message}` : "Square-off failed",
        });
      }
    },

    clearStrategy: () =>
      set({
        strategyId: null,
        strategyName: "Untitled Strategy",
        legs: [],
        closedLegs: [],
        realizedPnl: 0,
        lotMultiplier: 1,
        margin: null,
        lastExecutionNotice: null,
      }),

    applySettledLegs: (events, realizedDelta) => {
      if (events.length === 0) return;
      const settledIds = new Set(events.map((e) => e.leg_id));
      const newClosed: ClosedLegRecord[] = events.map((ev) => ({
        leg_id: ev.leg_id,
        contract_id: ev.contract_id,
        symbol: ev.symbol,
        expiry: ev.expiry,
        strike: ev.strike ?? null,
        option_type: ev.option_type,
        side: ev.side,
        lots_closed: ev.lots_settled,
        lot_size: ev.lot_size,
        entry_price: ev.entry_price,
        exit_price: ev.settlement_price,
        realized_pnl: ev.realized_pnl,
        closed_at: ev.settled_at,
      }));
      set((cur) => ({
        legs: cur.legs.filter((l) => !settledIds.has(l.leg_id)),
        closedLegs: [...newClosed, ...cur.closedLegs],
        realizedPnl: round2(cur.realizedPnl + realizedDelta),
        lotMultiplier: cur.legs.every((l) => settledIds.has(l.leg_id)) ? 1 : cur.lotMultiplier,
        lastExecutionNotice: `Auto-settled ${events.length} expired leg(s) at 15:30 IST · Realized ${realizedDelta >= 0 ? "+" : ""}₹${realizedDelta.toFixed(2)}`,
      }));
    },

    loadSavedStrategy: (saved) => {
      const metaMult = Number(
        (saved.metadata as Record<string, unknown> | undefined)?.lot_multiplier ?? 1
      );
      set({
        strategyId: saved.id,
        strategyName: saved.name,
        legs: saved.legs ?? [],
        closedLegs: saved.closed_legs ?? [],
        realizedPnl: Number(saved.realized_pnl ?? 0),
        lotMultiplier: Number.isFinite(metaMult) && metaMult >= 1 ? Math.floor(metaMult) : 1,
        lastExecutionNotice: `Loaded "${saved.name}"`,
      });
      const cids = (saved.legs ?? []).map((l) => l.contract_id);
      if (cids.length > 0) {
        void useMarketStore.getState().refreshActiveLegQuotes(cids);
      }
    },
  }))
);
