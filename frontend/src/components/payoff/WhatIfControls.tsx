"use client";

import type { CSSProperties } from "react";
import { RotateCcw } from "lucide-react";
import { formatIstDateTime } from "@/lib/format";
import { useMarketStore } from "@/stores/marketStore";
import { useStrategyStore } from "@/stores/strategyStore";

function sliderCssVars(min: number, max: number, val: number): CSSProperties {
  return {
    "--attr-min": String(min),
    "--attr-max": String(max),
    "--control-value": String(val),
  } as CSSProperties;
}

export function WhatIfControls() {
  const spot = useMarketStore((s) => s.spot);
  const strikeStep = useMarketStore((s) => s.strikeStep);
  const asOfIso = useMarketStore((s) => s.asOfIso);
  const selectedChainExpiry = useMarketStore((s) => s.selectedChainExpiry);

  const legs = useStrategyStore((s) => s.legs);
  const whatIf = useStrategyStore((s) => s.whatIf);
  const setWhatIf = useStrategyStore((s) => s.setWhatIf);
  const resetWhatIf = useStrategyStore((s) => s.resetWhatIf);

  const spotMin = Math.max(100, Math.round(spot * 0.88));
  const spotMax = Math.round(spot * 1.12);
  const spotStep = Math.max(5, Math.round(strikeStep / 2));
  const clampedTargetSpot = Math.min(spotMax, Math.max(spotMin, whatIf.targetSpot || spot));

  const openExpiries = legs
    .filter((l) => l.enabled && l.status === "OPEN")
    .map((l) => l.expiry)
    .sort();
  const targetEndExpiry = openExpiries[0] ?? selectedChainExpiry;

  const baseMs = Date.parse(asOfIso) || Date.now();
  const expMs = targetEndExpiry
    ? Date.parse(`${targetEndExpiry}T15:30:00+05:30`)
    : baseMs + 7 * 86400 * 1000;
  const maxTimeMs = Math.max(baseMs + 3600 * 1000, expMs);
  const currentTargetMs = Math.min(
    maxTimeMs,
    Math.max(baseMs, Date.parse(whatIf.targetDatetimeIso) || baseMs)
  );

  const totalSteps = 1000;
  const timeStepIdx =
    maxTimeMs > baseMs
      ? Math.round(((currentTargetMs - baseMs) / (maxTimeMs - baseMs)) * totalSteps)
      : 0;

  const spotPctMove = spot > 0 ? ((clampedTargetSpot - spot) / spot) * 100 : 0;

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-[#0d1422]">
      <div className="mb-2.5 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300">
          What-If Simulation Sliders
        </span>
        <button
          type="button"
          onClick={() => resetWhatIf(spot, asOfIso)}
          className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <RotateCcw className="h-3 w-3" />
          <span>Reset</span>
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Target Spot */}
        <div>
          <div className="flex items-center justify-between text-xs">
            <label htmlFor="whatif-spot" className="text-slate-600 dark:text-slate-400">
              Target Spot
            </label>
            <span className="font-mono font-semibold text-slate-900 tabular-nums dark:text-slate-100">
              {clampedTargetSpot.toLocaleString("en-IN")}{" "}
              <span
                className={`text-[11px] ${
                  spotPctMove >= 0
                    ? "text-[#16A34A] dark:text-emerald-400"
                    : "text-[#DC2626] dark:text-rose-400"
                }`}
              >
                ({spotPctMove >= 0 ? "+" : ""}
                {spotPctMove.toFixed(2)}%)
              </span>
            </span>
          </div>
          <input
            id="whatif-spot"
            type="range"
            className="whatif-slider mt-1"
            min={spotMin}
            max={spotMax}
            step={spotStep}
            value={clampedTargetSpot}
            style={sliderCssVars(spotMin, spotMax, clampedTargetSpot)}
            aria-valuetext={`${clampedTargetSpot} (${spotPctMove.toFixed(2)}%)`}
            onChange={(e) => setWhatIf({ targetSpot: Number(e.target.value) })}
          />
        </div>

        {/* Target Date/Time */}
        <div>
          <div className="flex items-center justify-between text-xs">
            <label htmlFor="whatif-time" className="text-slate-600 dark:text-slate-400">
              Target Date / Time
            </label>
            <span className="font-mono text-[11px] font-medium text-blue-700 tabular-nums dark:text-sky-300">
              {formatIstDateTime(new Date(currentTargetMs).toISOString())}
            </span>
          </div>
          <input
            id="whatif-time"
            type="range"
            className="whatif-slider mt-1"
            min={0}
            max={totalSteps}
            step={1}
            value={timeStepIdx}
            style={sliderCssVars(0, totalSteps, timeStepIdx)}
            aria-valuetext={formatIstDateTime(new Date(currentTargetMs).toISOString())}
            onChange={(e) => {
              const idx = Number(e.target.value);
              const nextMs = baseMs + (idx / totalSteps) * (maxTimeMs - baseMs);
              setWhatIf({ targetDatetimeIso: new Date(nextMs).toISOString() });
            }}
          />
        </div>

        {/* IV Shift % */}
        <div>
          <div className="flex items-center justify-between text-xs">
            <label htmlFor="whatif-iv" className="text-slate-600 dark:text-slate-400">
              IV Shift
            </label>
            <span className="font-mono font-semibold text-amber-700 tabular-nums dark:text-amber-300">
              {whatIf.ivShiftPct >= 0 ? "+" : ""}
              {whatIf.ivShiftPct.toFixed(1)}%
            </span>
          </div>
          <input
            id="whatif-iv"
            type="range"
            className="whatif-slider mt-1"
            min={-20}
            max={30}
            step={0.5}
            value={whatIf.ivShiftPct}
            style={sliderCssVars(-20, 30, whatIf.ivShiftPct)}
            aria-valuetext={`${whatIf.ivShiftPct.toFixed(1)} percent`}
            onChange={(e) => setWhatIf({ ivShiftPct: Number(e.target.value) })}
          />
        </div>
      </div>
    </div>
  );
}
