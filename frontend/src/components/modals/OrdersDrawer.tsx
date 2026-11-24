"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import {
  getDhanBrokerOrders,
  getDhanPositions,
  listOrders,
  reconcileDhanOrders,
} from "@/lib/api/client";
import type { BrokerOrderRecord, BrokerPositionRecord, OrderAuditLog } from "@/lib/api/types";
import { formatIstDateTime, formatSignedInr } from "@/lib/format";
import { useRiskStore } from "@/stores/riskStore";
import { useUiStore } from "@/stores/uiStore";

type DrawerTab = "audit" | "broker";

export function OrdersDrawer() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const activeDrawer = useUiStore((s) => s.activeDrawer);
  const setActiveDrawer = useUiStore((s) => s.setActiveDrawer);
  const executionMode = useRiskStore((s) => s.executionMode);

  const [tab, setTab] = useState<DrawerTab>("audit");
  const [orders, setOrders] = useState<OrderAuditLog[]>([]);
  const [brokerOrders, setBrokerOrders] = useState<BrokerOrderRecord[]>([]);
  const [positions, setPositions] = useState<BrokerPositionRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [brokerError, setBrokerError] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);

  const isOpen = activeDrawer === "orders";
  const env: "SANDBOX" | "LIVE" = executionMode === "DHAN_LIVE" ? "LIVE" : "SANDBOX";

  const refreshBrokerData = async () => {
    setLoading(true);
    setBrokerError(null);
    try {
      const [pos, ord] = await Promise.all([
        getDhanPositions(env),
        getDhanBrokerOrders(env),
      ]);
      setPositions(pos);
      setBrokerOrders(ord);
    } catch (err) {
      setBrokerError(
        err instanceof Error ? err.message : "Connect DhanHQ credentials to view live positions."
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      if (!dialog.open) dialog.showModal();
      setLoading(true);
      setSyncNotice(null);
      if (tab === "audit") {
        listOrders(undefined, 100)
          .then(setOrders)
          .finally(() => setLoading(false));
      } else {
        void refreshBrokerData();
      }
    } else if (dialog.open) {
      dialog.close();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, tab]);

  const handleSyncReconcile = async () => {
    setLoading(true);
    setBrokerError(null);
    try {
      const res = await reconcileDhanOrders(env);
      setBrokerOrders(res.orders);
      setPositions(res.positions);
      setSyncNotice(`Synced ${res.orders.length} broker orders (${res.updated_orders} local updated).`);
    } catch (err) {
      setBrokerError(err instanceof Error ? err.message : "Reconciliation failed");
    } finally {
      setLoading(false);
    }
  };

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
      className="m-auto w-full max-w-5xl rounded-xl border border-slate-200 bg-white p-5 text-slate-900 shadow-2xl dark:border-slate-700 dark:bg-[#111827] dark:text-slate-100"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <h1 id="orders-audit-title" className="text-base font-semibold text-slate-900 dark:text-white">
            Orders &amp; Broker Positions
          </h1>
          <div className="flex items-center rounded-md border border-slate-200 bg-slate-100 p-0.5 text-xs font-medium dark:border-slate-700 dark:bg-slate-900">
            <button
              type="button"
              onClick={() => setTab("audit")}
              className={`rounded px-2.5 py-1 ${
                tab === "audit"
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white"
                  : "text-slate-600 dark:text-slate-400"
              }`}
            >
              Audit Ledger
            </button>
            <button
              type="button"
              onClick={() => setTab("broker")}
              className={`rounded px-2.5 py-1 ${
                tab === "broker"
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white"
                  : "text-slate-600 dark:text-slate-400"
              }`}
            >
              Broker Positions ({env})
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {tab === "broker" && (
            <button
              type="button"
              disabled={loading}
              onClick={() => void handleSyncReconcile()}
              className="inline-flex items-center gap-1 rounded border border-blue-300 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50 dark:border-blue-500/40 dark:bg-blue-950/30 dark:text-blue-300"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Sync / Reconcile</span>
            </button>
          )}
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
      </div>

      {syncNotice && (
        <div className="mt-2 rounded border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-950/30 dark:text-emerald-200">
          {syncNotice}
        </div>
      )}

      {tab === "audit" ? (
        <div className="terminal-scroll mt-3 max-h-[440px] overflow-auto">
          {loading ? (
            <p className="py-8 text-center text-xs text-slate-500 dark:text-slate-400">
              Loading order ledger…
            </p>
          ) : orders.length === 0 ? (
            <p className="py-8 text-center text-xs text-slate-500 dark:text-slate-400">
              No orders logged yet. Click &ldquo;Log Order&rdquo; or &ldquo;Execute Strategy&rdquo; to see idempotent fills.
            </p>
          ) : (
            <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
              <thead className="sticky top-0 bg-slate-100 text-[10px] uppercase text-slate-600 dark:bg-[#0d1422] dark:text-slate-400">
                <tr>
                  <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">Time</th>
                  <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">Mode</th>
                  <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">Contract</th>
                  <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">Side</th>
                  <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">Qty (Lots)</th>
                  <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">Fill ₹</th>
                  <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">Status / Broker ID</th>
                  <th className="border-b border-slate-200 px-2 py-2 text-center dark:border-slate-800">Slice</th>
                  <th className="border-b border-slate-200 px-2 py-2 text-left dark:border-slate-800">Idem Key</th>
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
                    <td className="px-2 py-1.5 text-[10px] font-semibold text-slate-600 dark:text-slate-300">
                      {o.trading_mode}
                      {o.is_super_order ? " · SUPER" : ""}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[11px] text-slate-800 dark:text-slate-200">
                      {o.contract_id}
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
                    <td className="px-2 py-1.5 text-[11px]">
                      <span className="font-semibold">{o.status}</span>
                      {o.broker_order_id && (
                        <span className="ml-1 font-mono text-[10px] text-slate-500">
                          #{o.broker_order_id}
                        </span>
                      )}
                      {o.oms_error && (
                        <div className="max-w-[200px] truncate text-[10px] text-rose-600 dark:text-rose-400" title={o.oms_error}>
                          {o.oms_error}
                        </div>
                      )}
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
      ) : (
        <div className="terminal-scroll mt-3 max-h-[440px] space-y-4 overflow-auto text-xs">
          {brokerError && (
            <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900 dark:border-amber-500/40 dark:bg-amber-950/30 dark:text-amber-200">
              {brokerError}
            </div>
          )}

          <div>
            <h2 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Dhan Open &amp; Day Positions ({positions.length})
            </h2>
            {positions.length === 0 ? (
              <p className="rounded border border-dashed border-slate-200 py-4 text-center text-slate-500 dark:border-slate-800">
                No broker positions returned for {env}.
              </p>
            ) : (
              <table className="w-full border border-slate-200 text-xs tabular-nums dark:border-slate-800">
                <thead className="bg-slate-100 text-[10px] uppercase text-slate-600 dark:bg-slate-900 dark:text-slate-400">
                  <tr>
                    <th className="px-2 py-1.5 text-left">Symbol</th>
                    <th className="px-2 py-1.5 text-left">Prod</th>
                    <th className="px-2 py-1.5 text-right">Net Qty</th>
                    <th className="px-2 py-1.5 text-right">Buy Avg</th>
                    <th className="px-2 py-1.5 text-right">Sell Avg</th>
                    <th className="px-2 py-1.5 text-right">MTM ₹</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p, idx) => {
                    const mtm = p.realized_profit + p.unrealized_profit;
                    return (
                      <tr key={`${p.security_id}-${idx}`} className="border-t border-slate-200 dark:border-slate-800">
                        <td className="px-2 py-1.5 font-mono font-semibold">{p.trading_symbol}</td>
                        <td className="px-2 py-1.5">{p.product_type}</td>
                        <td className="px-2 py-1.5 text-right font-mono">{p.net_qty}</td>
                        <td className="px-2 py-1.5 text-right font-mono">{p.buy_avg.toFixed(2)}</td>
                        <td className="px-2 py-1.5 text-right font-mono">{p.sell_avg.toFixed(2)}</td>
                        <td
                          className={`px-2 py-1.5 text-right font-mono font-semibold ${
                            mtm >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                          }`}
                        >
                          {formatSignedInr(mtm)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          <div>
            <h2 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Dhan Orderbook ({brokerOrders.length})
            </h2>
            {brokerOrders.length === 0 ? (
              <p className="rounded border border-dashed border-slate-200 py-4 text-center text-slate-500 dark:border-slate-800">
                No broker orders returned for {env}.
              </p>
            ) : (
              <table className="w-full border border-slate-200 text-xs tabular-nums dark:border-slate-800">
                <thead className="bg-slate-100 text-[10px] uppercase text-slate-600 dark:bg-slate-900 dark:text-slate-400">
                  <tr>
                    <th className="px-2 py-1.5 text-left">Order ID</th>
                    <th className="px-2 py-1.5 text-left">Symbol / SecID</th>
                    <th className="px-2 py-1.5 text-left">Side</th>
                    <th className="px-2 py-1.5 text-right">Qty</th>
                    <th className="px-2 py-1.5 text-right">Avg Px</th>
                    <th className="px-2 py-1.5 text-left">Status / OMS Msg</th>
                  </tr>
                </thead>
                <tbody>
                  {brokerOrders.map((bo) => (
                    <tr key={bo.order_id} className="border-t border-slate-200 dark:border-slate-800">
                      <td className="px-2 py-1.5 font-mono">{bo.order_id}</td>
                      <td className="px-2 py-1.5 font-mono">
                        {bo.trading_symbol || `${bo.exchange_segment}:${bo.security_id}`}
                        {bo.is_super_order ? " (SUPER)" : ""}
                      </td>
                      <td className="px-2 py-1.5 font-bold">{bo.transaction_type}</td>
                      <td className="px-2 py-1.5 text-right font-mono">
                        {bo.filled_qty}/{bo.quantity}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono">
                        {(bo.average_traded_price || bo.price).toFixed(2)}
                      </td>
                      <td className="px-2 py-1.5">
                        <span className="font-semibold">{bo.order_status}</span>
                        {bo.oms_error_description && (
                          <div className="text-[10px] text-rose-600 dark:text-rose-400">
                            {bo.oms_error_description}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </dialog>
  );
}
