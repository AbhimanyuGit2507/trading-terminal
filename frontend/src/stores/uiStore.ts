import { create } from "zustand";

export type DisplayQtyMode = "lots" | "qty";
export type StrikeWindow = 15 | 25 | 999;
export type ActiveDrawer = null | "strategies" | "orders";

export interface UiState {
  includeCharges: boolean; // OFF by default per Tech Lead decision #2
  displayQtyMode: DisplayQtyMode;
  strikeWindow: StrikeWindow;
  defaultLots: number;
  activeDrawer: ActiveDrawer;
  partialExitLegId: string | null;

  toggleIncludeCharges: () => void;
  setDisplayQtyMode: (mode: DisplayQtyMode) => void;
  setStrikeWindow: (win: StrikeWindow) => void;
  setDefaultLots: (lots: number) => void;
  setActiveDrawer: (drawer: ActiveDrawer) => void;
  openPartialExitModal: (legId: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  includeCharges: false,
  displayQtyMode: "lots",
  strikeWindow: 15,
  defaultLots: 1,
  activeDrawer: null,
  partialExitLegId: null,

  toggleIncludeCharges: () => set((s) => ({ includeCharges: !s.includeCharges })),
  setDisplayQtyMode: (displayQtyMode) => set({ displayQtyMode }),
  setStrikeWindow: (strikeWindow) => set({ strikeWindow }),
  setDefaultLots: (lots) => set({ defaultLots: Math.max(1, Math.floor(lots)) }),
  setActiveDrawer: (activeDrawer) => set({ activeDrawer }),
  openPartialExitModal: (partialExitLegId) => set({ partialExitLegId }),
}));

