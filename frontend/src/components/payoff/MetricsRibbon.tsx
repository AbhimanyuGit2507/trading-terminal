"use client";

import type { MarginBreakdown } from "@/lib/api/types";
import { formatInr, formatPnl } from "@/lib/format";
import type { PayoffEvaluation } from "@/lib/quant";
import { useMarketStore } from "@/stores/marketStore";
import { useUiStore } from "@/stores/uiStore";

interface MetricsRibbonProps {
  evaluation: PayoffEvaluation;
  realizedPnl: number;
  margin: MarginBreakdown | null;
  isLoadingMargin: boolean;
}

export function MetricsRibbon({
  evaluation,
  realizedPnl,
  margin,
  isLoadingMargin,
}: MetricsRibbonProps) {
  const lotSize = useMarketStore((s) => s.lotSize);
  const includeCharges = useUiStore((s) => s.includeCharges);
  const toggleIncludeCharges = useUiStore((s) => s.toggleIncludeCharges);
  const pnlUnit = useUiStore((s) => s.pnlUnit);
  const setPnlUnit = useUiStore((s) => s.setPnlUnit);

  const maxProfitText = evaluation.max_profit_unlimited
    ? "Unlimited"
    : evaluation.max_profit !== null
      ? formatPnl(evaluation.max_profit, pnlUnit, lotSize, {
          decimals: pnlUnit === "POINTS" ? 2 : 0,
        })
      : "--";

  const maxLossText = evaluation.max_loss_unlimited
    ? "Unlimited"
    : evaluation.max_loss !== null
      ? formatPnl(evaluation.max_loss, pnlUnit, lotSize, {
          decimals: pnlUnit === "POINTS" ? 2 : 0,
        })
      : "--";

  const breakevenText =
    evaluation.breakevens.length > 0
      ? evaluation.breakevens
          .map((b) => b.toLocaleString("en-IN", { maximumFractionDigits: 1 }))
          .join(" / ")
      : "--";

  return (
    <div className="space-y-2">
      {/* Primary Strategy Risk/Reward Ribbon */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-[#0e1523]">
          <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Max Profit
          </div>
          <div className="mt-0.5 font-mono text-sm font-bold text-[#16A34A] tabular-nums dark:text-emerald-400">
            {maxProfitText}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-[#0e1523]">
          <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Max Loss
          </div>
          <div className="mt-0.5 font-mono text-sm font-bold text-[#DC2626] tabular-nums dark:text-rose-400">
            {maxLossText}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-[#0e1523]">
          <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Risk : Reward
          </div>
          <div className="mt-0.5 font-mono text-sm font-semibold text-slate-900 tabular-nums dark:text-slate-100">
            {evaluation.risk_reward !== null ? `1 : ${evaluation.risk_reward.toFixed(2)}` : "--"}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-[#0e1523]">
          <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Breakevens
          </div>
          <div
            className="mt-0.5 truncate font-mono text-xs font-semibold text-amber-700 tabular-nums dark:text-amber-300"
            title={breakevenText}
          >
            {breakevenText}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-[#0e1523]">
          <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
            POP
          </div>
          <div className="mt-0.5 font-mono text-sm font-semibold text-blue-700 tabular-nums dark:text-sky-300">
            {evaluation.pop.toFixed(1)}%
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-[#0e1523]">
          <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
            <span>Est. Margin</span>
            {isLoadingMargin && <span className="text-blue-600 dark:text-blue-400">…</span>}
          </div>
          <div className="mt-0.5 font-mono text-sm font-semibold text-slate-900 tabular-nums dark:text-slate-100">
            {margin ? formatInr(margin.total_margin, 0) : "--"}
          </div>
          {margin && margin.hedge_benefit > 0 && (
            <div className="text-[10px] text-[#16A34A] tabular-nums dark:text-emerald-400">
              Benefit: {formatInr(margin.hedge_benefit, 0)}
            </div>
          )}
        </div>
      </div>

      {/* Portfolio Greeks + MTM + ₹/Pts Toggle + Charges Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs tabular-nums dark:border-slate-800 dark:bg-[#0d1422]">
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <span className="text-slate-500 dark:text-slate-400">Proj. P&amp;L: </span>
            <span
              className={`font-mono font-bold ${
                evaluation.current_mtm_pnl >= 0
                  ? "text-[#16A34A] dark:text-emerald-400"
                  : "text-[#DC2626] dark:text-rose-400"
              }`}
            >
              {formatPnl(evaluation.current_mtm_pnl, pnlUnit, lotSize, {
                signed: true,
                decimals: pnlUnit === "POINTS" ? 2 : 0,
              })}
            </span>
          </div>
          {realizedPnl !== 0 && (
            <div>
              <span className="text-slate-500 dark:text-slate-400">Realized: </span>
              <span
                className={`font-mono font-semibold ${
                  realizedPnl >= 0
                    ? "text-[#16A34A] dark:text-emerald-400"
                    : "text-[#DC2626] dark:text-rose-400"
                }`}
              >
                {formatPnl(realizedPnl, pnlUnit, lotSize, {
                  signed: true,
                  decimals: pnlUnit === "POINTS" ? 2 : 0,
                })}
              </span>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 font-mono text-[11px] text-slate-700 dark:text-slate-300">
          <span>
            Δ <strong className="text-slate-900 dark:text-white">{evaluation.net_greeks.delta.toFixed(1)}</strong>
          </span>
          <span>
            Θ/day{" "}
            <strong
              className={
                evaluation.net_greeks.theta >= 0
                  ? "text-[#16A34A] dark:text-emerald-400"
                  : "text-[#DC2626] dark:text-rose-400"
              }
            >
              {evaluation.net_greeks.theta >= 0 ? "+" : ""}
              {evaluation.net_greeks.theta.toFixed(0)}
            </strong>
          </span>
          <span>
            Γ <strong className="text-slate-900 dark:text-white">{evaluation.net_greeks.gamma.toFixed(3)}</strong>
          </span>
          <span>
            V <strong className="text-slate-900 dark:text-white">{evaluation.net_greeks.vega.toFixed(0)}</strong>
          </span>
        </div>

        <div className="flex items-center gap-3">
          <div
            className="flex items-center rounded border border-slate-300 bg-white p-0.5 text-[10px] font-semibold dark:border-slate-700 dark:bg-slate-900"
            role="group"
            aria-label="Metrics P&L Unit"
          >
            <button
              type="button"
              onClick={() => setPnlUnit("INR")}
              className={`rounded px-1.5 py-0.5 ${
                pnlUnit === "INR"
                  ? "bg-blue-600 text-white"
                  : "text-slate-600 dark:text-slate-400"
              }`}
            >
              ₹
            </button>
            <button
              type="button"
              onClick={() => setPnlUnit("POINTS")}
              className={`rounded px-1.5 py-0.5 ${
                pnlUnit === "POINTS"
                  ? "bg-blue-600 text-white"
                  : "text-slate-600 dark:text-slate-400"
              }`}
            >
              Pts
            </button>
          </div>

          <label className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              checked={includeCharges}
              onChange={toggleIncludeCharges}
              className="h-3.5 w-3.5 rounded border-slate-300 bg-white accent-blue-600 dark:border-slate-600 dark:bg-slate-900"
            />
            <span>
              Include Est. Charges
              {includeCharges && evaluation.estimated_charges > 0
                ? ` (${formatInr(evaluation.estimated_charges, 0)})`
                : ""}
            </span>
          </label>
        </div>
      </div>
    </div>
  );
}
