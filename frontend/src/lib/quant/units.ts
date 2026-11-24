export type PnlDisplayUnit = "INR" | "POINTS";

export function inrToPoints(inrValue: number, primaryLotSize: number): number {
  if (primaryLotSize <= 0) return inrValue;
  return Math.round((inrValue / primaryLotSize) * 100) / 100;
}

export function convertPnlByUnit(
  inrValue: number,
  unit: PnlDisplayUnit,
  primaryLotSize: number
): number {
  return unit === "POINTS" ? inrToPoints(inrValue, primaryLotSize) : inrValue;
}

