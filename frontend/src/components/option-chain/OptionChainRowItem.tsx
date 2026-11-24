"use client";

import React from "react";
import type { OptionSide } from "@/lib/api/types";
import { formatCompactOi } from "@/lib/format";
import { useMarketStore } from "@/stores/marketStore";

interface OptionChainRowItemProps {
  strike: number;
  isAtm: boolean;
  atmStrike: number;
  maxOi: number;
  cePositionCount: number;
  pePositionCount: number;
  onAddLeg: (strike: number, optionType: "CE" | "PE", side: OptionSide) => void;
}

export const OptionChainRowItem = React.memo(function OptionChainRowItem({
  strike,
  isAtm,
  atmStrike,
  maxOi,
  cePositionCount,
  pePositionCount,
  onAddLeg,
}: OptionChainRowItemProps) {
  const row = useMarketStore((s) => s.rowsByStrike[strike]);
  if (!row) return null;

  const ceItm = strike < atmStrike;
  const peItm = strike > atmStrike;

  const ceOiPct = Math.min(100, Math.round((row.ce_oi / Math.max(maxOi, 1)) * 100));
  const peOiPct = Math.min(100, Math.round((row.pe_oi / Math.max(maxOi, 1)) * 100));

  const ceBg = isAtm
    ? "bg-[#FEF9C3] dark:bg-amber-500/10"
    : ceItm
      ? "bg-[#F8FAFC] dark:bg-slate-900/80"
      : "bg-white dark:bg-transparent";
  const peBg = isAtm
    ? "bg-[#FEF9C3] dark:bg-amber-500/10"
    : peItm
      ? "bg-[#F8FAFC] dark:bg-slate-900/80"
      : "bg-white dark:bg-transparent";

  return (
    <tr
      data-strike={strike}
      className={`border-b border-slate-200 text-[11px] tabular-nums transition-colors hover:bg-slate-50 dark:border-slate-800/70 dark:hover:bg-slate-800/40 ${
        isAtm ? "ring-1 ring-inset ring-amber-400/60 dark:ring-amber-500/40" : ""
      }`}
    >
      {/* CALL OI */}
      <td className={`relative px-2 py-1.5 text-right text-slate-600 dark:text-slate-300 ${ceBg}`}>
        <div
          className="pointer-events-none absolute inset-y-0.5 right-0 bg-emerald-500/15"
          style={{ width: `${ceOiPct}%` }}
        />
        <span className="relative z-10">{formatCompactOi(row.ce_oi)}</span>
      </td>

      {/* CALL IV */}
      <td className={`px-1.5 py-1.5 text-right text-slate-500 dark:text-slate-400 ${ceBg}`}>
        {row.ce_iv.toFixed(1)}
      </td>

      {/* CALL DELTA */}
      <td className={`px-1.5 py-1.5 text-right text-slate-600 dark:text-slate-300 ${ceBg}`}>
        {row.ce_delta.toFixed(2)}
      </td>

      {/* CALL LTP + B/S */}
      <td className={`px-2 py-1 ${ceBg}`}>
        <div className="flex items-center justify-end gap-1.5">
          {cePositionCount > 0 && (
            <span className="rounded bg-blue-100 px-1 text-[10px] font-semibold text-blue-700 dark:bg-blue-500/20 dark:text-blue-300">
              {cePositionCount}L
            </span>
          )}
          <span className="min-w-[52px] text-right font-mono font-semibold text-slate-900 dark:text-slate-100">
            {row.ce_ltp.toFixed(2)}
          </span>
          <div className="flex items-center gap-0.5">
            <button
              type="button"
              aria-label={`Buy ${strike} CE`}
              onClick={() => onAddLeg(strike, "CE", "BUY")}
              className="rounded border border-green-300 bg-[#DCFCE7] px-1.5 py-0.5 text-[10px] font-bold text-[#15803D] hover:bg-[#16A34A] hover:text-white dark:border-emerald-500/40 dark:bg-emerald-600/25 dark:text-emerald-300 dark:hover:bg-emerald-600 dark:hover:text-white"
            >
              B
            </button>
            <button
              type="button"
              aria-label={`Sell ${strike} CE`}
              onClick={() => onAddLeg(strike, "CE", "SELL")}
              className="rounded border border-red-300 bg-[#FEE2E2] px-1.5 py-0.5 text-[10px] font-bold text-[#B91C1C] hover:bg-[#DC2626] hover:text-white dark:border-rose-500/40 dark:bg-rose-600/25 dark:text-rose-300 dark:hover:bg-rose-600 dark:hover:text-white"
            >
              S
            </button>
          </div>
        </div>
      </td>

      {/* CENTER STRIKE */}
      <th
        scope="row"
        className={`border-x border-slate-200 px-2.5 py-1.5 text-center font-mono text-xs font-bold dark:border-slate-800 ${
          isAtm
            ? "bg-amber-200/70 text-amber-950 dark:bg-amber-500/20 dark:text-amber-300"
            : "bg-slate-100 text-slate-900 dark:bg-[#0e1523] dark:text-slate-100"
        }`}
      >
        <div className="flex items-center justify-center gap-1">
          <span>{strike}</span>
          {isAtm && (
            <span className="rounded bg-amber-500/30 px-1 text-[9px] font-bold text-amber-900 dark:text-amber-200">
              ATM
            </span>
          )}
        </div>
      </th>

      {/* PUT LTP + B/S */}
      <td className={`px-2 py-1 ${peBg}`}>
        <div className="flex items-center justify-start gap-1.5">
          <div className="flex items-center gap-0.5">
            <button
              type="button"
              aria-label={`Buy ${strike} PE`}
              onClick={() => onAddLeg(strike, "PE", "BUY")}
              className="rounded border border-green-300 bg-[#DCFCE7] px-1.5 py-0.5 text-[10px] font-bold text-[#15803D] hover:bg-[#16A34A] hover:text-white dark:border-emerald-500/40 dark:bg-emerald-600/25 dark:text-emerald-300 dark:hover:bg-emerald-600 dark:hover:text-white"
            >
              B
            </button>
            <button
              type="button"
              aria-label={`Sell ${strike} PE`}
              onClick={() => onAddLeg(strike, "PE", "SELL")}
              className="rounded border border-red-300 bg-[#FEE2E2] px-1.5 py-0.5 text-[10px] font-bold text-[#B91C1C] hover:bg-[#DC2626] hover:text-white dark:border-rose-500/40 dark:bg-rose-600/25 dark:text-rose-300 dark:hover:bg-rose-600 dark:hover:text-white"
            >
              S
            </button>
          </div>
          <span className="min-w-[52px] text-left font-mono font-semibold text-slate-900 dark:text-slate-100">
            {row.pe_ltp.toFixed(2)}
          </span>
          {pePositionCount > 0 && (
            <span className="rounded bg-blue-100 px-1 text-[10px] font-semibold text-blue-700 dark:bg-blue-500/20 dark:text-blue-300">
              {pePositionCount}L
            </span>
          )}
        </div>
      </td>

      {/* PUT DELTA */}
      <td className={`px-1.5 py-1.5 text-left text-slate-600 dark:text-slate-300 ${peBg}`}>
        {row.pe_delta.toFixed(2)}
      </td>

      {/* PUT IV */}
      <td className={`px-1.5 py-1.5 text-left text-slate-500 dark:text-slate-400 ${peBg}`}>
        {row.pe_iv.toFixed(1)}
      </td>

      {/* PUT OI */}
      <td className={`relative px-2 py-1.5 text-left text-slate-600 dark:text-slate-300 ${peBg}`}>
        <div
          className="pointer-events-none absolute inset-y-0.5 left-0 bg-rose-500/15"
          style={{ width: `${peOiPct}%` }}
        />
        <span className="relative z-10">{formatCompactOi(row.pe_oi)}</span>
      </td>
    </tr>
  );
});
