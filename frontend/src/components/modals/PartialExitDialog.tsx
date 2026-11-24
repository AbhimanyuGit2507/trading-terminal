"use client";

import { useEffect, useRef, useState } from "react";
import { formatSignedInr } from "@/lib/format";
import { useMarketStore } from "@/stores/marketStore";
import { useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";

export function PartialExitDialog() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const partialExitLegId = useUiStore((s) => s.partialExitLegId);
  const openPartialExitModal = useUiStore((s) => s.openPartialExitModal);

  const legs = useStrategyStore((s) => s.legs);
  const partialExitLeg = useStrategyStore((s) => s.partialExitLeg);
  const isExecuting = useStrategyStore((s) => s.isExecuting);
  const activeLegQuotes = useMarketStore((s) => s.activeLegQuotes);

  const leg = legs.find((l) => l.leg_id === partialExitLegId) ?? null;

  const [lotsToExit, setLotsToExit] = useState(1);
  const [exitPrice, setExitPrice] = useState("0");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (leg) {
      const liveLtp = activeLegQuotes[leg.contract_id]?.ltp ?? leg.entry_price;
      setLotsToExit(Math.max(1, Math.floor(leg.lots / 2) || 1));
      setExitPrice(liveLtp.toFixed(2));
      if (!dialog.open) {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [leg, activeLegQuotes]);

  // Light-dismiss fallback for browsers without HTMLDialogElement.closedBy
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;

    const isOutside = (e: PointerEvent) => {
      const r = dialog.getBoundingClientRect();
      return (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      );
    };

    let pressedOutside = false;
    const onDown = (e: PointerEvent) => {
      pressedOutside = isOutside(e);
    };
    const onUp = (e: PointerEvent) => {
      if (pressedOutside && isOutside(e)) dialog.close();
    };
    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("pointerup", onUp);
    return () => {
      dialog.removeEventListener("pointerdown", onDown);
      dialog.removeEventListener("pointerup", onUp);
    };
  }, []);

  const handleClose = () => {
    const dialog = dialogRef.current;
    if (dialog) {
      dialog.returnValue = "";
      if (dialog.open) dialog.close();
    }
    openPartialExitModal(null);
  };

  const parsedPx = Number(exitPrice) || 0;
  const estPnl = leg
    ? (leg.side === "BUY" ? parsedPx - leg.entry_price : leg.entry_price - parsedPx) *
      lotsToExit *
      leg.lot_size
    : 0;

  const handleConfirm = async () => {
    if (!leg) return;
    await partialExitLeg(leg.leg_id, lotsToExit, parsedPx);
    handleClose();
  };

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby="partial-exit-title"
      onClose={() => {
        if (dialogRef.current) dialogRef.current.returnValue = "";
        openPartialExitModal(null);
      }}
      className="m-auto w-full max-w-md rounded-xl border border-slate-700 bg-[#111827] p-5 text-slate-100 shadow-2xl"
    >
      {leg && (
        <div className="space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <h1 id="partial-exit-title" className="text-base font-semibold text-white">
                Partial / Full Leg Exit
              </h1>
              <p className="mt-0.5 text-xs text-slate-400 font-mono">
                {leg.side} {leg.strike ?? "FUT"} {leg.option_type} ({leg.expiry}) ·{" "}
                {leg.lots} lot(s) open
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <label htmlFor="exit-lots-input" className="block text-slate-400">
                Lots to Exit (max {leg.lots})
              </label>
              <input
                id="exit-lots-input"
                type="number"
                autoFocus
                min={1}
                max={leg.lots}
                value={lotsToExit}
                onChange={(e) =>
                  setLotsToExit(
                    Math.max(1, Math.min(leg.lots, Number(e.target.value) || 1))
                  )
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-sm text-white focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="exit-price-input" className="block text-slate-400">
                Exit Price (₹)
              </label>
              <input
                id="exit-price-input"
                type="number"
                step="0.05"
                min="0.05"
                value={exitPrice}
                onChange={(e) => setExitPrice(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-sm text-white focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-xs tabular-nums">
            <span className="text-slate-400">
              Projected Booked P&amp;L ({lotsToExit * leg.lot_size} qty):
            </span>
            <span
              className={`font-mono font-bold ${
                estPnl >= 0 ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {formatSignedInr(estPnl, 2)}
            </span>
          </div>

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={handleClose}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={isExecuting}
              onClick={() => void handleConfirm()}
              className="rounded-md bg-amber-500 px-3.5 py-1.5 text-xs font-semibold text-slate-950 hover:bg-amber-400 disabled:opacity-50"
            >
              {isExecuting ? "Executing…" : "Confirm Exit"}
            </button>
          </div>
        </div>
      )}
    </dialog>
  );
}

