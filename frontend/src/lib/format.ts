export function formatInr(value: number, decimals = 0): string {
  const abs = Math.abs(value);
  const formatted = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(abs);
  const sign = value < 0 ? "-" : "";
  return `${sign}₹${formatted}`;
}

export function formatSignedInr(value: number, decimals = 2): string {
  const prefix = value > 0 ? "+" : value < 0 ? "-" : "";
  const formatted = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Math.abs(value));
  return `${prefix}₹${formatted}`;
}

export function formatCompactOi(oi: number): string {
  if (oi >= 10_000_000) return `${(oi / 10_000_000).toFixed(2)}Cr`;
  if (oi >= 100_000) return `${(oi / 100_000).toFixed(2)}L`;
  if (oi >= 1_000) return `${(oi / 1_000).toFixed(1)}K`;
  return String(oi);
}

export function formatIstDateTime(iso: string): string {
  if (!iso) return "--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d) + " IST";
}

export function formatShortExpiry(expiryIso: string): string {
  const parts = expiryIso.split("-");
  if (parts.length !== 3) return expiryIso;
  const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
  }).format(d);
}

