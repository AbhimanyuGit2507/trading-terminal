"use client";

import { Clock, Pause, Play } from "lucide-react";
import { formatIstDateTime } from "@/lib/format";
import type { SimulatorStepSize } from "@/lib/api/types";
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
      className="border-b border-violet-500/25 bg-violet-950/20 px-4 py-2"
    >
      <div className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="inline-flex items-center gap-1.5 rounded-md border border-violet-500/30 bg-violet-500/15 px-2.5 py-1 text-xs font-semibold text-violet-200">
            <Clock className="h-3.5 w-3.5 text-violet-400" />
            <span className="tabular-nums">{formatIstDateTime(displayIso)}</span>
          </div>
          <span className="hidden lg:inline text-[11px] text-slate-400">
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
                className={`rounded px-2 py-1 text-xs font-mono font-medium transition-colors disabled:opacity-50 ${
                  isForward
                    ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                    : "border border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
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
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
          >
            {AUTO_STEPS.map((st) => (
              <option key={st} value={st}>
                Step {st}
              </option>
            ))}
          </select>

          <div className="flex items-center rounded border border-slate-700 bg-slate-900 p-0.5">
            {SPEEDS.map((sp) => (
              <button
                key={sp}
                type="button"
                onClick={() => setPlaybackSpeed(sp)}
                className={`rounded px-1.5 py-0.5 text-[11px] font-mono ${
                  playbackSpeed === sp
                    ? "bg-violet-600 text-white"
                    : "text-slate-400 hover:text-slate-200"
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

