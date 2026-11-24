import type { DhanStatusResponse, FeedStatus } from "@/lib/api/types";

export interface DhanPillPresentation {
  label: string;
  tone: "emerald" | "rose" | "amber" | "slate";
  title: string;
}

export function formatDhanPill(
  feedStatus: FeedStatus,
  dhanStatus: DhanStatusResponse | null,
  wsStatus: "connecting" | "connected" | "disconnected"
): DhanPillPresentation {
  const effectiveMode: FeedStatus = dhanStatus?.mode ?? feedStatus;

  if (effectiveMode === "LIVE_DHAN") {
    const secs = dhanStatus?.seconds_remaining;
    let timeSuffix = "Live";
    if (typeof secs === "number" && secs > 0) {
      const hours = Math.floor(secs / 3600);
      const mins = Math.floor((secs % 3600) / 60);
      timeSuffix = hours >= 1 ? `${hours}h left` : `${Math.max(1, mins)}m left`;
    }
    const accountLabel = dhanStatus?.account_name
      ? ` · ${dhanStatus.account_name}`
      : "";
    return {
      label: `Dhan Live (${timeSuffix})`,
      tone: wsStatus === "connected" ? "emerald" : "amber",
      title: `DhanHQ v2.5 Live Paper Mode${accountLabel} — WS ${wsStatus}. Click to manage token.`,
    };
  }

  if (effectiveMode === "TOKEN_EXPIRED") {
    return {
      label: "Token Expired — Paste Token",
      tone: "rose",
      title:
        dhanStatus?.message ??
        "DhanHQ daily access token expired. Click to paste or renew token.",
    };
  }

  return {
    label: "Mock Mode — Connect Dhan",
    tone: wsStatus === "connecting" ? "amber" : "slate",
    title:
      dhanStatus?.message ??
      `Simulated feed active (WS ${wsStatus}). Click to connect DhanHQ v2.5 live feed.`,
  };
}

