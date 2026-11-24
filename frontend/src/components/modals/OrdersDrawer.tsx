"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { listOrders } from "@/lib/api/client";
import type { OrderAuditLog } from "@/lib/api/types";
import { formatIstDateTime } from "@/lib/format";
import { useUiStore } from "@/stores/uiStore";

export function OrdersDrawer() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const activeDrawer = useUiStore((s) => s.activeDrawer);
  const setActiveDrawer = useUiStore((s) => s.setActiveDrawer);

  const [orders, setOrders] = useState<OrderAuditLog[]>([]);
  const [loading, setLoading] = useState(false);

  const isOpen = activeDrawer === "orders";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      if (!dialog.open) dialog.showModal();
      setLoading(true);
      listOrders(undefined, 100)
        .then(setOrders)
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

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby="orders-audit-title"
      onClose={() => {
        if (dialogRef.current) dialogRef.current.returnValue = "";
        if (activeDrawer === "orders") setActiveDrawer(null);
      }}
      className="m-auto w-full max-w-4xl rounded-xl border border-slate-700 bg-[#111827] p-5 text-slate-100 shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <h1 id="orders-audit-title" className="text-base font-semibold text-white">
          Virtual Order Audit Ledger (Idempotent + Freeze-Sliced)
        </h1>
        <button
          type="button"
          autoFocus
          aria-label="Close order log"
          onClick={handleClose}
          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="terminal-scroll mt-3 max-h-[440px] overflow-auto">
        {loading ? (
          <p className="py-8 text-center text-xs text-slate-400">Loading order ledger…</p>
        ) : orders.length === 0 ? (
          <p className="py-8 text-center text-xs text-slate-400">
            No orders logged yet. Click &ldquo;Log Order&rdquo; or exit a leg to test idempotent virtual fills.
          </p>
        ) : (
          <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
            <thead className="sticky top-0 bg-[#0d1422] text-[10px] uppercase text-slate-400">
              <tr>
                <th className="border-b border-slate-800 px-2 py-2 text-left">Time</th>
                <th className="border-b border-slate-800 px-2 py-2 text-left">Contract</th>
                <th className="border-b border-slate-800 px-2 py-2 text-left">Action</th>
                <th className="border-b border-slate-800 px-2 py-2 text-left">Side</th>
                <th className="border-b border-slate-800 px-2 py-2 text-right">Qty (Lots)</th>
                <th className="border-b border-slate-800 px-2 py-2 text-right">Fill ₹</th>
                <th className="border-b border-slate-800 px-2 py-2 text-center">Slice</th>
                <th className="border-b border-slate-800 px-2 py-2 text-left">Idem Key</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-2 py-1.5 text-[11px] text-slate-400">
                    {formatIstDateTime(o.executed_at)}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[11px] text-slate-200">
                    {o.contract_id}
                  </td>
                  <td className="px-2 py-1.5 text-[11px] text-slate-300">{o.action}</td>
                  <td className="px-2 py-1.5">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                        o.side === "BUY"
                          ? "bg-emerald-600/20 text-emerald-300"
                          : "bg-rose-600/20 text-rose-300"
                      }`}
                    >
                      {o.side}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {o.quantity} ({o.lots}L)
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-slate-100">
                    {o.fill_price ?? "--"}
                  </td>
                  <td className="px-2 py-1.5 text-center text-[11px] text-slate-400">
                    {o.total_slices > 1
                      ? o.slice_index === 0
                        ? `Parent (${o.total_slices})`
                        : `${o.slice_index}/${o.total_slices}`
                      : "1/1"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[10px] text-slate-500">
                    {o.idempotency_key.slice(0, 8)}…
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </dialog>
  );
}
