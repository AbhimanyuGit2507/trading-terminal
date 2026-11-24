"use client";

import { Clock, Pause, Play } from "lucide-react";
import type { SimulatorStepSize } from "@/lib/api/types";
import { formatIstDateTime } from "@/lib/format";
import { useMarketStore } from "@/stores/marketStore";
import { type PlaybackSpeed, useSimulatorStore } from "@/stores/simulatorStore";

const STEP_BUTTONS: SimulatorStepSize[] = [
  "-1d",
  "-30m",
  "-15m",
  "-5m",
  "-1m",
  "+1m",
  "+5m",
  "+15m",
  "+30m",
  "+1d",
];

const SPEEDS: PlaybackSpeed[] = [1, 2, 5, 10];
const AUTO_STEPS: SimulatorStepSize[] = ["+1m", "+5m", "+15m", "+30m"];

export function SimulatorBar() {
  const mode = useSimulatorStore((s) => s.mode);
  const simDatetimeIso = useSimulatorStore((s) => s.simDatetimeIso);
  const isPlaying = useSimulatorStore((s) => s.isPlaying);
  const playbackSpeed = useSimulatorStore((s) => s.playbackSpeed);
  const autoStepSize = useSimulatorStore((s) => s.autoStepSize);
  const isStepping = useSimulatorStore((s) => s.isStepping);
  const stepTime = useSimulatorStore((s) => s.stepTime);
  const togglePlay = useSimulatorStore((s) => s.togglePlay);
  const setPlaybackSpeed = useSimulatorStore((s) => s.setPlaybackSpeed);
  const setAutoStepSize = useSimulatorStore((s) => s.setAutoStepSize);
  const asOfIso = useMarketStore((s) => s.asOfIso);

  if (mode !== "simulator") return null;

  const displayIso = simDatetimeIso || asOfIso;

  return (
    <section
      aria-label="Simulator Time-Travel Controls"
      className="border-b border-violet-200 bg-violet-50/80 px-4 py-2 dark:border-violet-500/25 dark:bg-violet-950/20"
    >
      <div className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="inline-flex items-center gap-1.5 rounded-md border border-violet-300 bg-white px-2.5 py-1 text-xs font-semibold text-violet-800 dark:border-violet-500/30 dark:bg-violet-500/15 dark:text-violet-200">
            <Clock className="h-3.5 w-3.5 text-violet-600 dark:text-violet-400" />
            <span className="tabular-nums">{formatIstDateTime(displayIso)}</span>
          </div>
          <span className="hidden text-[11px] text-slate-600 lg:inline dark:text-slate-400">
            Phase 1 Mock Replay Clock (Parquet 1-min ingestion wires in Phase 2)
          </span>
        </div>

        {/* Step Controls */}
        <div className="flex flex-wrap items-center gap-1">
          {STEP_BUTTONS.map((step) => {
            const isForward = step.startsWith("+");
            return (
              <button
                key={step}
                type="button"
                disabled={isStepping}
                onClick={() => void stepTime(step)}
                className={`rounded px-2 py-1 font-mono text-xs font-medium transition-colors disabled:opacity-50 ${
                  isForward
                    ? "border border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300 dark:hover:bg-emerald-500/20"
                    : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {step}
              </button>
            );
          })}
        </div>

        {/* AutoPlay Controls */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={togglePlay}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-semibold transition-colors ${
              isPlaying
                ? "bg-amber-500 text-slate-950 hover:bg-amber-400"
                : "bg-violet-600 text-white hover:bg-violet-500"
            }`}
          >
            {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            <span>{isPlaying ? "Pause" : "AutoPlay"}</span>
          </button>

          <select
            aria-label="AutoPlay step size"
            value={autoStepSize}
            onChange={(e) => setAutoStepSize(e.target.value as SimulatorStepSize)}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            {AUTO_STEPS.map((st) => (
              <option key={st} value={st}>
                Step {st}
              </option>
            ))}
          </select>

          <div className="flex items-center rounded border border-slate-300 bg-white p-0.5 dark:border-slate-700 dark:bg-slate-900">
            {SPEEDS.map((sp) => (
              <button
                key={sp}
                type="button"
                onClick={() => setPlaybackSpeed(sp)}
                className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${
                  playbackSpeed === sp
                    ? "bg-violet-600 text-white"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                {sp}x
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
