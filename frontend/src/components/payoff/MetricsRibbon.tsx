"use client";

import type { MarginBreakdown } from "@/lib/api/types";
import { formatInr, formatSignedInr } from "@/lib/format";
import type { PayoffEvaluation } from "@/lib/quant";
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
  const includeCharges = useUiStore((s) => s.includeCharges);
  const toggleIncludeCharges = useUiStore((s) => s.toggleIncludeCharges);

  const maxProfitText = evaluation.max_profit_unlimited
    ? "Unlimited"
    : evaluation.max_profit !== null
      ? formatInr(evaluation.max_profit, 0)
      : "--";

  const maxLossText = evaluation.max_loss_unlimited
    ? "Unlimited"
    : evaluation.max_loss !== null
      ? formatInr(evaluation.max_loss, 0)
      : "--";

  const breakevenText =
    evaluation.breakevens.length > 0
      ? evaluation.breakevens.map((b) => b.toLocaleString("en-IN", { maximumFractionDigits: 1 })).join(" / ")
      : "--";

  return (
    <div className="space-y-2">
      {/* Primary Strategy Risk/Reward Ribbon */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <div className="rounded-lg border border-slate-800 bg-[#0e1523] px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">Max Profit</div>
          <div className="mt-0.5 font-mono text-sm font-bold text-emerald-400 tabular-nums">
            {maxProfitText}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-[#0e1523] px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">Max Loss</div>
          <div className="mt-0.5 font-mono text-sm font-bold text-rose-400 tabular-nums">
            {maxLossText}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-[#0e1523] px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">Risk : Reward</div>
          <div className="mt-0.5 font-mono text-sm font-semibold text-slate-100 tabular-nums">
            {evaluation.risk_reward !== null ? `1 : ${evaluation.risk_reward.toFixed(2)}` : "--"}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-[#0e1523] px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">Breakevens</div>
          <div className="mt-0.5 truncate font-mono text-xs font-semibold text-amber-300 tabular-nums" title={breakevenText}>
            {breakevenText}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-[#0e1523] px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">POP</div>
          <div className="mt-0.5 font-mono text-sm font-semibold text-sky-300 tabular-nums">
            {evaluation.pop.toFixed(1)}%
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-[#0e1523] px-3 py-2">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-slate-400">
            <span>Est. Margin</span>
            {isLoadingMargin && <span className="text-blue-400">…</span>}
          </div>
          <div className="mt-0.5 font-mono text-sm font-semibold text-slate-100 tabular-nums">
            {margin ? formatInr(margin.total_margin, 0) : "--"}
          </div>
          {margin && margin.hedge_benefit > 0 && (
            <div className="text-[10px] text-emerald-400 tabular-nums">
              Benefit: {formatInr(margin.hedge_benefit, 0)}
            </div>
          )}
        </div>
      </div>

      {/* Portfolio Greeks + MTM + Charges Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-[#0d1422] px-3 py-2 text-xs tabular-nums">
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <span className="text-slate-400">Proj. P&amp;L: </span>
            <span
              className={`font-mono font-bold ${
                evaluation.current_mtm_pnl >= 0 ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {formatSignedInr(evaluation.current_mtm_pnl, 0)}
            </span>
          </div>
          {realizedPnl !== 0 && (
            <div>
              <span className="text-slate-400">Realized: </span>
              <span
                className={`font-mono font-semibold ${
                  realizedPnl >= 0 ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {formatSignedInr(realizedPnl, 0)}
              </span>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 font-mono text-[11px] text-slate-300">
          <span>
            Δ <strong className="text-white">{evaluation.net_greeks.delta.toFixed(1)}</strong>
          </span>
          <span>
            Θ/day{" "}
            <strong
              className={
                evaluation.net_greeks.theta >= 0 ? "text-emerald-400" : "text-rose-400"
              }
            >
              {evaluation.net_greeks.theta >= 0 ? "+" : ""}
              {evaluation.net_greeks.theta.toFixed(0)}
            </strong>
          </span>
          <span>
            Γ <strong className="text-white">{evaluation.net_greeks.gamma.toFixed(3)}</strong>
          </span>
          <span>
            V <strong className="text-white">{evaluation.net_greeks.vega.toFixed(0)}</strong>
          </span>
        </div>

        <label className="inline-flex cursor-pointer items-center gap-2 text-[11px] text-slate-300">
          <input
            type="checkbox"
            checked={includeCharges}
            onChange={toggleIncludeCharges}
            className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-900 accent-blue-500"
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
  );
}

