"use client";

import React from "react";
import { formatCompactOi } from "@/lib/format";
import type { OptionSide } from "@/lib/api/types";
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
    ? "bg-amber-500/10"
    : ceItm
      ? "bg-slate-900/80"
      : "bg-transparent";
  const peBg = isAtm
    ? "bg-amber-500/10"
    : peItm
      ? "bg-slate-900/80"
      : "bg-transparent";

  return (
    <tr
      data-strike={strike}
      className={`border-b border-slate-800/70 text-[11px] tabular-nums transition-colors hover:bg-slate-800/40 ${
        isAtm ? "ring-1 ring-inset ring-amber-500/40" : ""
      }`}
    >
      {/* CALL OI */}
      <td className={`relative px-2 py-1.5 text-right text-slate-300 ${ceBg}`}>
        <div
          className="pointer-events-none absolute inset-y-0.5 right-0 bg-emerald-500/15"
          style={{ width: `${ceOiPct}%` }}
        />
        <span className="relative z-10">{formatCompactOi(row.ce_oi)}</span>
      </td>

      {/* CALL IV */}
      <td className={`px-1.5 py-1.5 text-right text-slate-400 ${ceBg}`}>
        {row.ce_iv.toFixed(1)}
      </td>

      {/* CALL DELTA */}
      <td className={`px-1.5 py-1.5 text-right text-slate-300 ${ceBg}`}>
        {row.ce_delta.toFixed(2)}
      </td>

      {/* CALL LTP + B/S */}
      <td className={`px-2 py-1 ${ceBg}`}>
        <div className="flex items-center justify-end gap-1.5">
          {cePositionCount > 0 && (
            <span className="rounded bg-blue-500/20 px-1 text-[10px] font-semibold text-blue-300">
              {cePositionCount}L
            </span>
          )}
          <span className="min-w-[52px] text-right font-mono font-semibold text-slate-100">
            {row.ce_ltp.toFixed(2)}
          </span>
          <div className="flex items-center gap-0.5">
            <button
              type="button"
              aria-label={`Buy ${strike} CE`}
              onClick={() => onAddLeg(strike, "CE", "BUY")}
              className="rounded bg-emerald-600/25 px-1.5 py-0.5 text-[10px] font-bold text-emerald-300 border border-emerald-500/40 hover:bg-emerald-600 hover:text-white"
            >
              B
            </button>
            <button
              type="button"
              aria-label={`Sell ${strike} CE`}
              onClick={() => onAddLeg(strike, "CE", "SELL")}
              className="rounded bg-rose-600/25 px-1.5 py-0.5 text-[10px] font-bold text-rose-300 border border-rose-500/40 hover:bg-rose-600 hover:text-white"
            >
              S
            </button>
          </div>
        </div>
      </td>

      {/* CENTER STRIKE */}
      <th
        scope="row"
        className={`px-2.5 py-1.5 text-center font-mono text-xs font-bold border-x border-slate-800 ${
          isAtm
            ? "bg-amber-500/20 text-amber-300"
            : "bg-[#0e1523] text-slate-100"
        }`}
      >
        <div className="flex items-center justify-center gap-1">
          <span>{strike}</span>
          {isAtm && (
            <span className="rounded bg-amber-500/30 px-1 text-[9px] font-bold text-amber-200">
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
              className="rounded bg-emerald-600/25 px-1.5 py-0.5 text-[10px] font-bold text-emerald-300 border border-emerald-500/40 hover:bg-emerald-600 hover:text-white"
            >
              B
            </button>
            <button
              type="button"
              aria-label={`Sell ${strike} PE`}
              onClick={() => onAddLeg(strike, "PE", "SELL")}
              className="rounded bg-rose-600/25 px-1.5 py-0.5 text-[10px] font-bold text-rose-300 border border-rose-500/40 hover:bg-rose-600 hover:text-white"
            >
              S
            </button>
          </div>
          <span className="min-w-[52px] text-left font-mono font-semibold text-slate-100">
            {row.pe_ltp.toFixed(2)}
          </span>
          {pePositionCount > 0 && (
            <span className="rounded bg-blue-500/20 px-1 text-[10px] font-semibold text-blue-300">
              {pePositionCount}L
            </span>
          )}
        </div>
      </td>

      {/* PUT DELTA */}
      <td className={`px-1.5 py-1.5 text-left text-slate-300 ${peBg}`}>
        {row.pe_delta.toFixed(2)}
      </td>

      {/* PUT IV */}
      <td className={`px-1.5 py-1.5 text-left text-slate-400 ${peBg}`}>
        {row.pe_iv.toFixed(1)}
      </td>

      {/* PUT OI */}
      <td className={`relative px-2 py-1.5 text-left text-slate-300 ${peBg}`}>
        <div
          className="pointer-events-none absolute inset-y-0.5 left-0 bg-rose-500/15"
          style={{ width: `${peOiPct}%` }}
        />
        <span className="relative z-10">{formatCompactOi(row.pe_oi)}</span>
      </td>
    </tr>
  );
});

