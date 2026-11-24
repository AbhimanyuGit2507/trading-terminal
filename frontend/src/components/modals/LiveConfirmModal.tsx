"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ShieldAlert, ShieldCheck, X, Zap } from "lucide-react";
import { executeOrders } from "@/lib/api/client";
import type { OptionSide } from "@/lib/api/types";
import { formatInr } from "@/lib/format";
import { estimateLegCharges } from "@/lib/quant/charges";
import { useMarketStore } from "@/stores/marketStore";
import { useRiskStore } from "@/stores/riskStore";
import { getEffectiveLegs, useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";

export function LiveConfirmModal() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const isOpen = useUiStore((s) => s.liveOrderTicketOpen);
  const setOpen = useUiStore((s) => s.setLiveOrderTicketOpen);

  const executionMode = useRiskStore((s) => s.executionMode);
  const productType = useRiskStore((s) => s.productType);
  const setProductType = useRiskStore((s) => s.setProductType);
  const orderType = useRiskStore((s) => s.orderType);
  const setOrderType = useRiskStore((s) => s.setOrderType);
  const limitBufferTicks = useRiskStore((s) => s.limitBufferTicks);
  const setLimitBufferTicks = useRiskStore((s) => s.setLimitBufferTicks);
  const funds = useRiskStore((s) => s.funds);
  const loadFunds = useRiskStore((s) => s.loadFunds);
  const riskState = useRiskStore((s) => s.riskState);

  const legs = useStrategyStore((s) => s.legs);
  const lotMultiplier = useStrategyStore((s) => s.lotMultiplier);
  const margin = useStrategyStore((s) => s.margin);
  const strategyId = useStrategyStore((s) => s.strategyId);
  const setLastExecutionNotice = useStrategyStore((s) => s.setLastExecutionNotice);

  const symbol = useMarketStore((s) => s.symbol);
  const asOfIso = useMarketStore((s) => s.asOfIso);
  const activeLegQuotes = useMarketStore((s) => s.activeLegQuotes);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const isLive = executionMode === "DHAN_LIVE";
  const env: "SANDBOX" | "LIVE" = isLive ? "LIVE" : "SANDBOX";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      setErrorMsg(null);
      void loadFunds(env);
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [isOpen, env, loadFunds]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
    const isOutside = (e: PointerEvent) => {
      const r = dialog.getBoundingClientRect();
      return (
        e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom
      );
    };
    let downOutside = false;
    const onDown = (e: PointerEvent) => {
      downOutside = isOutside(e);
    };
    const onUp = (e: PointerEvent) => {
      if (downOutside && isOutside(e)) dialog.close();
    };
    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("pointerup", onUp);
    return () => {
      dialog.removeEventListener("pointerdown", onDown);
      dialog.removeEventListener("pointerup", onUp);
    };
  }, []);

  const openLegs = useMemo(() => {
    const active = getEffectiveLegs(
      legs.filter((l) => l.status === "OPEN" && l.enabled),
      lotMultiplier
    );
    // Margin-safe execution order: BUY (hedge) legs first, then SELL (short) legs
    const buys = active.filter((l) => l.side === "BUY");
    const sells = active.filter((l) => l.side === "SELL");
    return [...buys, ...sells];
  }, [legs, lotMultiplier]);

  const estCharges = useMemo(
    () =>
      openLegs.reduce((sum, leg) => {
        const q = activeLegQuotes[leg.contract_id];
        const px = q ? (leg.side === "BUY" ? q.ask || q.ltp : q.bid || q.ltp) : leg.entry_price;
        return (
          sum +
          estimateLegCharges(
            px,
            leg.lots * leg.lot_size,
            leg.side as OptionSide,
            leg.option_type,
            leg.exchange
          )
        );
      }, 0),
    [openLegs, activeLegQuotes]
  );
  const estMargin = margin?.total_margin ?? 0;
  const availableBal = funds?.available_balance ?? null;
  const insufficientFunds = availableBal !== null && estMargin > 0 && availableBal < estMargin;
  const killBlocked = Boolean(riskState?.daily_kill_switch_active);

  const handleClose = () => {
    if (dialogRef.current) {
      dialogRef.current.returnValue = "";
      if (dialogRef.current.open) dialogRef.current.close();
    }
    setOpen(false);
  };

  const handleConfirmExecute = async () => {
    if (openLegs.length === 0) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await executeOrders({
        strategy_id: strategyId,
        trading_mode: isLive ? "DHAN_LIVE" : "DHAN_SANDBOX",
        action: "OPEN_LEGS",
        product_type: productType,
        order_type: orderType,
        limit_buffer_ticks: limitBufferTicks,
        slice_if_frozen: true,
        as_of: asOfIso || null,
        legs: openLegs.map((leg) => {
          const q = activeLegQuotes[leg.contract_id];
          const basePx = q
            ? leg.side === "BUY"
              ? q.ask || q.ltp
              : q.bid || q.ltp
            : leg.entry_price;
          const buf = orderType === "LIMIT" ? limitBufferTicks * 0.05 : 0;
          const px = leg.side === "BUY" ? basePx + buf : Math.max(0.05, basePx - buf);
          return {
            leg_id: leg.leg_id,
            contract_id: leg.contract_id,
            side: leg.side as OptionSide,
            lots: leg.lots,
            lot_size: leg.lot_size,
            limit_price: orderType === "MARKET" ? null : px.toFixed(2),
            product_type: leg.product_type ?? productType,
            order_type: orderType,
            target_price: leg.target_price != null ? String(leg.target_price) : null,
            stop_loss_price: leg.stop_loss_price != null ? String(leg.stop_loss_price) : null,
            trailing_jump: leg.trailing_jump != null ? String(leg.trailing_jump) : null,
          };
        }),
      });
      const fillCount = res.fills.length;
      setLastExecutionNotice(
        `${isLive ? "DHAN LIVE" : "DHAN SANDBOX"} basket submitted (${fillCount} order fill${fillCount === 1 ? "" : "s"}, id ${res.idempotency_key.slice(0, 8)}…)`
      );
      handleClose();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Execution rejected");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby="live-ticket-title"
      onClose={() => {
        if (dialogRef.current) dialogRef.current.returnValue = "";
        if (isOpen) setOpen(false);
      }}
      className="m-auto w-full max-w-2xl rounded-xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl dark:border-slate-700 dark:bg-[#111827] dark:text-slate-100"
    >
      {/* Mode Warning Banner */}
      <div
        className={`flex items-center justify-between border-b px-5 py-3.5 ${
          isLive
            ? "border-rose-300 bg-rose-600 text-white dark:border-rose-700"
            : "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-600/40 dark:bg-amber-950/50 dark:text-amber-200"
        }`}
      >
        <div className="flex items-center gap-2">
          {isLive ? <ShieldAlert className="h-5 w-5" /> : <Zap className="h-5 w-5 text-amber-600 dark:text-amber-400" />}
          <div>
            <h1 id="live-ticket-title" className="text-sm font-bold tracking-tight">
              {isLive
                ? "REAL-MONEY ORDER TICKET — DHANHQ LIVE"
                : "SANDBOX TEST ORDER TICKET — DHANHQ SANDBOX"}
            </h1>
            <p className={`text-[11px] ${isLive ? "text-rose-100" : "opacity-80"}`}>
              Margin-safe basket routing: BUY hedge legs execute first and confirm TRADED before SELL legs fire.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleClose}
          aria-label="Close order ticket"
          className="rounded p-1 opacity-80 hover:opacity-100"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-4 px-5 py-4 text-xs">
        {/* Product / Order Type Controls */}
        <div className="grid grid-cols-3 gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
          <div>
            <label htmlFor="ticket-product" className="block text-[10px] font-semibold uppercase text-slate-500 dark:text-slate-400">
              Product Type
            </label>
            <select
              id="ticket-product"
              value={productType}
              onChange={(e) => setProductType(e.target.value as "MARGIN" | "INTRADAY")}
              className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 font-medium text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            >
              <option value="MARGIN">NRML / MARGIN</option>
              <option value="INTRADAY">MIS / INTRADAY</option>
            </select>
          </div>

          <div>
            <label htmlFor="ticket-ordertype" className="block text-[10px] font-semibold uppercase text-slate-500 dark:text-slate-400">
              Order Type
            </label>
            <select
              id="ticket-ordertype"
              value={orderType}
              onChange={(e) => setOrderType(e.target.value as "LIMIT" | "MARKET")}
              className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 font-medium text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            >
              <option value="LIMIT">LIMIT (+Buffer)</option>
              <option value="MARKET">MARKET</option>
            </select>
          </div>

          <div>
            <label htmlFor="ticket-buffer" className="block text-[10px] font-semibold uppercase text-slate-500 dark:text-slate-400">
              Limit Buffer (Ticks × ₹0.05)
            </label>
            <input
              id="ticket-buffer"
              type="number"
              min={0}
              max={50}
              disabled={orderType === "MARKET"}
              value={limitBufferTicks}
              onChange={(e) => setLimitBufferTicks(Number(e.target.value) || 0)}
              className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 font-mono text-slate-900 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            />
          </div>
        </div>

        {/* Ordered Basket Legs */}
        <div className="max-h-56 overflow-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-left text-xs tabular-nums">
            <thead className="bg-slate-100 text-[10px] uppercase text-slate-600 dark:bg-slate-900 dark:text-slate-400">
              <tr>
                <th className="px-2.5 py-2">Order</th>
                <th className="px-2.5 py-2">Contract</th>
                <th className="px-2.5 py-2 text-right">Qty</th>
                <th className="px-2.5 py-2 text-right">Est. Px</th>
                <th className="px-2.5 py-2">Super Order (SL / Tgt)</th>
              </tr>
            </thead>
            <tbody>
              {openLegs.map((leg) => {
                const q = activeLegQuotes[leg.contract_id];
                const px = q ? (leg.side === "BUY" ? q.ask || q.ltp : q.bid || q.ltp) : leg.entry_price;
                const isBuy = leg.side === "BUY";
                const hasSuper = leg.target_price != null || leg.stop_loss_price != null;
                return (
                  <tr key={leg.leg_id} className="border-t border-slate-200 dark:border-slate-800">
                    <td className="px-2.5 py-2">
                      <span
                        className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                          isBuy
                            ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-600/20 dark:text-emerald-300"
                            : "bg-rose-100 text-rose-800 dark:bg-rose-600/20 dark:text-rose-300"
                        }`}
                      >
                        {leg.side} {isBuy ? "· EXECUTES 1ST" : "· 2ND"}
                      </span>
                    </td>
                    <td className="px-2.5 py-2 font-mono font-semibold">
                      {symbol} {leg.strike ?? "FUT"} {leg.option_type} ({leg.expiry})
                    </td>
                    <td className="px-2.5 py-2 text-right font-mono">
                      {leg.lots * leg.lot_size} ({leg.lots}L)
                    </td>
                    <td className="px-2.5 py-2 text-right font-mono">
                      {orderType === "MARKET" ? "MKT" : `₹${px.toFixed(2)}`}
                    </td>
                    <td className="px-2.5 py-2 text-[11px]">
                      {hasSuper ? (
                        <span className="rounded bg-blue-50 px-1.5 py-0.5 font-mono text-blue-800 dark:bg-blue-950/50 dark:text-blue-300">
                          {leg.stop_loss_price != null ? `SL ${leg.stop_loss_price}` : ""}{" "}
                          {leg.target_price != null ? `TGT ${leg.target_price}` : ""}{" "}
                          {leg.trailing_jump != null ? `TRL ${leg.trailing_jump}` : ""}
                        </span>
                      ) : (
                        <span className="text-slate-400">Standard Order</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Margin vs Available Funds Summary */}
        <div className="grid grid-cols-3 gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 dark:border-slate-800 dark:bg-slate-900">
          <div>
            <div className="text-[10px] uppercase text-slate-500 dark:text-slate-400">Est. Margin</div>
            <div className="font-mono text-sm font-bold text-slate-900 dark:text-white">
              {formatInr(estMargin)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-slate-500 dark:text-slate-400">
              Dhan Available Funds ({env})
            </div>
            <div
              className={`font-mono text-sm font-bold ${
                insufficientFunds
                  ? "text-rose-600 dark:text-rose-400"
                  : "text-emerald-700 dark:text-emerald-400"
              }`}
            >
              {availableBal !== null ? formatInr(availableBal) : "Unable to fetch"}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-slate-500 dark:text-slate-400">Est. Charges</div>
            <div className="font-mono text-sm font-semibold text-slate-800 dark:text-slate-200">
              {formatInr(estCharges)}
            </div>
          </div>
        </div>

        {insufficientFunds && (
          <div className="flex items-center gap-2 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-rose-800 dark:border-rose-500/40 dark:bg-rose-950/40 dark:text-rose-200">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>
              Available Dhan balance is below estimated basket margin. Backend Risk Guard will reject insufficient funds.
            </span>
          </div>
        )}

        {killBlocked && (
          <div className="flex items-center gap-2 rounded-md border border-rose-400 bg-rose-100 px-3 py-2 font-semibold text-rose-900 dark:border-rose-500 dark:bg-rose-950/60 dark:text-rose-200">
            <ShieldAlert className="h-4 w-4 shrink-0" />
            <span>DAILY KILL SWITCH IS ACTIVE — Unlock it in TopBar before firing orders.</span>
          </div>
        )}

        {errorMsg && (
          <div className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-rose-800 dark:border-rose-500/40 dark:bg-rose-950/40 dark:text-rose-200">
            {errorMsg}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            Cancel
          </button>
          <button
            type="button"
            autoFocus
            disabled={isSubmitting || openLegs.length === 0 || killBlocked}
            onClick={() => void handleConfirmExecute()}
            className={`inline-flex items-center gap-1.5 rounded-md px-4 py-1.5 font-semibold text-white disabled:opacity-40 ${
              isLive
                ? "bg-rose-600 hover:bg-rose-500"
                : "bg-amber-600 hover:bg-amber-500"
            }`}
          >
            <ShieldCheck className="h-4 w-4" />
            <span>
              {isSubmitting
                ? "Routing to DhanHQ…"
                : isLive
                  ? "Confirm Real-Money Execution"
                  : "Submit to Dhan Sandbox"}
            </span>
          </button>
        </div>
      </div>
    </dialog>
  );
}
