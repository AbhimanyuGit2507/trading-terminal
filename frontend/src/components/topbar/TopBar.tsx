"use client";

import { Activity, BookMarked, History, Radio } from "lucide-react";
import { useMarketStore } from "@/stores/marketStore";
import { useSimulatorStore } from "@/stores/simulatorStore";
import { useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";
import type { IndexSymbol } from "@/lib/api/types";

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

  const resetWhatIf = useStrategyStore((s) => s.resetWhatIf);
  const setActiveDrawer = useUiStore((s) => s.setActiveDrawer);

  const handleSymbolChange = async (nextSym: IndexSymbol) => {
    if (nextSym === symbol) return;
    const asOf = mode === "simulator" && simDatetimeIso ? simDatetimeIso : undefined;
    const snap = await loadChain(nextSym, undefined, asOf);
    resetWhatIf(snap.spot, snap.as_of);
  };

  const handleExpiryChange = async (nextExpiry: string) => {
    const asOf = mode === "simulator" && simDatetimeIso ? simDatetimeIso : undefined;
    await loadChain(symbol, nextExpiry, asOf);
  };

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-[#0d131f]/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        {/* Brand + Index Pills */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 pr-2 border-r border-slate-800">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-600/20 text-blue-400 border border-blue-500/30">
              <Activity className="h-4 w-4" />
            </div>
            <div>
              <span className="text-sm font-semibold tracking-tight text-slate-100">
                StockMock
              </span>
              <span className="ml-1.5 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium uppercase text-slate-400">
                F&amp;O
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1 rounded-lg bg-slate-900 p-0.5 border border-slate-800">
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
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/70"
                  }`}
                >
                  {sym}
                </button>
              );
            })}
          </div>

          {/* Chain Expiry Selector */}
          <div className="flex items-center gap-1.5">
            <label htmlFor="chain-expiry-select" className="text-[11px] uppercase tracking-wider text-slate-400">
              Expiry
            </label>
            <select
              id="chain-expiry-select"
              value={selectedChainExpiry}
              onChange={(e) => void handleExpiryChange(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-100 focus:border-blue-500 focus:outline-none"
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
            <span className="text-[11px] uppercase text-slate-400">Spot</span>
            <span className="font-mono text-sm font-semibold text-slate-100">
              {spot.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] uppercase text-slate-400">Fut</span>
            <span className="font-mono text-sm font-semibold text-sky-400">
              {futuresPrice.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] uppercase text-slate-400">VIX</span>
            <span className="font-mono text-sm font-semibold text-amber-400">
              {indiaVix.toFixed(2)}
            </span>
          </div>
          <div className="hidden sm:flex items-baseline gap-1 rounded bg-slate-800/80 px-2 py-0.5 text-[11px] text-slate-300">
            <span>Lot:</span>
            <span className="font-mono font-semibold text-white">{lotSize}</span>
          </div>
        </div>

        {/* Mode Toggle + Drawers + Stream Indicator */}
        <div className="flex items-center gap-2">
          <div
            className="flex items-center rounded-lg border border-slate-800 bg-slate-900 p-0.5"
            role="group"
            aria-label="Trading Workspace Mode"
          >
            <button
              type="button"
              onClick={() => setMode("builder")}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                mode === "builder"
                  ? "bg-emerald-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Builder
            </button>
            <button
              type="button"
              onClick={() => setMode("simulator")}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                mode === "simulator"
                  ? "bg-violet-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Simulator
            </button>
          </div>

          <button
            type="button"
            onClick={() => setActiveDrawer("strategies")}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-200 hover:bg-slate-800"
          >
            <BookMarked className="h-3.5 w-3.5 text-blue-400" />
            <span>Saved</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveDrawer("orders")}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-200 hover:bg-slate-800"
          >
            <History className="h-3.5 w-3.5 text-slate-400" />
            <span>Orders</span>
          </button>

          <div
            title={`WebSocket stream: ${wsStatus}`}
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium border ${
              wsStatus === "connected"
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                : wsStatus === "connecting"
                  ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                  : "border-slate-700 bg-slate-800 text-slate-400"
            }`}
          >
            <Radio className="h-3 w-3" />
            <span className="hidden md:inline">
              {wsStatus === "connected" ? "Live Feed" : wsStatus === "connecting" ? "Syncing" : "Mock"}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}

