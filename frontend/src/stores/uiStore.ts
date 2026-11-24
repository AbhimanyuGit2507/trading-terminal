import { create } from "zustand";

export type ThemeMode = "light" | "dark";
export type PnlUnit = "INR" | "POINTS";
export type DisplayQtyMode = "lots" | "qty";
export type StrikeWindow = 15 | 25 | 999;
export type ActiveDrawer = null | "strategies" | "orders";
export type PayoffRightTab = "graph" | "table" | "greeks";

export interface ChartOverlaysState {
  expiryPayoff: boolean;
  targetMtm: boolean;
  sdBands: boolean;
  oiOverlay: boolean;
}

export type ChartOverlayKey = keyof ChartOverlaysState;

export function applyThemeToDocument(theme: ThemeMode): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta) {
    meta.setAttribute("content", theme);
  }
  try {
    localStorage.setItem("stockmock-theme", theme);
  } catch {
    // ignore storage errors
  }
}

export interface UiState {
  theme: ThemeMode;
  pnlUnit: PnlUnit;
  rightTab: PayoffRightTab;
  chartOverlays: ChartOverlaysState;
  includeCharges: boolean; // OFF by default per Tech Lead decision #2
  displayQtyMode: DisplayQtyMode;
  strikeWindow: StrikeWindow;
  defaultLots: number;
  activeDrawer: ActiveDrawer;
  partialExitLegId: string | null;

  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  hydrateThemeFromStorage: () => void;
  setPnlUnit: (unit: PnlUnit) => void;
  togglePnlUnit: () => void;
  setRightTab: (tab: PayoffRightTab) => void;
  toggleChartOverlay: (key: ChartOverlayKey) => void;
  toggleIncludeCharges: () => void;
  setDisplayQtyMode: (mode: DisplayQtyMode) => void;
  setStrikeWindow: (win: StrikeWindow) => void;
  setDefaultLots: (lots: number) => void;
  setActiveDrawer: (drawer: ActiveDrawer) => void;
  openPartialExitModal: (legId: string | null) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  theme: "light",
  pnlUnit: "INR",
  rightTab: "graph",
  chartOverlays: {
    expiryPayoff: true,
    targetMtm: true,
    sdBands: true,
    oiOverlay: false,
  },
  includeCharges: false,
  displayQtyMode: "lots",
  strikeWindow: 15,
  defaultLots: 1,
  activeDrawer: null,
  partialExitLegId: null,

  setTheme: (theme) => {
    applyThemeToDocument(theme);
    set({ theme });
  },

  toggleTheme: () => {
    const next: ThemeMode = get().theme === "light" ? "dark" : "light";
    applyThemeToDocument(next);
    set({ theme: next });
  },

  hydrateThemeFromStorage: () => {
    if (typeof window === "undefined") return;
    try {
      const stored = localStorage.getItem("stockmock-theme");
      const resolved: ThemeMode =
        stored === "dark" || stored === "light" ? stored : "light";
      applyThemeToDocument(resolved);
      set({ theme: resolved });
    } catch {
      applyThemeToDocument("light");
    }
  },

  setPnlUnit: (pnlUnit) => set({ pnlUnit }),
  togglePnlUnit: () =>
    set((s) => ({ pnlUnit: s.pnlUnit === "INR" ? "POINTS" : "INR" })),
  setRightTab: (rightTab) => set({ rightTab }),
  toggleChartOverlay: (key) =>
    set((s) => ({
      chartOverlays: {
        ...s.chartOverlays,
        [key]: !s.chartOverlays[key],
      },
    })),

  toggleIncludeCharges: () => set((s) => ({ includeCharges: !s.includeCharges })),
  setDisplayQtyMode: (displayQtyMode) => set({ displayQtyMode }),
  setStrikeWindow: (strikeWindow) => set({ strikeWindow }),
  setDefaultLots: (lots) => set({ defaultLots: Math.max(1, Math.floor(lots)) }),
  setActiveDrawer: (activeDrawer) => set({ activeDrawer }),
  openPartialExitModal: (partialExitLegId) => set({ partialExitLegId }),
}));
