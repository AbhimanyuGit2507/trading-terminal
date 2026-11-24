"use client";

import { Activity, BookMarked, History, LockOpen, Moon, OctagonAlert, Radio, Sun } from "lucide-react";
import type { ExecutionMode, IndexSymbol } from "@/lib/api/types";
import { formatDhanPill } from "@/lib/dhanStatus";
import { useMarketStore } from "@/stores/marketStore";
import { useRiskStore } from "@/stores/riskStore";
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
  const feedStatus = useMarketStore((s) => s.feedStatus);
  const dhanStatus = useMarketStore((s) => s.dhanStatus);
  const loadChain = useMarketStore((s) => s.loadChain);

  const mode = useSimulatorStore((s) => s.mode);
  const setMode = useSimulatorStore((s) => s.setMode);
  const simDatetimeIso = useSimulatorStore((s) => s.simDatetimeIso);
  const loadAvailableDates = useSimulatorStore((s) => s.loadAvailableDates);
  const jumpToDateTime = useSimulatorStore((s) => s.jumpToDateTime);

  const resetWhatIf = useStrategyStore((s) => s.resetWhatIf);
  const setLastExecutionNotice = useStrategyStore((s) => s.setLastExecutionNotice);
  const setActiveDrawer = useUiStore((s) => s.setActiveDrawer);
  const setLiveModeConfirmOpen = useUiStore((s) => s.setLiveModeConfirmOpen);
  const setKillUnlockModalOpen = useUiStore((s) => s.setKillUnlockModalOpen);
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);

  const executionMode = useRiskStore((s) => s.executionMode);
  const riskState = useRiskStore((s) => s.riskState);
  const isKillArmed = useRiskStore((s) => s.isKillArmed);
  const isTriggeringKill = useRiskStore((s) => s.isTriggeringKill);
  const requestModeSwitch = useRiskStore((s) => s.requestModeSwitch);
  const setExecutionModeLocal = useRiskStore((s) => s.setExecutionModeLocal);
  const armOrTriggerKillSwitch = useRiskStore((s) => s.armOrTriggerKillSwitch);

  const displayedMode: ExecutionMode =
    mode === "simulator" ? "SIMULATOR" : executionMode;

  const handleModeClick = async (next: ExecutionMode) => {
    if (next === "DHAN_LIVE") {
      setLiveModeConfirmOpen(true);
      return;
    }
    const res = await requestModeSwitch(next, false);
    if (!res.ok) {
      if (next === "SIMULATOR" || next === "PAPER_LIVE") {
        setExecutionModeLocal(next);
        await setMode(next === "SIMULATOR" ? "simulator" : "builder");
      } else {
        setLastExecutionNotice(res.error ?? "Connect DhanHQ token before switching to Sandbox");
        setActiveDrawer("dhan");
      }
    }
  };

  const handleKillSwitchClick = async () => {
    const res = await armOrTriggerKillSwitch("Manual KILL SWITCH clicked from TopBar");
    if (res.triggered) {
      setLastExecutionNotice(
        `KILL SWITCH EXECUTED: Cancelled ${res.triggered.cancelled_orders} order(s), exited ${res.triggered.exited_positions} position batch(es), ${res.triggered.fallback_exits} fallback market exit(s).`
      );
    } else if (res.error) {
      setLastExecutionNotice(`Kill switch error: ${res.error}`);
    }
  };

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

        {/* 4-Mode Switcher + Kill Switch + Drawers + Theme Toggle + Stream Indicator */}
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="flex items-center rounded-lg border border-slate-200 bg-slate-100 p-0.5 dark:border-slate-800 dark:bg-slate-900"
            role="group"
            aria-label="Trading Workspace Mode"
          >
            {(
              [
                { key: "SIMULATOR", label: "Simulator", activeCls: "bg-slate-700 text-white shadow-sm" },
                { key: "PAPER_LIVE", label: "Paper Live", activeCls: "bg-blue-600 text-white shadow-sm" },
                { key: "DHAN_SANDBOX", label: "Dhan Sandbox", activeCls: "bg-amber-600 text-white shadow-sm" },
                { key: "DHAN_LIVE", label: "Dhan Live", activeCls: "bg-rose-600 text-white shadow-sm" },
              ] as const
            ).map((opt) => {
              const active = displayedMode === opt.key;
              return (
                <button
                  key={opt.key}
                  type="button"
                  onClick={() => void handleModeClick(opt.key)}
                  className={`rounded-md px-2 py-1 text-[11px] font-semibold transition-colors ${
                    active
                      ? opt.activeCls
                      : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
                  }`}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>

          {(displayedMode === "DHAN_SANDBOX" ||
            displayedMode === "DHAN_LIVE" ||
            riskState?.daily_kill_switch_active) &&
            (riskState?.daily_kill_switch_active ? (
              <button
                type="button"
                onClick={() => setKillUnlockModalOpen(true)}
                className="inline-flex animate-pulse items-center gap-1.5 rounded-md border border-rose-500 bg-rose-700 px-2.5 py-1 text-[11px] font-bold text-white shadow-sm hover:bg-rose-600"
              >
                <LockOpen className="h-3.5 w-3.5" />
                <span>KILL SWITCH ACTIVE — UNLOCK</span>
              </button>
            ) : (
              <button
                type="button"
                disabled={isTriggeringKill}
                onClick={() => void handleKillSwitchClick()}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-bold shadow-sm transition-colors ${
                  isKillArmed
                    ? "animate-pulse border-rose-700 bg-rose-600 text-white"
                    : "border-rose-400 bg-rose-50 text-rose-700 hover:bg-rose-600 hover:text-white dark:border-rose-500/60 dark:bg-rose-950/40 dark:text-rose-300 dark:hover:bg-rose-600 dark:hover:text-white"
                }`}
              >
                <OctagonAlert className="h-3.5 w-3.5" />
                <span>
                  {isTriggeringKill
                    ? "EXITING ALL…"
                    : isKillArmed
                      ? "Click again to Square Off Everything"
                      : "KILL SWITCH (EXIT ALL)"}
                </span>
              </button>
            ))}

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

          {(() => {
            const pill = formatDhanPill(feedStatus, dhanStatus, wsStatus);
            const toneClass =
              pill.tone === "emerald"
                ? "border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-400 dark:hover:bg-emerald-500/20"
                : pill.tone === "rose"
                  ? "border-rose-300 bg-rose-50 text-rose-700 hover:bg-rose-100 dark:border-rose-500/40 dark:bg-rose-500/15 dark:text-rose-300 dark:hover:bg-rose-500/25"
                  : pill.tone === "amber"
                    ? "border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400 dark:hover:bg-amber-500/20"
                    : "border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700";

            return (
              <button
                type="button"
                onClick={() => setActiveDrawer("dhan")}
                title={pill.title}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors ${toneClass}`}
              >
                <Radio className="h-3 w-3 shrink-0" />
                <span className="hidden md:inline">{pill.label}</span>
              </button>
            );
          })()}
        </div>
      </div>
    </header>
  );
}
