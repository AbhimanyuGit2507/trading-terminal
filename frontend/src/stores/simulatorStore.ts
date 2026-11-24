import { create } from "zustand";
import { stepSimulator } from "@/lib/api/client";
import type { SimulatorStepSize } from "@/lib/api/types";
import { useMarketStore } from "./marketStore";
import { useStrategyStore } from "./strategyStore";

export type AppMode = "builder" | "simulator";
export type PlaybackSpeed = 1 | 2 | 5 | 10;

export interface SimulatorState {
  mode: AppMode;
  simDatetimeIso: string;
  isPlaying: boolean;
  playbackSpeed: PlaybackSpeed;
  autoStepSize: SimulatorStepSize;
  isStepping: boolean;
  error: string | null;

  setMode: (mode: AppMode) => void;
  setSimDatetimeIso: (iso: string) => void;
  setPlaybackSpeed: (speed: PlaybackSpeed) => void;
  setAutoStepSize: (step: SimulatorStepSize) => void;
  togglePlay: () => void;
  stopPlay: () => void;
  stepTime: (step: SimulatorStepSize) => Promise<void>;
}

export const useSimulatorStore = create<SimulatorState>((set, get) => ({
  mode: "builder",
  simDatetimeIso: "",
  isPlaying: false,
  playbackSpeed: 1,
  autoStepSize: "+5m",
  isStepping: false,
  error: null,

  setMode: (mode) => {
    const m = useMarketStore.getState();
    set({
      mode,
      isPlaying: false,
      simDatetimeIso: get().simDatetimeIso || m.asOfIso || new Date().toISOString(),
    });
  },

  setSimDatetimeIso: (simDatetimeIso) => set({ simDatetimeIso }),
  setPlaybackSpeed: (playbackSpeed) => set({ playbackSpeed }),
  setAutoStepSize: (autoStepSize) => set({ autoStepSize }),
  togglePlay: () => set((s) => ({ isPlaying: !s.isPlaying })),
  stopPlay: () => set({ isPlaying: false }),

  stepTime: async (step) => {
    if (get().isStepping) return;
    const market = useMarketStore.getState();
    const strategy = useStrategyStore.getState();
    const curIso = get().simDatetimeIso || market.asOfIso || new Date().toISOString();
    const activeContracts = strategy.legs
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
      });
      market.setSnapshot(res.chain);
      if (res.leg_quotes) {
        market.mergeActiveLegQuotes(res.leg_quotes);
      }
      set({
        simDatetimeIso: res.new_as_of,
        isStepping: false,
      });
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

