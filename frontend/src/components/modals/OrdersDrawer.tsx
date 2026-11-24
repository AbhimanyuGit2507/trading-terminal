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
      className="m-auto w-full max-w-4xl rounded-xl border border-slate-200 bg-white p-5 text-slate-900 shadow-2xl dark:border-slate-700 dark:bg-[#111827] dark:text-slate-100"
    >
      <div className="flex items-center justify-between border-b border-slate-200 pb-3 dark:border-slate-800">
        <h1 id="orders-audit-title" className="text-base font-semibold text-slate-900 dark:text-white">
          Virtual Order Audit Ledger (Idempotent + Freeze-Sliced)
        </h1>
        <button
          type="button"
          autoFocus
          aria-label="Close order log"
          onClick={handleClose}
          className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="terminal-scroll mt-3 max-h-[440px] overflow-auto">
        {loading ? (
          <p className="py-8 text-center text-xs text-slate-500 dark:text-slate-400">
            Loading order ledger…
          </p>
        ) : orders.length === 0 ? (
          <p className="py-8 text-center text-xs text-slate-500 dark:text-slate-400">
            No orders logged yet. Click &ldquo;Log Order&rdquo; or exit a leg to test idempotent virtual fills.
          </p>
        ) : (
          <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
            <thead className="sticky top-0 bg-slate-100 text-[10px] uppercase text-slate-600 dark:bg-[#0d1422] dark:text-slate-400">
              <tr>
                <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">
                  Time
                </th>
                <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">
                  Contract
                </th>
                <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">
                  Action
                </th>
                <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">
                  Side
                </th>
                <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                  Qty (Lots)
                </th>
                <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                  Fill ₹
                </th>
                <th className="border-b border-slate-200 px-2 py-2 text-center dark:border-slate-800">
                  Slice
                </th>
                <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">
                  Idem Key
                </th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr
                  key={o.id}
                  className="border-b border-slate-200 hover:bg-slate-50 dark:border-slate-800/60 dark:hover:bg-slate-800/30"
                >
                  <td className="px-2 py-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                    {formatIstDateTime(o.executed_at)}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[11px] text-slate-800 dark:text-slate-200">
                    {o.contract_id}
                  </td>
                  <td className="px-2 py-1.5 text-[11px] text-slate-700 dark:text-slate-300">
                    {o.action}
                  </td>
                  <td className="px-2 py-1.5">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                        o.side === "BUY"
                          ? "bg-[#DCFCE7] text-[#15803D] dark:bg-emerald-600/20 dark:text-emerald-300"
                          : "bg-[#FEE2E2] text-[#B91C1C] dark:bg-rose-600/20 dark:text-rose-300"
                      }`}
                    >
                      {o.side}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-slate-800 dark:text-slate-200">
                    {o.quantity} ({o.lots}L)
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-slate-900 dark:text-slate-100">
                    {o.fill_price ?? "--"}
                  </td>
                  <td className="px-2 py-1.5 text-center text-[11px] text-slate-500 dark:text-slate-400">
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
