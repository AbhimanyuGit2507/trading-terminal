"use client";

import { Activity, BookMarked, History, Moon, Radio, Sun } from "lucide-react";
import type { IndexSymbol } from "@/lib/api/types";
import { useMarketStore } from "@/stores/marketStore";
import { useSimulatorStore } from "@/stores/simulatorStore";
import { useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";

const SYMBOLS: IndexSymbol[] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"];

export function TopBar() {
  const symbol = useMarketStore((s) => s.symbol);
  const expiries = useMarketStore((s) => s.expiries);
  const selectedChainExpiry = useMarketStore((s) => s.selectedChainExpiry);
  const spot = useMarketStore((s) => s.spot);
  const futuresPrice = useMarketStore((s) => s.futuresPrice);
  const indiaVix = useMarketStore((s) => s.indiaVix);
  const lotSize = useMarketStore((s) => s.lotSize);
  const wsStatus = useMarketStore((s) => s.wsStatus);
  const loadChain = useMarketStore((s) => s.loadChain);

  const mode = useSimulatorStore((s) => s.mode);
  const setMode = useSimulatorStore((s) => s.setMode);
  const simDatetimeIso = useSimulatorStore((s) => s.simDatetimeIso);
  const loadAvailableDates = useSimulatorStore((s) => s.loadAvailableDates);
  const jumpToDateTime = useSimulatorStore((s) => s.jumpToDateTime);

  const resetWhatIf = useStrategyStore((s) => s.resetWhatIf);
  const setActiveDrawer = useUiStore((s) => s.setActiveDrawer);
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);

  const handleSymbolChange = async (nextSym: IndexSymbol) => {
    if (nextSym === symbol) return;
    if (mode === "simulator") {
      useMarketStore.setState({ symbol: nextSym });
      const dates = await loadAvailableDates(nextSym);
      const targetIso =
        dates.length > 0
          ? `${dates[dates.length - 1]}T09:20:00+05:30`
          : simDatetimeIso || new Date().toISOString();
      await jumpToDateTime(targetIso);
      return;
    }
    const snap = await loadChain(nextSym, undefined, undefined);
    resetWhatIf(snap.spot, snap.as_of);
  };

  const handleExpiryChange = async (nextExpiry: string) => {
    const asOf = mode === "simulator" && simDatetimeIso ? simDatetimeIso : undefined;
    if (mode === "simulator" && asOf) {
      useMarketStore.setState({ selectedChainExpiry: nextExpiry });
      await jumpToDateTime(asOf);
      return;
    }
    await loadChain(symbol, nextExpiry, asOf);
  };

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-[#0d131f]/95">
      <div className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        {/* Brand + Index Pills */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 border-r border-slate-200 pr-2 dark:border-slate-800">
            <div className="flex h-7 w-7 items-center justify-center rounded-md border border-blue-200 bg-blue-50 text-blue-600 dark:border-blue-500/30 dark:bg-blue-600/20 dark:text-blue-400">
              <Activity className="h-4 w-4" />
            </div>
            <div>
              <span className="text-sm font-bold tracking-tight text-slate-900 dark:text-slate-100">
                StockMock
              </span>
              <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                F&amp;O
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-100 p-0.5 dark:border-slate-800 dark:bg-slate-900">
            {SYMBOLS.map((sym) => {
              const active = sym === symbol;
              return (
                <button
                  key={sym}
                  type="button"
                  onClick={() => void handleSymbolChange(sym)}
                  className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                    active
                      ? "bg-blue-600 text-white shadow-sm"
                      : "text-slate-600 hover:bg-white hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-200"
                  }`}
                >
                  {sym}
                </button>
              );
            })}
          </div>

          {/* Chain Expiry Selector */}
          <div className="flex items-center gap-1.5">
            <label
              htmlFor="chain-expiry-select"
              className="text-[11px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400"
            >
              Expiry
            </label>
            <select
              id="chain-expiry-select"
              value={selectedChainExpiry}
              onChange={(e) => void handleExpiryChange(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              {expiries.map((exp) => (
                <option key={exp.expiry_date} value={exp.expiry_date}>
                  {exp.label} · {exp.dte} DTE
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Live Spot / Futures / VIX Ticker */}
        <div className="flex flex-wrap items-center gap-4 text-xs tabular-nums">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] font-medium uppercase text-slate-500 dark:text-slate-400">
              Spot
            </span>
            <span className="font-mono text-sm font-bold text-slate-900 dark:text-slate-100">
              {spot.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] font-medium uppercase text-slate-500 dark:text-slate-400">
              Fut
            </span>
            <span className="font-mono text-sm font-bold text-blue-600 dark:text-sky-400">
              {futuresPrice.toLocaleString("en-IN", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] font-medium uppercase text-slate-500 dark:text-slate-400">
              VIX
            </span>
            <span className="font-mono text-sm font-bold text-amber-600 dark:text-amber-400">
              {indiaVix.toFixed(2)}
            </span>
          </div>
          <div className="hidden items-baseline gap-1 rounded border border-slate-200 bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 sm:flex dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300">
            <span>Lot:</span>
            <span className="font-mono font-semibold text-slate-900 dark:text-white">
              {lotSize}
            </span>
          </div>
        </div>

        {/* Mode Toggle + Drawers + Theme Toggle + Stream Indicator */}
        <div className="flex items-center gap-2">
          <div
            className="flex items-center rounded-lg border border-slate-200 bg-slate-100 p-0.5 dark:border-slate-800 dark:bg-slate-900"
            role="group"
            aria-label="Trading Workspace Mode"
          >
            <button
              type="button"
              onClick={() => setMode("builder")}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                mode === "builder"
                  ? "bg-emerald-600 text-white shadow-sm"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              Builder
            </button>
            <button
              type="button"
              onClick={() => setMode("simulator")}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                mode === "simulator"
                  ? "bg-violet-600 text-white shadow-sm"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              Simulator
            </button>
          </div>

          <button
            type="button"
            onClick={() => setActiveDrawer("strategies")}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <BookMarked className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" />
            <span>Saved</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveDrawer("orders")}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <History className="h-3.5 w-3.5 text-slate-500 dark:text-slate-400" />
            <span>Orders</span>
          </button>

          <button
            type="button"
            onClick={toggleTheme}
            aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
            title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
            className="inline-flex items-center justify-center rounded-md border border-slate-300 bg-white p-1.5 text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {theme === "light" ? (
              <Moon className="h-3.5 w-3.5 text-slate-700" />
            ) : (
              <Sun className="h-3.5 w-3.5 text-amber-400" />
            )}
          </button>

          <div
            title={`WebSocket stream: ${wsStatus}`}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${
              wsStatus === "connected"
                ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-400"
                : wsStatus === "connecting"
                  ? "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400"
                  : "border-slate-300 bg-slate-100 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400"
            }`}
          >
            <Radio className="h-3 w-3" />
            <span className="hidden md:inline">
              {wsStatus === "connected"
                ? "Live Feed"
                : wsStatus === "connecting"
                  ? "Syncing"
                  : "Mock"}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
