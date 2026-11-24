import { create } from "zustand";
import {
  getAvailableSimulatorDates,
  jumpSimulator,
  stepSimulator,
} from "@/lib/api/client";
import type { IndexSymbol, SimulatorStepSize } from "@/lib/api/types";
import { useMarketStore } from "./marketStore";
import { getEffectiveLegs, useStrategyStore } from "./strategyStore";

export type AppMode = "builder" | "simulator";
export type PlaybackSpeed = 1 | 2 | 5 | 10;

export interface SimulatorState {
  mode: AppMode;
  simDatetimeIso: string;
  availableDates: string[];
  expiryDates: string[];
  dataSource: "parquet" | "mock_fallback";
  endOfData: boolean;
  isPlaying: boolean;
  playbackSpeed: PlaybackSpeed;
  autoStepSize: SimulatorStepSize;
  isStepping: boolean;
  isLoadingDates: boolean;
  error: string | null;

  setMode: (mode: AppMode) => Promise<void>;
  setSimDatetimeIso: (iso: string) => void;
  setPlaybackSpeed: (speed: PlaybackSpeed) => void;
  setAutoStepSize: (step: SimulatorStepSize) => void;
  togglePlay: () => void;
  stopPlay: () => void;
  loadAvailableDates: (symbol: IndexSymbol) => Promise<string[]>;
  jumpToDateTime: (targetIso: string) => Promise<void>;
  stepTime: (step: SimulatorStepSize) => Promise<void>;
}

export const useSimulatorStore = create<SimulatorState>((set, get) => ({
  mode: "builder",
  simDatetimeIso: "",
  availableDates: [],
  expiryDates: [],
  dataSource: "parquet",
  endOfData: false,
  isPlaying: false,
  playbackSpeed: 1,
  autoStepSize: "+5m",
  isStepping: false,
  isLoadingDates: false,
  error: null,

  setMode: async (nextMode) => {
    const prevMode = get().mode;
    if (prevMode === nextMode) return;

    useStrategyStore.getState().switchWorkspaceMode(prevMode, nextMode);
    set({ mode: nextMode, isPlaying: false, endOfData: false, error: null });

    const market = useMarketStore.getState();
    if (nextMode === "simulator") {
      const dates = await get().loadAvailableDates(market.symbol);
      const preferredDate =
        get().expiryDates[get().expiryDates.length - 1] ??
        dates[dates.length - 1];
      const targetIso = preferredDate
        ? `${preferredDate}T09:20:00+05:30`
        : get().simDatetimeIso || market.asOfIso || new Date().toISOString();
      await get().jumpToDateTime(targetIso);
    } else {
      try {
        const snap = await market.loadChain(market.symbol);
        useStrategyStore.getState().resetWhatIf(snap.spot, snap.as_of);
      } catch {
        // non-fatal if offline
      }
    }
  },

  setSimDatetimeIso: (simDatetimeIso) => set({ simDatetimeIso }),
  setPlaybackSpeed: (playbackSpeed) => set({ playbackSpeed }),
  setAutoStepSize: (autoStepSize) => set({ autoStepSize }),
  togglePlay: () => set((s) => ({ isPlaying: !s.isPlaying })),
  stopPlay: () => set({ isPlaying: false }),

  loadAvailableDates: async (symbol) => {
    set({ isLoadingDates: true });
    try {
      const res = await getAvailableSimulatorDates(symbol);
      set({
        availableDates: res.dates,
        expiryDates: res.expiry_dates,
        dataSource: res.data_source,
        isLoadingDates: false,
      });
      return res.dates;
    } catch {
      set({ isLoadingDates: false });
      return [];
    }
  },

  jumpToDateTime: async (targetIso) => {
    const market = useMarketStore.getState();
    const strategy = useStrategyStore.getState();
    const effectiveLegs = getEffectiveLegs(strategy.legs, strategy.lotMultiplier);
    const activeContracts = effectiveLegs
      .filter((l) => l.status === "OPEN")
      .map((l) => l.contract_id);

    set({ isStepping: true, isPlaying: false, error: null });
    try {
      const res = await jumpSimulator({
        symbol: market.symbol,
        target_dt: targetIso,
        chain_expiry: market.selectedChainExpiry || null,
        active_contracts: activeContracts,
        open_legs: effectiveLegs,
      });
      market.setSnapshot(res.chain);
      if (res.leg_quotes) {
        market.mergeActiveLegQuotes(res.leg_quotes);
      }
      set({
        simDatetimeIso: res.new_as_of,
        dataSource: res.data_source,
        endOfData: res.end_of_data,
        isStepping: false,
      });
      strategy.setWhatIf({
        targetSpot: res.chain.spot,
        targetDatetimeIso: res.new_as_of,
      });
    } catch (err) {
      set({
        isStepping: false,
        error: err instanceof Error ? err.message : "Simulator jump failed",
      });
    }
  },

  stepTime: async (step) => {
    if (get().isStepping) return;
    const market = useMarketStore.getState();
    const strategy = useStrategyStore.getState();
    const curIso = get().simDatetimeIso || market.asOfIso || new Date().toISOString();
    const effectiveLegs = getEffectiveLegs(strategy.legs, strategy.lotMultiplier);
    const activeContracts = effectiveLegs
      .filter((l) => l.status === "OPEN")
      .map((l) => l.contract_id);

    set({ isStepping: true, error: null });
    try {
      const res = await stepSimulator({
        symbol: market.symbol,
        current_as_of: curIso,
        step,
        chain_expiry: market.selectedChainExpiry || null,
        active_contracts: activeContracts,
        open_legs: effectiveLegs,
      });
      market.setSnapshot(res.chain);
      if (res.leg_quotes) {
        market.mergeActiveLegQuotes(res.leg_quotes);
      }
      if (res.settled_legs && res.settled_legs.length > 0) {
        strategy.applySettledLegs(res.settled_legs, Number(res.realized_pnl_delta ?? 0));
      }
      const shouldPause =
        Boolean(res.end_of_data) || (res.settled_legs?.length ?? 0) > 0;
      set((s) => ({
        simDatetimeIso: res.new_as_of,
        dataSource: res.data_source,
        endOfData: res.end_of_data,
        isPlaying: shouldPause ? false : s.isPlaying,
        isStepping: false,
      }));
      strategy.setWhatIf({
        targetSpot: res.chain.spot,
        targetDatetimeIso: res.new_as_of,
      });
    } catch (err) {
      set({
        isStepping: false,
        isPlaying: false,
        error: err instanceof Error ? err.message : "Simulator step failed",
      });
    }
  },
}));
