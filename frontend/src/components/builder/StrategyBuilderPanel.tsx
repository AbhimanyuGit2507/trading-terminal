"use client";

import { useMemo, useState } from "react";
import {
  CheckSquare,
  LogOut,
  Minus,
  Plus,
  Save,
  Send,
  Square,
  Trash2,
  X,
} from "lucide-react";
import {
  createStrategy,
  executeOrders,
  getOptionChain,
  updateStrategy,
} from "@/lib/api/client";
import type { OptionSide } from "@/lib/api/types";
import { formatPnl, formatShortExpiry, formatSignedInr } from "@/lib/format";
import { buildPresetLegs, type PresetKey, STRATEGY_PRESETS } from "@/lib/presets";
import { useMarketStore } from "@/stores/marketStore";
import { useRiskStore } from "@/stores/riskStore";
import { useSimulatorStore } from "@/stores/simulatorStore";
import { getEffectiveLegs, useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";

const MULTIPLIER_PRESETS = [1, 2, 3, 5, 10] as const;

export function StrategyBuilderPanel() {
  const legs = useStrategyStore((s) => s.legs);
  const closedLegs = useStrategyStore((s) => s.closedLegs);
  const realizedPnl = useStrategyStore((s) => s.realizedPnl);
  const lotMultiplier = useStrategyStore((s) => s.lotMultiplier);
  const strategyId = useStrategyStore((s) => s.strategyId);
  const strategyName = useStrategyStore((s) => s.strategyName);
  const isExecuting = useStrategyStore((s) => s.isExecuting);
  const lastExecutionNotice = useStrategyStore((s) => s.lastExecutionNotice);

  const setStrategyName = useStrategyStore((s) => s.setStrategyName);
  const setLotMultiplier = useStrategyStore((s) => s.setLotMultiplier);
  const replaceWithLegs = useStrategyStore((s) => s.replaceWithLegs);
  const toggleLegEnabled = useStrategyStore((s) => s.toggleLegEnabled);
  const flipLegSide = useStrategyStore((s) => s.flipLegSide);
  const updateLegLots = useStrategyStore((s) => s.updateLegLots);
  const updateLegRisk = useStrategyStore((s) => s.updateLegRisk);
  const removeLeg = useStrategyStore((s) => s.removeLeg);
  const squareOffAll = useStrategyStore((s) => s.squareOffAll);
  const clearStrategy = useStrategyStore((s) => s.clearStrategy);
  const loadSavedStrategy = useStrategyStore((s) => s.loadSavedStrategy);
  const setLastExecutionNotice = useStrategyStore((s) => s.setLastExecutionNotice);

  const symbol = useMarketStore((s) => s.symbol);
  const feedStatus = useMarketStore((s) => s.feedStatus);
  const lotSize = useMarketStore((s) => s.lotSize);
  const expiries = useMarketStore((s) => s.expiries);
  const selectedChainExpiry = useMarketStore((s) => s.selectedChainExpiry);
  const asOfIso = useMarketStore((s) => s.asOfIso);
  const activeLegQuotes = useMarketStore((s) => s.activeLegQuotes);
  const getCurrentSnapshot = useMarketStore((s) => s.getCurrentSnapshot);

  const dailyMaxLossLimit = useStrategyStore((s) => s.dailyMaxLossLimit);
  const autoSquareOffOnMaxLoss = useStrategyStore((s) => s.autoSquareOffOnMaxLoss);
  const maxLossTriggered = useStrategyStore((s) => s.maxLossTriggered);
  const setDailyMaxLossLimit = useStrategyStore((s) => s.setDailyMaxLossLimit);
  const setAutoSquareOffOnMaxLoss = useStrategyStore((s) => s.setAutoSquareOffOnMaxLoss);

  const mode = useSimulatorStore((s) => s.mode);
  const executionMode = useRiskStore((s) => s.executionMode);
  const updateRiskLimits = useRiskStore((s) => s.updateRiskLimits);
  const displayQtyMode = useUiStore((s) => s.displayQtyMode);
  const setDisplayQtyMode = useUiStore((s) => s.setDisplayQtyMode);
  const pnlUnit = useUiStore((s) => s.pnlUnit);
  const setPnlUnit = useUiStore((s) => s.setPnlUnit);
  const defaultLots = useUiStore((s) => s.defaultLots);
  const openPartialExitModal = useUiStore((s) => s.openPartialExitModal);
  const setLiveOrderTicketOpen = useUiStore((s) => s.setLiveOrderTicketOpen);

  const [isSaving, setIsSaving] = useState(false);
  const [isApplyingPreset, setIsApplyingPreset] = useState(false);

  const expiryTagByDate = useMemo(() => {
    const map: Record<string, string> = {};
    for (const e of expiries) {
      map[e.expiry_date] = e.is_monthly ? "M" : "W";
    }
    return map;
  }, [expiries]);

  const handleApplyPreset = async (presetKey: PresetKey, label: string) => {
    const snap = getCurrentSnapshot();
    if (!snap) return;
    setIsApplyingPreset(true);
    try {
      let farSnap = null;
      if (presetKey === "calendar_spread") {
        const nextExp = expiries.find((e) => e.expiry_date > selectedChainExpiry);
        if (nextExp) {
          farSnap = await getOptionChain(symbol, nextExp.expiry_date, asOfIso || undefined);
        }
      }
      const presetLegs = buildPresetLegs(presetKey, snap, farSnap, defaultLots);
      replaceWithLegs(presetLegs, `${symbol} ${label}`);
    } finally {
      setIsApplyingPreset(false);
    }
  };

  const handleSaveStrategy = async () => {
    setIsSaving(true);
    try {
      const payload = {
        name: strategyName.trim() || `${symbol} Strategy`,
        symbol,
        mode,
        legs,
        closed_legs: closedLegs,
        realized_pnl: realizedPnl.toFixed(2),
        metadata: { saved_from: "stockmock_ui", lot_multiplier: lotMultiplier },
      };
      const saved = strategyId
        ? await updateStrategy(strategyId, payload)
        : await createStrategy(payload);
      loadSavedStrategy(saved);
      setLastExecutionNotice(`Saved "${saved.name}" to PostgreSQL`);
    } catch (err) {
      setLastExecutionNotice(
        err instanceof Error ? `Save failed: ${err.message}` : "Save failed"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleExecuteVirtualOrder = async () => {
    const openLegs = getEffectiveLegs(
      legs.filter((l) => l.status === "OPEN" && l.enabled),
      lotMultiplier
    );
    if (openLegs.length === 0) return;
    if (mode !== "simulator" && (executionMode === "DHAN_SANDBOX" || executionMode === "DHAN_LIVE")) {
      setLiveOrderTicketOpen(true);
      return;
    }
    try {
      const tradingMode = feedStatus === "LIVE_DHAN" ? "PAPER_LIVE" : "SIMULATOR";
      const res = await executeOrders({
        strategy_id: strategyId,
        trading_mode: tradingMode,
        action: "OPEN_LEGS",
        slice_if_frozen: true,
        as_of: asOfIso || null,
        legs: openLegs.map((leg) => ({
          leg_id: leg.leg_id,
          contract_id: leg.contract_id,
          side: leg.side as OptionSide,
          lots: leg.lots,
          lot_size: leg.lot_size,
          limit_price: String(activeLegQuotes[leg.contract_id]?.ltp ?? leg.entry_price),
        })),
      });
      const childCount = res.fills.filter((f) => !f.is_parent).length;
      setLastExecutionNotice(
        `${tradingMode === "PAPER_LIVE" ? "Paper-Live" : "Virtual"} order filled (${childCount} slice fill${childCount === 1 ? "" : "s"}, key ${res.idempotency_key.slice(0, 8)}…)`
      );
    } catch (err) {
      setLastExecutionNotice(
        err instanceof Error ? `Order failed: ${err.message}` : "Execution failed"
      );
    }
  };

  return (
    <section className="flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-[#111827] dark:shadow-lg">
      {/* Presets Ribbon */}
      <div className="border-b border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-[#0e1523]">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Ready-Made Strategy Presets
          </span>
          <span className="text-[10px] text-slate-400 dark:text-slate-500">
            Click to populate ATM/OTM legs
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {STRATEGY_PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              disabled={isApplyingPreset}
              onClick={() => void handleApplyPreset(p.key, p.label)}
              className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-700 transition-colors hover:border-blue-400 hover:bg-blue-50 hover:text-blue-700 disabled:opacity-50 dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-blue-500/50 dark:hover:bg-blue-600/15 dark:hover:text-blue-200"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Strategy Action Toolbar + Global Lot Multiplier */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 dark:border-slate-800">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            aria-label="Strategy Name"
            value={strategyName}
            onChange={(e) => setStrategyName(e.target.value)}
            className="w-40 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          />
          <button
            type="button"
            disabled={isSaving}
            onClick={() => void handleSaveStrategy()}
            className="inline-flex items-center gap-1 rounded-md border border-blue-300 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50 dark:border-blue-500/40 dark:bg-blue-600/20 dark:text-blue-200 dark:hover:bg-blue-600/35"
          >
            <Save className="h-3.5 w-3.5" />
            <span>{isSaving ? "Saving…" : strategyId ? "Update" : "Save"}</span>
          </button>

          {/* Global Lot Multiplier */}
          <div
            className="flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] dark:border-slate-700 dark:bg-slate-900"
            aria-label="Global Lot Multiplier"
          >
            <span className="pr-0.5 text-[10px] font-semibold uppercase text-slate-500 dark:text-slate-400">
              Mult
            </span>
            {MULTIPLIER_PRESETS.map((factor) => (
              <button
                key={factor}
                type="button"
                onClick={() => setLotMultiplier(factor)}
                className={`rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold transition-colors ${
                  lotMultiplier === factor
                    ? "bg-blue-600 text-white"
                    : "text-slate-600 hover:bg-slate-200 dark:text-slate-400 dark:hover:bg-slate-800"
                }`}
              >
                {factor}x
              </button>
            ))}
            <div className="ml-0.5 flex items-center border-l border-slate-200 pl-1 dark:border-slate-700">
              <button
                type="button"
                aria-label="Decrease multiplier"
                onClick={() => setLotMultiplier(lotMultiplier - 1)}
                className="rounded p-0.5 text-slate-500 hover:bg-slate-200 dark:text-slate-400 dark:hover:bg-slate-800"
              >
                <Minus className="h-2.5 w-2.5" />
              </button>
              <input
                type="number"
                aria-label="Custom lot multiplier"
                min={1}
                value={lotMultiplier}
                onChange={(e) => setLotMultiplier(Number(e.target.value) || 1)}
                className="w-9 bg-transparent text-center font-mono text-[11px] font-semibold text-slate-900 focus:outline-none dark:text-white"
              />
              <button
                type="button"
                aria-label="Increase multiplier"
                onClick={() => setLotMultiplier(lotMultiplier + 1)}
                className="rounded p-0.5 text-slate-500 hover:bg-slate-200 dark:text-slate-400 dark:hover:bg-slate-800"
              >
                <Plus className="h-2.5 w-2.5" />
              </button>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {/* ₹ vs Pts Display Toggle */}
          <div
            className="flex items-center rounded border border-slate-300 bg-slate-100 p-0.5 text-[10px] font-semibold dark:border-slate-700 dark:bg-slate-900"
            role="group"
            aria-label="P&L Display Unit"
          >
            <button
              type="button"
              onClick={() => setPnlUnit("INR")}
              className={`rounded px-1.5 py-0.5 ${
                pnlUnit === "INR"
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                  : "text-slate-500 dark:text-slate-400"
              }`}
            >
              ₹
            </button>
            <button
              type="button"
              onClick={() => setPnlUnit("POINTS")}
              className={`rounded px-1.5 py-0.5 ${
                pnlUnit === "POINTS"
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                  : "text-slate-500 dark:text-slate-400"
              }`}
            >
              Pts
            </button>
          </div>

          <div className="flex items-center rounded border border-slate-300 bg-slate-100 p-0.5 text-[10px] font-semibold dark:border-slate-700 dark:bg-slate-900">
            <button
              type="button"
              onClick={() => setDisplayQtyMode("lots")}
              className={`rounded px-1.5 py-0.5 ${
                displayQtyMode === "lots"
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                  : "text-slate-500 dark:text-slate-400"
              }`}
            >
              Lots
            </button>
            <button
              type="button"
              onClick={() => setDisplayQtyMode("qty")}
              className={`rounded px-1.5 py-0.5 ${
                displayQtyMode === "qty"
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                  : "text-slate-500 dark:text-slate-400"
              }`}
            >
              Qty
            </button>
          </div>

          <div
            className={`flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] ${
              maxLossTriggered
                ? "border-rose-400 bg-rose-50 text-rose-800 dark:border-rose-500/50 dark:bg-rose-950/30 dark:text-rose-200"
                : "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
            }`}
            title="Daily Max-Loss circuit breaker (in INR)"
          >
            <label htmlFor="daily-max-loss-input" className="text-[10px] font-semibold uppercase text-slate-500 dark:text-slate-400">
              Max Loss ₹
            </label>
            <input
              id="daily-max-loss-input"
              type="number"
              min={0}
              step={500}
              placeholder="Off"
              value={dailyMaxLossLimit ?? ""}
              onChange={(e) => {
                const raw = e.target.value.trim();
                const parsed = raw === "" ? null : Number(raw);
                setDailyMaxLossLimit(parsed);
                if (parsed !== null && parsed > 0) {
                  void updateRiskLimits({ daily_max_loss_inr: parsed });
                }
              }}
              className="w-16 bg-transparent font-mono text-[11px] font-semibold text-slate-900 focus:outline-none dark:text-white"
            />
            <label className="inline-flex cursor-pointer items-center gap-1 border-l border-slate-200 pl-1.5 text-[10px] dark:border-slate-700">
              <input
                type="checkbox"
                checked={autoSquareOffOnMaxLoss}
                onChange={(e) => setAutoSquareOffOnMaxLoss(e.target.checked)}
                className="h-3 w-3 rounded border-slate-300 accent-rose-600"
              />
              <span>Auto Sq</span>
            </label>
          </div>

          <button
            type="button"
            disabled={legs.length === 0 || isExecuting}
            onClick={() => void handleExecuteVirtualOrder()}
            className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-40 ${
              mode !== "simulator" && executionMode === "DHAN_LIVE"
                ? "bg-rose-600 hover:bg-rose-500"
                : mode !== "simulator" && executionMode === "DHAN_SANDBOX"
                  ? "bg-amber-600 hover:bg-amber-500"
                  : "bg-emerald-600 hover:bg-emerald-500"
            }`}
          >
            <Send className="h-3 w-3" />
            <span>
              {mode !== "simulator" &&
              (executionMode === "DHAN_LIVE" || executionMode === "DHAN_SANDBOX")
                ? "Execute Strategy"
                : feedStatus === "LIVE_DHAN"
                  ? "Paper Log"
                  : "Log Order"}
            </span>
          </button>

          <button
            type="button"
            disabled={legs.length === 0 || isExecuting}
            onClick={() => void squareOffAll()}
            className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-40 dark:border-amber-500/40 dark:bg-amber-500/15 dark:text-amber-200 dark:hover:bg-amber-500/25"
          >
            <LogOut className="h-3 w-3" />
            <span>Sq. Off</span>
          </button>

          <button
            type="button"
            disabled={legs.length === 0 && closedLegs.length === 0}
            onClick={clearStrategy}
            title="Clear all legs"
            className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:border-red-300 hover:bg-red-50 hover:text-red-700 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-rose-600/20 dark:hover:text-rose-300"
          >
            <Trash2 className="h-3 w-3" />
            <span>Clear</span>
          </button>
        </div>
      </div>

      {/* Notice Banner */}
      {lastExecutionNotice && (
        <div className="flex items-center justify-between border-b border-blue-200 bg-blue-50 px-3 py-1.5 text-[11px] text-blue-800 dark:border-slate-800 dark:bg-blue-950/30 dark:text-blue-200">
          <span>{lastExecutionNotice}</span>
          <button
            type="button"
            aria-label="Dismiss notice"
            onClick={() => setLastExecutionNotice(null)}
            className="text-blue-600 hover:text-blue-900 dark:text-slate-400 dark:hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Active Legs Table */}
      <div className="terminal-scroll max-h-[260px] overflow-auto">
        {legs.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1 px-4 py-8 text-center text-xs text-slate-500 dark:text-slate-400">
            <p className="font-medium text-slate-700 dark:text-slate-300">
              No active legs in strategy
            </p>
            <p className="text-[11px] text-slate-500">
              Click <span className="font-semibold text-[#15803D] dark:text-emerald-400">B</span>{" "}
              / <span className="font-semibold text-[#B91C1C] dark:text-rose-400">S</span> on any
              strike in the Option Chain or pick a preset above.
            </p>
          </div>
        ) : (
          <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
            <thead className="sticky top-0 z-10 bg-slate-100 text-[10px] uppercase tracking-wider text-slate-600 dark:bg-[#0d1422] dark:text-slate-400">
              <tr>
                <th className="border-b border-slate-200 px-2 py-1.5 text-left dark:border-slate-800">
                  On
                </th>
                <th className="border-b border-slate-200 px-1.5 py-1.5 text-left dark:border-slate-800">
                  B/S
                </th>
                <th className="border-b border-slate-200 px-2 py-1.5 text-left dark:border-slate-800">
                  Contract
                </th>
                <th className="border-b border-slate-200 px-2 py-1.5 text-center dark:border-slate-800">
                  {displayQtyMode === "lots" ? "Lots" : "Qty"}
                </th>
                <th className="border-b border-slate-200 px-2 py-1.5 text-right dark:border-slate-800">
                  Entry
                </th>
                <th className="border-b border-slate-200 px-2 py-1.5 text-right dark:border-slate-800">
                  LTP
                </th>
                <th className="border-b border-slate-200 px-2 py-1.5 text-right dark:border-slate-800">
                  P&amp;L ({pnlUnit === "POINTS" ? "Pts" : "₹"})
                </th>
                <th className="border-b border-slate-200 px-2 py-1.5 text-center dark:border-slate-800">
                  Super SL / Tgt
                </th>
                <th className="border-b border-slate-200 px-2 py-1.5 text-right dark:border-slate-800">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {legs.map((leg) => {
                const quote = activeLegQuotes[leg.contract_id];
                const curLtp = quote ? quote.ltp : leg.entry_price;
                const effectiveLots = leg.lots * lotMultiplier;
                const qty = effectiveLots * leg.lot_size;
                const signedQty = leg.side === "BUY" ? qty : -qty;
                const legPnl = signedQty * (curLtp - leg.entry_price);
                const expTag = expiryTagByDate[leg.expiry] ?? "";

                return (
                  <tr
                    key={leg.leg_id}
                    className={`border-b border-slate-200 hover:bg-slate-50 dark:border-slate-800/60 dark:hover:bg-slate-800/30 ${
                      !leg.enabled ? "opacity-50" : ""
                    }`}
                  >
                    <td className="px-2 py-1.5">
                      <button
                        type="button"
                        aria-label={leg.enabled ? "Disable leg" : "Enable leg"}
                        onClick={() => toggleLegEnabled(leg.leg_id)}
                        className="text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
                      >
                        {leg.enabled ? (
                          <CheckSquare className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" />
                        ) : (
                          <Square className="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" />
                        )}
                      </button>
                    </td>

                    <td className="px-1.5 py-1.5">
                      <button
                        type="button"
                        title="Click to flip Buy/Sell"
                        onClick={() => flipLegSide(leg.leg_id)}
                        className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                          leg.side === "BUY"
                            ? "border border-green-300 bg-[#DCFCE7] text-[#15803D] dark:border-emerald-500/40 dark:bg-emerald-600/25 dark:text-emerald-300"
                            : "border border-red-300 bg-[#FEE2E2] text-[#B91C1C] dark:border-rose-500/40 dark:bg-rose-600/25 dark:text-rose-300"
                        }`}
                      >
                        {leg.side === "BUY" ? "B" : "S"}
                      </button>
                    </td>

                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono font-semibold text-slate-900 dark:text-slate-100">
                          {leg.option_type === "FUT"
                            ? `${leg.symbol} FUT`
                            : `${leg.strike} ${leg.option_type}`}
                        </span>
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                          {formatShortExpiry(leg.expiry)}
                          {expTag ? ` (${expTag})` : ""}
                        </span>
                      </div>
                    </td>

                    <td className="px-2 py-1.5">
                      <div className="flex items-center justify-center gap-1">
                        <button
                          type="button"
                          aria-label="Decrease lots"
                          onClick={() => updateLegLots(leg.leg_id, leg.lots - 1)}
                          className="rounded border border-slate-300 p-0.5 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                        >
                          <Minus className="h-2.5 w-2.5" />
                        </button>
                        <span className="min-w-[34px] text-center font-mono text-slate-900 dark:text-slate-100">
                          {displayQtyMode === "lots" ? (
                            lotMultiplier > 1 ? (
                              <span title={`${leg.lots} base × ${lotMultiplier} = ${effectiveLots} lots`}>
                                {leg.lots}L×{lotMultiplier}={effectiveLots}L
                              </span>
                            ) : (
                              `${leg.lots}L`
                            )
                          ) : (
                            qty
                          )}
                        </span>
                        <button
                          type="button"
                          aria-label="Increase lots"
                          onClick={() => updateLegLots(leg.leg_id, leg.lots + 1)}
                          className="rounded border border-slate-300 p-0.5 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                        >
                          <Plus className="h-2.5 w-2.5" />
                        </button>
                      </div>
                    </td>

                    <td className="px-2 py-1.5 text-right font-mono text-slate-600 dark:text-slate-300">
                      {leg.entry_price.toFixed(2)}
                    </td>

                    <td className="px-2 py-1.5 text-right font-mono text-slate-900 dark:text-slate-100">
                      {curLtp.toFixed(2)}
                    </td>

                    <td
                      className={`px-2 py-1.5 text-right font-mono font-semibold ${
                        legPnl > 0
                          ? "text-[#16A34A] dark:text-emerald-400"
                          : legPnl < 0
                            ? "text-[#DC2626] dark:text-rose-400"
                            : "text-slate-600 dark:text-slate-300"
                      }`}
                    >
                      {formatPnl(legPnl, pnlUnit, lotSize, { signed: true })}
                    </td>

                    <td className="px-2 py-1.5">
                      <div className="flex items-center justify-center gap-1">
                        <input
                          type="number"
                          min={0}
                          step={0.5}
                          placeholder="SL"
                          aria-label={`Stop loss for ${leg.contract_id}`}
                          value={leg.stop_loss_price ?? ""}
                          onChange={(e) => {
                            const v = e.target.value.trim();
                            updateLegRisk(leg.leg_id, {
                              stop_loss_price: v === "" ? null : Number(v),
                            });
                          }}
                          className="w-14 rounded border border-slate-200 bg-white px-1 py-0.5 text-center font-mono text-[10px] text-slate-800 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        />
                        <input
                          type="number"
                          min={0}
                          step={0.5}
                          placeholder="Tgt"
                          aria-label={`Target price for ${leg.contract_id}`}
                          value={leg.target_price ?? ""}
                          onChange={(e) => {
                            const v = e.target.value.trim();
                            updateLegRisk(leg.leg_id, {
                              target_price: v === "" ? null : Number(v),
                            });
                          }}
                          className="w-14 rounded border border-slate-200 bg-white px-1 py-0.5 text-center font-mono text-[10px] text-slate-800 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        />
                      </div>
                    </td>

                    <td className="px-2 py-1.5 text-right">
                      <div className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => openPartialExitModal(leg.leg_id)}
                          className="rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 hover:bg-amber-100 dark:border-slate-700 dark:bg-slate-900 dark:text-amber-300 dark:hover:bg-amber-500/20"
                        >
                          Exit
                        </button>
                        <button
                          type="button"
                          aria-label="Remove leg"
                          onClick={() => removeLeg(leg.leg_id)}
                          className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-red-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-rose-400"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Realized / Closed Legs Summary */}
      {(closedLegs.length > 0 || realizedPnl !== 0) && (
        <div className="border-t border-slate-200 bg-slate-50 px-3 py-2 text-[11px] dark:border-slate-800 dark:bg-[#0d1422]">
          <div className="flex items-center justify-between">
            <span className="font-medium text-slate-600 dark:text-slate-400">
              Booked / Partial Exits ({closedLegs.length})
            </span>
            <span
              className={`font-mono font-semibold tabular-nums ${
                realizedPnl >= 0
                  ? "text-[#16A34A] dark:text-emerald-400"
                  : "text-[#DC2626] dark:text-rose-400"
              }`}
            >
              Realized: {formatPnl(realizedPnl, pnlUnit, lotSize, { signed: true, decimals: 2 })}
            </span>
          </div>
          {closedLegs.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {closedLegs.slice(0, 4).map((cl, idx) => (
                <span
                  key={`${cl.leg_id}-${idx}`}
                  className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-700 tabular-nums dark:border-slate-800 dark:bg-slate-900/90 dark:text-slate-300"
                >
                  {cl.side === "BUY" ? "B" : "S"} {cl.strike ?? "FUT"} {cl.option_type} ×
                  {cl.lots_closed}L{" "}
                  <span
                    className={
                      cl.realized_pnl >= 0
                        ? "text-[#16A34A] dark:text-emerald-400"
                        : "text-[#DC2626] dark:text-rose-400"
                    }
                  >
                    {formatSignedInr(cl.realized_pnl, 0)}
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
