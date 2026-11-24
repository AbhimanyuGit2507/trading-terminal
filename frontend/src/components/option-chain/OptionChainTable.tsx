"use client";

import { useCallback, useMemo, useRef } from "react";
import { Crosshair, Minus, Plus } from "lucide-react";
import type { OptionSide } from "@/lib/api/types";
import { useMarketStore } from "@/stores/marketStore";
import { useStrategyStore } from "@/stores/strategyStore";
import { type StrikeWindow, useUiStore } from "@/stores/uiStore";
import { OptionChainRowItem } from "./OptionChainRowItem";

export function OptionChainTable() {
  const strikes = useMarketStore((s) => s.strikes);
  const atmStrike = useMarketStore((s) => s.atmStrike);
  const maxOi = useMarketStore((s) => s.maxOi);
  const symbol = useMarketStore((s) => s.symbol);
  const exchange = useMarketStore((s) => s.exchange);
  const selectedChainExpiry = useMarketStore((s) => s.selectedChainExpiry);
  const lotSize = useMarketStore((s) => s.lotSize);
  const forwardPrice = useMarketStore((s) => s.forwardPrice);
  const futuresPrice = useMarketStore((s) => s.futuresPrice);
  const futuresContractId = useMarketStore((s) => s.futuresContractId);
  const isLoadingChain = useMarketStore((s) => s.isLoadingChain);

  const legs = useStrategyStore((s) => s.legs);
  const addLeg = useStrategyStore((s) => s.addLeg);

  const strikeWindow = useUiStore((s) => s.strikeWindow);
  const setStrikeWindow = useUiStore((s) => s.setStrikeWindow);
  const defaultLots = useUiStore((s) => s.defaultLots);
  const setDefaultLots = useUiStore((s) => s.setDefaultLots);

  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const visibleStrikes = useMemo(() => {
    if (strikes.length === 0) return [];
    if (strikeWindow >= 999) return strikes;
    let atmIdx = 0;
    let bestDiff = Infinity;
    for (let i = 0; i < strikes.length; i++) {
      const d = Math.abs(strikes[i] - atmStrike);
      if (d < bestDiff) {
        bestDiff = d;
        atmIdx = i;
      }
    }
    const start = Math.max(0, atmIdx - strikeWindow);
    const end = Math.min(strikes.length, atmIdx + strikeWindow + 1);
    return strikes.slice(start, end);
  }, [strikes, atmStrike, strikeWindow]);

  const legCountsByStrikeType = useMemo(() => {
    const map: Record<string, number> = {};
    for (const leg of legs) {
      if (leg.status !== "OPEN" || leg.expiry !== selectedChainExpiry || leg.strike == null) continue;
      const key = `${leg.strike}:${leg.option_type}`;
      map[key] = (map[key] ?? 0) + leg.lots;
    }
    return map;
  }, [legs, selectedChainExpiry]);

  const handleAddLeg = useCallback(
    (strike: number, optionType: "CE" | "PE", side: OptionSide) => {
      const row = useMarketStore.getState().rowsByStrike[strike];
      if (!row || !selectedChainExpiry) return;
      const isCall = optionType === "CE";
      addLeg({
        leg_id: crypto.randomUUID(),
        contract_id: isCall ? row.ce_contract_id : row.pe_contract_id,
        symbol,
        exchange,
        expiry: selectedChainExpiry,
        strike,
        option_type: optionType,
        side,
        lots: defaultLots,
        lot_size: lotSize,
        entry_price: isCall ? row.ce_ltp : row.pe_ltp,
        entry_iv: (isCall ? row.ce_iv : row.pe_iv) / 100.0,
        forward_at_base: forwardPrice,
        enabled: true,
        status: "OPEN",
      });
    },
    [addLeg, defaultLots, exchange, forwardPrice, lotSize, selectedChainExpiry, symbol]
  );

  const handleAddFuture = (side: OptionSide) => {
    if (!futuresContractId || !selectedChainExpiry) return;
    addLeg({
      leg_id: crypto.randomUUID(),
      contract_id: futuresContractId,
      symbol,
      exchange,
      expiry: selectedChainExpiry,
      strike: null,
      option_type: "FUT",
      side,
      lots: defaultLots,
      lot_size: lotSize,
      entry_price: futuresPrice,
      entry_iv: 0,
      forward_at_base: forwardPrice,
      enabled: true,
      status: "OPEN",
    });
  };

  const scrollToAtm = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const atmRow = container.querySelector<HTMLElement>(`[data-strike="${atmStrike}"]`);
    if (atmRow) {
      atmRow.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  };

  return (
    <section className="flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-[#111827] dark:shadow-lg">
      {/* Option Chain Header Controls */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-[#0e1523]">
        <div className="flex items-center gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-800 dark:text-slate-200">
            Option Chain
          </h2>
          {isLoadingChain && (
            <span className="animate-pulse text-[11px] text-blue-600 dark:text-blue-400">
              Loading…
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Quick Futures B/S */}
          <div className="flex items-center gap-1 rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] dark:border-slate-700/80 dark:bg-slate-900">
            <span className="text-slate-500 dark:text-slate-400">FUT</span>
            <button
              type="button"
              onClick={() => handleAddFuture("BUY")}
              className="rounded bg-[#DCFCE7] px-1.5 py-0.5 text-[10px] font-bold text-[#15803D] hover:bg-[#16A34A] hover:text-white dark:bg-emerald-600/25 dark:text-emerald-300 dark:hover:bg-emerald-600"
            >
              B
            </button>
            <button
              type="button"
              onClick={() => handleAddFuture("SELL")}
              className="rounded bg-[#FEE2E2] px-1.5 py-0.5 text-[10px] font-bold text-[#B91C1C] hover:bg-[#DC2626] hover:text-white dark:bg-rose-600/25 dark:text-rose-300 dark:hover:bg-rose-600"
            >
              S
            </button>
          </div>

          {/* Default Lots Stepper */}
          <div className="flex items-center gap-1 rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] dark:border-slate-700 dark:bg-slate-900">
            <span className="text-slate-500 dark:text-slate-400">Lots</span>
            <button
              type="button"
              aria-label="Decrease default lots"
              onClick={() => setDefaultLots(defaultLots - 1)}
              className="rounded p-0.5 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <Minus className="h-3 w-3" />
            </button>
            <span className="min-w-[18px] text-center font-mono font-semibold text-slate-900 dark:text-white">
              {defaultLots}
            </span>
            <button
              type="button"
              aria-label="Increase default lots"
              onClick={() => setDefaultLots(defaultLots + 1)}
              className="rounded p-0.5 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <Plus className="h-3 w-3" />
            </button>
          </div>

          {/* Strike Window Filter */}
          <div className="flex items-center rounded border border-slate-300 bg-white p-0.5 text-[11px] dark:border-slate-700 dark:bg-slate-900">
            {([15, 25, 999] as StrikeWindow[]).map((win) => (
              <button
                key={win}
                type="button"
                onClick={() => setStrikeWindow(win)}
                className={`rounded px-1.5 py-0.5 font-medium ${
                  strikeWindow === win
                    ? "bg-blue-600 text-white"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                {win >= 999 ? "All" : `±${win}`}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={scrollToAtm}
            title="Center on ATM strike"
            className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-[11px] font-medium text-amber-700 hover:bg-amber-50 dark:border-slate-700 dark:bg-slate-900 dark:text-amber-300 dark:hover:bg-slate-800"
          >
            <Crosshair className="h-3 w-3" />
            <span>ATM</span>
          </button>
        </div>
      </div>

      {/* Scrollable Option Chain Table */}
      <div
        ref={scrollContainerRef}
        tabIndex={0}
        role="region"
        aria-label="Indian F&O Option Chain Table"
        className="terminal-scroll max-h-[600px] overflow-auto focus:outline-none"
      >
        <table className="w-full border-separate border-spacing-0 text-xs">
          <thead className="sticky top-0 z-20 bg-slate-100 text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:bg-[#0d1422] dark:text-slate-400">
            <tr>
              <th scope="col" className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                OI
              </th>
              <th scope="col" className="border-b border-slate-200 px-1.5 py-2 text-right dark:border-slate-800">
                IV
              </th>
              <th scope="col" className="border-b border-slate-200 px-1.5 py-2 text-right dark:border-slate-800">
                Δ
              </th>
              <th
                scope="col"
                className="border-b border-slate-200 px-2 py-2 text-right text-emerald-700 dark:border-slate-800 dark:text-emerald-400"
              >
                Call LTP
              </th>
              <th
                scope="col"
                className="border-x border-b border-slate-200 bg-slate-200/70 px-2.5 py-2 text-center text-slate-900 dark:border-slate-800 dark:bg-[#0a101b] dark:text-slate-200"
              >
                Strike
              </th>
              <th
                scope="col"
                className="border-b border-slate-200 px-2 py-2 text-left text-rose-700 dark:border-slate-800 dark:text-rose-400"
              >
                Put LTP
              </th>
              <th scope="col" className="border-b border-slate-200 px-1.5 py-2 text-left dark:border-slate-800">
                Δ
              </th>
              <th scope="col" className="border-b border-slate-200 px-1.5 py-2 text-left dark:border-slate-800">
                IV
              </th>
              <th scope="col" className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">
                OI
              </th>
            </tr>
          </thead>
          <tbody>
            {visibleStrikes.map((strike) => (
              <OptionChainRowItem
                key={strike}
                strike={strike}
                isAtm={strike === atmStrike}
                atmStrike={atmStrike}
                maxOi={maxOi}
                cePositionCount={legCountsByStrikeType[`${strike}:CE`] ?? 0}
                pePositionCount={legCountsByStrikeType[`${strike}:PE`] ?? 0}
                onAddLeg={handleAddLeg}
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
