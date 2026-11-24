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
import { formatShortExpiry, formatSignedInr } from "@/lib/format";
import { buildPresetLegs, type PresetKey, STRATEGY_PRESETS } from "@/lib/presets";
import { useMarketStore } from "@/stores/marketStore";
import { useSimulatorStore } from "@/stores/simulatorStore";
import { useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";

export function StrategyBuilderPanel() {
  const legs = useStrategyStore((s) => s.legs);
  const closedLegs = useStrategyStore((s) => s.closedLegs);
  const realizedPnl = useStrategyStore((s) => s.realizedPnl);
  const strategyId = useStrategyStore((s) => s.strategyId);
  const strategyName = useStrategyStore((s) => s.strategyName);
  const isExecuting = useStrategyStore((s) => s.isExecuting);
  const lastExecutionNotice = useStrategyStore((s) => s.lastExecutionNotice);

  const setStrategyName = useStrategyStore((s) => s.setStrategyName);
  const replaceWithLegs = useStrategyStore((s) => s.replaceWithLegs);
  const toggleLegEnabled = useStrategyStore((s) => s.toggleLegEnabled);
  const flipLegSide = useStrategyStore((s) => s.flipLegSide);
  const updateLegLots = useStrategyStore((s) => s.updateLegLots);
  const removeLeg = useStrategyStore((s) => s.removeLeg);
  const squareOffAll = useStrategyStore((s) => s.squareOffAll);
  const clearStrategy = useStrategyStore((s) => s.clearStrategy);
  const loadSavedStrategy = useStrategyStore((s) => s.loadSavedStrategy);
  const setLastExecutionNotice = useStrategyStore((s) => s.setLastExecutionNotice);

  const symbol = useMarketStore((s) => s.symbol);
  const expiries = useMarketStore((s) => s.expiries);
  const selectedChainExpiry = useMarketStore((s) => s.selectedChainExpiry);
  const asOfIso = useMarketStore((s) => s.asOfIso);
  const activeLegQuotes = useMarketStore((s) => s.activeLegQuotes);
  const getCurrentSnapshot = useMarketStore((s) => s.getCurrentSnapshot);

  const mode = useSimulatorStore((s) => s.mode);
  const displayQtyMode = useUiStore((s) => s.displayQtyMode);
  const setDisplayQtyMode = useUiStore((s) => s.setDisplayQtyMode);
  const defaultLots = useUiStore((s) => s.defaultLots);
  const openPartialExitModal = useUiStore((s) => s.openPartialExitModal);

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
        metadata: { saved_from: "stockmock_ui" },
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
    const openLegs = legs.filter((l) => l.status === "OPEN" && l.enabled);
    if (openLegs.length === 0) return;
    try {
      const res = await executeOrders({
        strategy_id: strategyId,
        trading_mode: "SIMULATOR",
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
        `Virtual order filled (${childCount} slice fill${childCount === 1 ? "" : "s"}, key ${res.idempotency_key.slice(0, 8)}…)`
      );
    } catch (err) {
      setLastExecutionNotice(
        err instanceof Error ? `Order failed: ${err.message}` : "Execution failed"
      );
    }
  };

  return (
    <section className="flex flex-col rounded-xl border border-slate-800 bg-[#111827] shadow-lg overflow-hidden">
      {/* Presets Ribbon */}
      <div className="border-b border-slate-800 bg-[#0e1523] px-3 py-2">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Ready-Made Strategy Presets
          </span>
          <span className="text-[10px] text-slate-500">
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
              className="rounded-md border border-slate-700/80 bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-200 transition-colors hover:border-blue-500/50 hover:bg-blue-600/15 hover:text-blue-200 disabled:opacity-50"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Strategy Action Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-3 py-2">
        <div className="flex items-center gap-2">
          <input
            type="text"
            aria-label="Strategy Name"
            value={strategyName}
            onChange={(e) => setStrategyName(e.target.value)}
            className="w-44 rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-100 focus:border-blue-500 focus:outline-none"
          />
          <button
            type="button"
            disabled={isSaving}
            onClick={() => void handleSaveStrategy()}
            className="inline-flex items-center gap-1 rounded-md border border-blue-500/40 bg-blue-600/20 px-2.5 py-1 text-xs font-medium text-blue-200 hover:bg-blue-600/35 disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            <span>{isSaving ? "Saving…" : strategyId ? "Update" : "Save"}</span>
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <div className="flex items-center rounded border border-slate-700 bg-slate-900 p-0.5 text-[10px]">
            <button
              type="button"
              onClick={() => setDisplayQtyMode("lots")}
              className={`rounded px-1.5 py-0.5 ${
                displayQtyMode === "lots" ? "bg-slate-700 text-white" : "text-slate-400"
              }`}
            >
              Lots
            </button>
            <button
              type="button"
              onClick={() => setDisplayQtyMode("qty")}
              className={`rounded px-1.5 py-0.5 ${
                displayQtyMode === "qty" ? "bg-slate-700 text-white" : "text-slate-400"
              }`}
            >
              Qty
            </button>
          </div>

          <button
            type="button"
            disabled={legs.length === 0 || isExecuting}
            onClick={() => void handleExecuteVirtualOrder()}
            className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-40"
          >
            <Send className="h-3 w-3" />
            <span>Log Order</span>
          </button>

          <button
            type="button"
            disabled={legs.length === 0 || isExecuting}
            onClick={() => void squareOffAll()}
            className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-xs font-medium text-amber-200 hover:bg-amber-500/25 disabled:opacity-40"
          >
            <LogOut className="h-3 w-3" />
            <span>Sq. Off</span>
          </button>

          <button
            type="button"
            disabled={legs.length === 0 && closedLegs.length === 0}
            onClick={clearStrategy}
            title="Clear all legs"
            className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300 hover:bg-rose-600/20 hover:text-rose-300 disabled:opacity-40"
          >
            <Trash2 className="h-3 w-3" />
            <span>Clear</span>
          </button>
        </div>
      </div>

      {/* Notice Banner */}
      {lastExecutionNotice && (
        <div className="flex items-center justify-between border-b border-slate-800 bg-blue-950/30 px-3 py-1.5 text-[11px] text-blue-200">
          <span>{lastExecutionNotice}</span>
          <button
            type="button"
            aria-label="Dismiss notice"
            onClick={() => setLastExecutionNotice(null)}
            className="text-slate-400 hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Active Legs Table */}
      <div className="terminal-scroll max-h-[260px] overflow-auto">
        {legs.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1 px-4 py-8 text-center text-xs text-slate-400">
            <p className="font-medium text-slate-300">No active legs in strategy</p>
            <p className="text-[11px] text-slate-500">
              Click <span className="text-emerald-400 font-semibold">B</span> /{" "}
              <span className="text-rose-400 font-semibold">S</span> on any strike in the Option
              Chain or pick a preset above.
            </p>
          </div>
        ) : (
          <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
            <thead className="sticky top-0 z-10 bg-[#0d1422] text-[10px] uppercase tracking-wider text-slate-400">
              <tr>
                <th className="border-b border-slate-800 px-2 py-1.5 text-left">On</th>
                <th className="border-b border-slate-800 px-1.5 py-1.5 text-left">B/S</th>
                <th className="border-b border-slate-800 px-2 py-1.5 text-left">Contract</th>
                <th className="border-b border-slate-800 px-2 py-1.5 text-center">
                  {displayQtyMode === "lots" ? "Lots" : "Qty"}
                </th>
                <th className="border-b border-slate-800 px-2 py-1.5 text-right">Entry</th>
                <th className="border-b border-slate-800 px-2 py-1.5 text-right">LTP</th>
                <th className="border-b border-slate-800 px-2 py-1.5 text-right">P&amp;L</th>
                <th className="border-b border-slate-800 px-2 py-1.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {legs.map((leg) => {
                const quote = activeLegQuotes[leg.contract_id];
                const curLtp = quote ? quote.ltp : leg.entry_price;
                const qty = leg.lots * leg.lot_size;
                const signedQty = leg.side === "BUY" ? qty : -qty;
                const legPnl = signedQty * (curLtp - leg.entry_price);
                const expTag = expiryTagByDate[leg.expiry] ?? "";

                return (
                  <tr
                    key={leg.leg_id}
                    className={`border-b border-slate-800/60 hover:bg-slate-800/30 ${
                      !leg.enabled ? "opacity-50" : ""
                    }`}
                  >
                    <td className="px-2 py-1.5">
                      <button
                        type="button"
                        aria-label={leg.enabled ? "Disable leg" : "Enable leg"}
                        onClick={() => toggleLegEnabled(leg.leg_id)}
                        className="text-slate-300 hover:text-white"
                      >
                        {leg.enabled ? (
                          <CheckSquare className="h-3.5 w-3.5 text-blue-400" />
                        ) : (
                          <Square className="h-3.5 w-3.5 text-slate-500" />
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
                            ? "bg-emerald-600/25 text-emerald-300 border border-emerald-500/40"
                            : "bg-rose-600/25 text-rose-300 border border-rose-500/40"
                        }`}
                      >
                        {leg.side === "BUY" ? "B" : "S"}
                      </button>
                    </td>

                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono font-semibold text-slate-100">
                          {leg.option_type === "FUT"
                            ? `${leg.symbol} FUT`
                            : `${leg.strike} ${leg.option_type}`}
                        </span>
                        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
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
                          className="rounded border border-slate-700 p-0.5 text-slate-300 hover:bg-slate-800"
                        >
                          <Minus className="h-2.5 w-2.5" />
                        </button>
                        <span className="min-w-[28px] text-center font-mono text-slate-100">
                          {displayQtyMode === "lots" ? leg.lots : qty}
                        </span>
                        <button
                          type="button"
                          aria-label="Increase lots"
                          onClick={() => updateLegLots(leg.leg_id, leg.lots + 1)}
                          className="rounded border border-slate-700 p-0.5 text-slate-300 hover:bg-slate-800"
                        >
                          <Plus className="h-2.5 w-2.5" />
                        </button>
                      </div>
                    </td>

                    <td className="px-2 py-1.5 text-right font-mono text-slate-300">
                      {leg.entry_price.toFixed(2)}
                    </td>

                    <td className="px-2 py-1.5 text-right font-mono text-slate-100">
                      {curLtp.toFixed(2)}
                    </td>

                    <td
                      className={`px-2 py-1.5 text-right font-mono font-semibold ${
                        legPnl > 0
                          ? "text-emerald-400"
                          : legPnl < 0
                            ? "text-rose-400"
                            : "text-slate-300"
                      }`}
                    >
                      {formatSignedInr(legPnl, 0)}
                    </td>

                    <td className="px-2 py-1.5 text-right">
                      <div className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => openPartialExitModal(leg.leg_id)}
                          className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-amber-300 hover:bg-amber-500/20"
                        >
                          Exit
                        </button>
                        <button
                          type="button"
                          aria-label="Remove leg"
                          onClick={() => removeLeg(leg.leg_id)}
                          className="rounded p-0.5 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
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
        <div className="border-t border-slate-800 bg-[#0d1422] px-3 py-2 text-[11px]">
          <div className="flex items-center justify-between">
            <span className="font-medium text-slate-400">
              Booked / Partial Exits ({closedLegs.length})
            </span>
            <span
              className={`font-mono font-semibold tabular-nums ${
                realizedPnl >= 0 ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              Realized: {formatSignedInr(realizedPnl, 2)}
            </span>
          </div>
          {closedLegs.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {closedLegs.slice(0, 4).map((cl, idx) => (
                <span
                  key={`${cl.leg_id}-${idx}`}
                  className="rounded border border-slate-800 bg-slate-900/90 px-2 py-0.5 text-[10px] text-slate-300 tabular-nums"
                >
                  {cl.side === "BUY" ? "B" : "S"} {cl.strike ?? "FUT"} {cl.option_type} ×{cl.lots_closed}L{" "}
                  <span className={cl.realized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
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

