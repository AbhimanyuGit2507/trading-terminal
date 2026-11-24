"use client";

import { useEffect, useRef, useState } from "react";
import { LockOpen, ShieldAlert, X } from "lucide-react";
import { formatInr } from "@/lib/format";
import { useMarketStore } from "@/stores/marketStore";
import { useRiskStore } from "@/stores/riskStore";
import { useUiStore } from "@/stores/uiStore";

export function SafetyGuardModals() {
  const liveDialogRef = useRef<HTMLDialogElement>(null);
  const unlockDialogRef = useRef<HTMLDialogElement>(null);

  const liveModeConfirmOpen = useUiStore((s) => s.liveModeConfirmOpen);
  const setLiveModeConfirmOpen = useUiStore((s) => s.setLiveModeConfirmOpen);
  const killUnlockModalOpen = useUiStore((s) => s.killUnlockModalOpen);
  const setKillUnlockModalOpen = useUiStore((s) => s.setKillUnlockModalOpen);

  const dhanStatus = useMarketStore((s) => s.dhanStatus);
  const riskState = useRiskStore((s) => s.riskState);
  const egressIp = useRiskStore((s) => s.egressIp);
  const requestModeSwitch = useRiskStore((s) => s.requestModeSwitch);
  const unlockKillSwitch = useRiskStore((s) => s.unlockKillSwitch);

  const [unlockText, setUnlockText] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const dialog = liveDialogRef.current;
    if (!dialog) return;
    if (liveModeConfirmOpen) {
      setErrorMsg(null);
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [liveModeConfirmOpen]);

  useEffect(() => {
    const dialog = unlockDialogRef.current;
    if (!dialog) return;
    if (killUnlockModalOpen) {
      setUnlockText("");
      setErrorMsg(null);
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [killUnlockModalOpen]);

  const handleConfirmLiveMode = async () => {
    setSubmitting(true);
    setErrorMsg(null);
    const res = await requestModeSwitch("DHAN_LIVE", true);
    setSubmitting(false);
    if (res.ok) {
      if (liveDialogRef.current?.open) liveDialogRef.current.close();
      setLiveModeConfirmOpen(false);
    } else {
      setErrorMsg(res.error ?? "Unable to activate DHAN_LIVE mode.");
    }
  };

  const handleConfirmUnlock = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setErrorMsg(null);
    const res = await unlockKillSwitch(unlockText);
    setSubmitting(false);
    if (res.ok) {
      if (unlockDialogRef.current?.open) unlockDialogRef.current.close();
      setKillUnlockModalOpen(false);
    } else {
      setErrorMsg(res.error ?? "Invalid unlock phrase.");
    }
  };

  return (
    <>
      {/* 1. Explicit DHAN_LIVE Switch Confirmation Modal */}
      <dialog
        ref={liveDialogRef}
        closedby="any"
        aria-labelledby="live-switch-title"
        onClose={() => {
          if (liveDialogRef.current) liveDialogRef.current.returnValue = "";
          if (liveModeConfirmOpen) setLiveModeConfirmOpen(false);
        }}
        className="m-auto w-full max-w-md rounded-xl border border-rose-400 bg-white p-0 text-slate-900 shadow-2xl dark:border-rose-700 dark:bg-[#111827] dark:text-slate-100"
      >
        <div className="flex items-center justify-between bg-rose-600 px-5 py-3 text-white">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5" />
            <h1 id="live-switch-title" className="text-sm font-bold">
              Switch to DhanHQ LIVE Real-Money Mode
            </h1>
          </div>
          <button
            type="button"
            onClick={() => {
              liveDialogRef.current?.close();
              setLiveModeConfirmOpen(false);
            }}
            aria-label="Close confirmation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4 text-xs">
          <p className="text-slate-700 dark:text-slate-300">
            Verify your DhanHQ account, Daily Max-Loss Limit, and SEBI Static Egress IP before unlocking real-money order routing:
          </p>

          <div className="space-y-1.5 rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono dark:border-slate-800 dark:bg-slate-900">
            <div className="flex justify-between">
              <span className="text-slate-500">Active UCC:</span>
              <span className="font-semibold text-slate-900 dark:text-white">
                {dhanStatus?.ucc ?? dhanStatus?.client_id_masked ?? "Not connected"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Backend Daily Max Loss:</span>
              <span className="font-semibold text-rose-600 dark:text-rose-400">
                {formatInr(riskState?.daily_max_loss_inr ?? 25000)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Backend Egress IP:</span>
              <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                {egressIp?.public_ip ?? "Unavailable"}
              </span>
            </div>
          </div>

          {errorMsg && (
            <div className="rounded border border-rose-300 bg-rose-50 px-3 py-2 text-rose-800 dark:border-rose-500/40 dark:bg-rose-950/40 dark:text-rose-200">
              {errorMsg}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => {
                liveDialogRef.current?.close();
                setLiveModeConfirmOpen(false);
              }}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
            >
              Stay Safe (Cancel)
            </button>
            <button
              type="button"
              autoFocus
              disabled={submitting}
              onClick={() => void handleConfirmLiveMode()}
              className="rounded-md bg-rose-600 px-3.5 py-1.5 font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
            >
              {submitting ? "Enabling…" : "I Confirm — Enable DHAN LIVE"}
            </button>
          </div>
        </div>
      </dialog>

      {/* 2. Kill Switch Typed Unlock Modal */}
      <dialog
        ref={unlockDialogRef}
        closedby="any"
        aria-labelledby="kill-unlock-title"
        onClose={() => {
          if (unlockDialogRef.current) unlockDialogRef.current.returnValue = "";
          if (killUnlockModalOpen) setKillUnlockModalOpen(false);
        }}
        className="m-auto w-full max-w-md rounded-xl border border-amber-400 bg-white p-0 text-slate-900 shadow-2xl dark:border-amber-700 dark:bg-[#111827] dark:text-slate-100"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <LockOpen className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            <h1 id="kill-unlock-title" className="text-sm font-bold">
              Unlock Daily Kill Switch
            </h1>
          </div>
          <button
            type="button"
            onClick={() => {
              unlockDialogRef.current?.close();
              setKillUnlockModalOpen(false);
            }}
            aria-label="Close unlock dialog"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={(e) => void handleConfirmUnlock(e)} className="space-y-3 px-5 py-4 text-xs">
          <p className="text-slate-600 dark:text-slate-300">
            Reason engaged: <span className="font-semibold">{riskState?.kill_switch_reason ?? "Emergency Kill Switch triggered"}</span>
          </p>
          <div>
            <label htmlFor="unlock-phrase-input" className="block font-medium text-slate-700 dark:text-slate-300">
              Type <span className="font-mono font-bold">UNLOCK</span> to re-enable order execution
            </label>
            <input
              id="unlock-phrase-input"
              type="text"
              autoFocus
              value={unlockText}
              onChange={(e) => setUnlockText(e.target.value)}
              placeholder="UNLOCK"
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 font-mono text-sm uppercase text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </div>

          {errorMsg && (
            <div className="rounded border border-rose-300 bg-rose-50 px-3 py-2 text-rose-800 dark:border-rose-500/40 dark:bg-rose-950/40 dark:text-rose-200">
              {errorMsg}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                unlockDialogRef.current?.close();
                setKillUnlockModalOpen(false);
              }}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || unlockText.trim().toUpperCase() !== "UNLOCK"}
              className="rounded-md bg-amber-600 px-3.5 py-1.5 font-semibold text-white hover:bg-amber-500 disabled:opacity-40"
            >
              {submitting ? "Unlocking…" : "Unlock Execution"}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}

