"use client";

import { useEffect, useRef, useState } from "react";
import { Trash2, X } from "lucide-react";
import { deleteStrategy, listStrategies } from "@/lib/api/client";
import type { StrategyResponse } from "@/lib/api/types";
import { formatIstDateTime, formatSignedInr } from "@/lib/format";
import { useMarketStore } from "@/stores/marketStore";
import { useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";

export function StrategiesDrawer() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const activeDrawer = useUiStore((s) => s.activeDrawer);
  const setActiveDrawer = useUiStore((s) => s.setActiveDrawer);
  const loadSavedStrategy = useStrategyStore((s) => s.loadSavedStrategy);
  const loadChain = useMarketStore((s) => s.loadChain);
  const currentSymbol = useMarketStore((s) => s.symbol);

  const [items, setItems] = useState<StrategyResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isOpen = activeDrawer === "strategies";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      if (!dialog.open) dialog.showModal();
      setLoading(true);
      setError(null);
      listStrategies()
        .then(setItems)
        .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
        .finally(() => setLoading(false));
    } else if (dialog.open) {
      dialog.close();
    }
  }, [isOpen]);

  const handleClose = () => {
    if (dialogRef.current) {
      dialogRef.current.returnValue = "";
      if (dialogRef.current.open) dialogRef.current.close();
    }
    setActiveDrawer(null);
  };

  const handleLoad = async (strat: StrategyResponse) => {
    if (strat.symbol !== currentSymbol) {
      await loadChain(strat.symbol);
    }
    loadSavedStrategy(strat);
    handleClose();
  };

  const handleDelete = async (id: string) => {
    await deleteStrategy(id);
    setItems((prev) => prev.filter((item) => item.id !== id));
  };

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby="saved-strategies-title"
      onClose={() => {
        if (dialogRef.current) dialogRef.current.returnValue = "";
        if (activeDrawer === "strategies") setActiveDrawer(null);
      }}
      className="m-auto w-full max-w-2xl rounded-xl border border-slate-700 bg-[#111827] p-5 text-slate-100 shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <h1 id="saved-strategies-title" className="text-base font-semibold text-white">
          Saved Strategies (PostgreSQL)
        </h1>
        <button
          type="button"
          autoFocus
          aria-label="Close saved strategies"
          onClick={handleClose}
          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="terminal-scroll mt-3 max-h-[420px] space-y-2 overflow-auto">
        {loading && <p className="py-6 text-center text-xs text-slate-400">Loading strategies…</p>}
        {error && <p className="py-4 text-center text-xs text-rose-400">{error}</p>}
        {!loading && !error && items.length === 0 && (
          <p className="py-8 text-center text-xs text-slate-400">
            No saved strategies yet. Click Save in the Builder panel to persist one.
          </p>
        )}

        {items.map((strat) => (
          <div
            key={strat.id}
            className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-[#0d1422] px-3 py-2.5 text-xs"
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-slate-100">{strat.name}</span>
                <span className="rounded bg-blue-600/20 px-1.5 py-0.5 text-[10px] font-semibold text-blue-300">
                  {strat.symbol}
                </span>
                <span className="text-[10px] text-slate-400">
                  {strat.legs.length} open leg(s)
                </span>
              </div>
              <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-400 tabular-nums">
                <span>Updated: {formatIstDateTime(strat.updated_at)}</span>
                <span>
                  Realized:{" "}
                  <strong
                    className={
                      Number(strat.realized_pnl) >= 0 ? "text-emerald-400" : "text-rose-400"
                    }
                  >
                    {formatSignedInr(Number(strat.realized_pnl), 0)}
                  </strong>
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void handleLoad(strat)}
                className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-500"
              >
                Load
              </button>
              <button
                type="button"
                aria-label={`Delete ${strat.name}`}
                onClick={() => void handleDelete(strat.id)}
                className="rounded-md border border-slate-700 p-1.5 text-slate-400 hover:bg-rose-600/20 hover:text-rose-400"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </dialog>
  );
}
