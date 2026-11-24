"use client";

import { useEffect, useRef, useState } from "react";
import {
  ClipboardPaste,
  ExternalLink,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  Unplug,
  X,
} from "lucide-react";
import {
  disconnectDhan,
  generateDhanTotp,
  getDhanStatus,
  renewDhanToken,
  saveDhanToken,
} from "@/lib/api/client";
import { useMarketStore } from "@/stores/marketStore";
import { useUiStore } from "@/stores/uiStore";

type ModalTab = "paste" | "renew";

export function DhanConnectModal() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const activeDrawer = useUiStore((s) => s.activeDrawer);
  const setActiveDrawer = useUiStore((s) => s.setActiveDrawer);

  const symbol = useMarketStore((s) => s.symbol);
  const feedStatus = useMarketStore((s) => s.feedStatus);
  const dhanStatus = useMarketStore((s) => s.dhanStatus);
  const setDhanStatus = useMarketStore((s) => s.setDhanStatus);
  const loadChain = useMarketStore((s) => s.loadChain);

  const isOpen = activeDrawer === "dhan";

  const [tab, setTab] = useState<ModalTab>("paste");
  const [clientId, setClientId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [pin, setPin] = useState("");
  const [totp, setTotp] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      setFeedback(null);
      void getDhanStatus()
        .then((st) => setDhanStatus(st))
        .catch(() => undefined);
      if (!dialog.open) {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [isOpen, setDhanStatus]);

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
    setActiveDrawer(null);
  };

  const applyNewStatus = async (status: Awaited<ReturnType<typeof getDhanStatus>>, okMsg: string) => {
    setDhanStatus(status);
    setFeedback({ kind: "success", text: okMsg });
    await loadChain(symbol).catch(() => undefined);
  };

  const handlePasteFromClipboard = async () => {
    try {
      const clip = await navigator.clipboard.readText();
      if (clip.trim()) {
        setAccessToken(clip.trim());
        setFeedback({ kind: "success", text: "Pasted access token from clipboard." });
      }
    } catch {
      setFeedback({
        kind: "error",
        text: "Clipboard access denied — paste manually into the Access Token field.",
      });
    }
  };

  const handleSaveToken = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!clientId.trim() || !accessToken.trim()) {
      setFeedback({ kind: "error", text: "Client ID and Access Token are required." });
      return;
    }
    setIsSubmitting(true);
    setFeedback(null);
    try {
      const res = await saveDhanToken({
        client_id: clientId.trim(),
        access_token: accessToken.trim(),
      });
      setAccessToken("");
      await applyNewStatus(
        res,
        res.mode === "LIVE_DHAN"
          ? `Connected to DhanHQ Live (${res.account_name ?? res.client_id_masked ?? "Verified"})`
          : res.message ?? "Saved DhanHQ credentials."
      );
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to verify & save Dhan token.",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRenewToken = async () => {
    setIsSubmitting(true);
    setFeedback(null);
    try {
      const res = await renewDhanToken();
      await applyNewStatus(res, res.message ?? "Renewed DhanHQ access token for +24 hours.");
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to renew DhanHQ token.",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleGenerateTotp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!clientId.trim() || !pin.trim() || !totp.trim()) {
      setFeedback({ kind: "error", text: "Client ID, PIN, and 6-digit TOTP are required." });
      return;
    }
    setIsSubmitting(true);
    setFeedback(null);
    try {
      const res = await generateDhanTotp({
        client_id: clientId.trim(),
        pin: pin.trim(),
        totp: totp.trim(),
      });
      setPin("");
      setTotp("");
      await applyNewStatus(res, res.message ?? "Generated & activated fresh DhanHQ session.");
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "TOTP token generation failed.",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDisconnect = async () => {
    setIsSubmitting(true);
    setFeedback(null);
    try {
      const res = await disconnectDhan();
      await applyNewStatus(res, "Switched back to Offline Mock Market Feed.");
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to switch to Mock Mode.",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const effectiveMode = dhanStatus?.mode ?? feedStatus;

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby="dhan-connect-title"
      onClose={() => {
        if (dialogRef.current) dialogRef.current.returnValue = "";
        if (activeDrawer === "dhan") setActiveDrawer(null);
      }}
      className="m-auto w-full max-w-lg rounded-xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl dark:border-slate-700 dark:bg-[#111827] dark:text-slate-100"
    >
      <div className="flex items-start justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            <h1 id="dhan-connect-title" className="text-base font-semibold">
              DhanHQ v2.5 Live Feed & Paper Trading
            </h1>
          </div>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            Zero-latency live ticks for Paper Trading. Real-money orders remain disabled.
          </p>
        </div>
        <button
          type="button"
          onClick={handleClose}
          aria-label="Close Dhan API modal"
          className="rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-4 px-5 py-4">
        {/* Live Connection Status Banner */}
        <div
          className={`flex items-center justify-between rounded-lg border px-3 py-2 text-xs ${
            effectiveMode === "LIVE_DHAN"
              ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-950/30 dark:text-emerald-200"
              : effectiveMode === "TOKEN_EXPIRED"
                ? "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-500/40 dark:bg-rose-950/30 dark:text-rose-200"
                : "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
          }`}
        >
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 shrink-0" />
            <div>
              <div className="font-semibold">
                {effectiveMode === "LIVE_DHAN"
                  ? `Connected${dhanStatus?.account_name ? `: ${dhanStatus.account_name}` : ""}`
                  : effectiveMode === "TOKEN_EXPIRED"
                    ? "Daily Dhan Token Expired (Running on Mock Fallback)"
                    : "Offline Mock Feed Active"}
              </div>
              {dhanStatus?.client_id_masked && (
                <div className="text-[11px] opacity-80">
                  Client {dhanStatus.client_id_masked}
                  {typeof dhanStatus.seconds_remaining === "number" &&
                  dhanStatus.seconds_remaining > 0
                    ? ` · ${Math.floor(dhanStatus.seconds_remaining / 3600)}h ${Math.floor((dhanStatus.seconds_remaining % 3600) / 60)}m remaining`
                    : ""}
                </div>
              )}
            </div>
          </div>

          <button
            type="button"
            disabled={isSubmitting || effectiveMode === "MOCK_FALLBACK" || effectiveMode === "DISCONNECTED"}
            onClick={() => void handleDisconnect()}
            className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            <Unplug className="h-3 w-3" />
            <span>Switch to Mock</span>
          </button>
        </div>

        {/* Mode Tabs */}
        <div className="flex gap-1 rounded-lg border border-slate-200 bg-slate-100 p-1 text-xs font-medium dark:border-slate-800 dark:bg-slate-900">
          <button
            type="button"
            onClick={() => setTab("paste")}
            className={`flex-1 rounded-md py-1.5 transition-colors ${
              tab === "paste"
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
            }`}
          >
            Paste Daily Token
          </button>
          <button
            type="button"
            onClick={() => setTab("renew")}
            className={`flex-1 rounded-md py-1.5 transition-colors ${
              tab === "renew"
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
            }`}
          >
            Renew / TOTP Login
          </button>
        </div>

        {tab === "paste" ? (
          <form onSubmit={(e) => void handleSaveToken(e)} className="space-y-3 text-xs">
            <div className="flex items-center justify-between rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-[11px] text-blue-900 dark:border-blue-500/30 dark:bg-blue-950/30 dark:text-blue-200">
              <span>Generate your 24h access token from DhanHQ Web &rarr; Access DhanHQ APIs.</span>
              <a
                href="https://web.dhan.co"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex shrink-0 items-center gap-1 font-semibold underline"
              >
                <span>Open web.dhan.co</span>
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>

            <div>
              <label htmlFor="dhan-client-id" className="block font-medium text-slate-700 dark:text-slate-300">
                Dhan Client ID
              </label>
              <input
                id="dhan-client-id"
                type="text"
                autoFocus
                placeholder="e.g. 1100123456"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 font-mono text-sm text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="dhan-access-token" className="font-medium text-slate-700 dark:text-slate-300">
                  Daily Access Token (JWT)
                </label>
                <button
                  type="button"
                  onClick={() => void handlePasteFromClipboard()}
                  className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  <ClipboardPaste className="h-3 w-3" />
                  <span>Paste</span>
                </button>
              </div>
              <textarea
                id="dhan-access-token"
                rows={3}
                placeholder="eyJ0eXAiOiJKV1QiLC..."
                value={accessToken}
                onChange={(e) => setAccessToken(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 font-mono text-xs text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={handleClose}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="rounded-md bg-blue-600 px-3.5 py-1.5 font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
              >
                {isSubmitting ? "Verifying…" : "Save & Connect Live Feed"}
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-4 text-xs">
            <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/70">
              <div>
                <div className="font-semibold text-slate-800 dark:text-slate-200">
                  Extend Active Session (+24h)
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400">
                  Calls Dhan `/v2/RenewToken` using the currently stored token.
                </div>
              </div>
              <button
                type="button"
                disabled={isSubmitting || !dhanStatus?.connected}
                onClick={() => void handleRenewToken()}
                className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 font-semibold text-white hover:bg-emerald-500 disabled:opacity-40"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                <span>Renew +24h</span>
              </button>
            </div>

            <form onSubmit={(e) => void handleGenerateTotp(e)} className="space-y-3 border-t border-slate-200 pt-3 dark:border-slate-800">
              <div className="font-semibold text-slate-800 dark:text-slate-200">
                Or Generate via PIN + TOTP (PIN is never stored)
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label htmlFor="totp-client-id" className="block text-slate-600 dark:text-slate-400">
                    Client ID
                  </label>
                  <input
                    id="totp-client-id"
                    type="text"
                    autoFocus
                    placeholder="1100123456"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
                    className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label htmlFor="totp-pin" className="block text-slate-600 dark:text-slate-400">
                    6-Digit PIN
                  </label>
                  <input
                    id="totp-pin"
                    type="password"
                    inputMode="numeric"
                    placeholder="••••••"
                    value={pin}
                    onChange={(e) => setPin(e.target.value)}
                    className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label htmlFor="totp-code" className="block text-slate-600 dark:text-slate-400">
                    Authenticator TOTP
                  </label>
                  <input
                    id="totp-code"
                    type="text"
                    inputMode="numeric"
                    maxLength={8}
                    placeholder="123456"
                    value={totp}
                    onChange={(e) => setTotp(e.target.value)}
                    className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={handleClose}
                  className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="rounded-md bg-blue-600 px-3.5 py-1.5 font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
                >
                  {isSubmitting ? "Authenticating…" : "Generate & Connect"}
                </button>
              </div>
            </form>
          </div>
        )}

        {feedback && (
          <div
            className={`rounded-md border px-3 py-2 text-xs ${
              feedback.kind === "success"
                ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-950/30 dark:text-emerald-200"
                : "border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-500/40 dark:bg-rose-950/30 dark:text-rose-200"
            }`}
          >
            {feedback.text}
          </div>
        )}
      </div>
    </dialog>
  );
}

