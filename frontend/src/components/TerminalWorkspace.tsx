"use client";

import { useEffect, useRef } from "react";
import { evaluateAnalytics, getInstruments } from "@/lib/api/client";
import { MarketStreamClient } from "@/lib/api/wsClient";
import { useMarketStore } from "@/stores/marketStore";
import { useSimulatorStore } from "@/stores/simulatorStore";
import { useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";
import { StrategyBuilderPanel } from "./builder/StrategyBuilderPanel";
import { OrdersDrawer } from "./modals/OrdersDrawer";
import { PartialExitDialog } from "./modals/PartialExitDialog";
import { StrategiesDrawer } from "./modals/StrategiesDrawer";
import { OptionChainTable } from "./option-chain/OptionChainTable";
import { PayoffPanel } from "./payoff/PayoffPanel";
import { SimulatorBar } from "./simulator/SimulatorBar";
import { TopBar } from "./topbar/TopBar";

export function TerminalWorkspace() {
  const wsRef = useRef<MarketStreamClient | null>(null);

  const symbol = useMarketStore((s) => s.symbol);
  const selectedChainExpiry = useMarketStore((s) => s.selectedChainExpiry);
  const spot = useMarketStore((s) => s.spot);
  const asOfIso = useMarketStore((s) => s.asOfIso);
  const indiaVix = useMarketStore((s) => s.indiaVix);
  const error = useMarketStore((s) => s.error);

  const legs = useStrategyStore((s) => s.legs);
  const realizedPnl = useStrategyStore((s) => s.realizedPnl);
  const setMargin = useStrategyStore((s) => s.setMargin);
  const setIsLoadingMargin = useStrategyStore((s) => s.setIsLoadingMargin);

  const mode = useSimulatorStore((s) => s.mode);
  const isPlaying = useSimulatorStore((s) => s.isPlaying);
  const playbackSpeed = useSimulatorStore((s) => s.playbackSpeed);
  const autoStepSize = useSimulatorStore((s) => s.autoStepSize);
  const stepTime = useSimulatorStore((s) => s.stepTime);

  const includeCharges = useUiStore((s) => s.includeCharges);

  // Initial load: instruments + default NIFTY option chain
  useEffect(() => {
    let mounted = true;
    const market = useMarketStore.getState();
    const strategy = useStrategyStore.getState();

    getInstruments()
      .then((specs) => {
        if (mounted) market.setInstruments(specs);
      })
      .catch(() => undefined);

    market
      .loadChain("NIFTY")
      .then((snap) => {
        if (mounted) {
          strategy.resetWhatIf(snap.spot, snap.as_of);
        }
      })
      .catch(() => undefined);

    return () => {
      mounted = false;
    };
  }, []);

  // Unified coalesced WebSocket lifecycle (Builder live/mock stream)
  useEffect(() => {
    const client = new MarketStreamClient({
      flushIntervalMs: 100,
      onFrame: (frame) => {
        if (useSimulatorStore.getState().mode === "builder") {
          useMarketStore.getState().applyTickFrame(frame);
        }
      },
      onStatusChange: (status) => {
        useMarketStore.getState().setWsStatus(status);
      },
    });
    wsRef.current = client;
    client.connect();

    return () => {
      client.disconnect();
      wsRef.current = null;
    };
  }, []);

  // Re-subscribe whenever symbol, viewed expiry, or open multi-expiry legs change
  useEffect(() => {
    if (!wsRef.current || mode !== "builder" || !selectedChainExpiry) return;
    const activeContracts = Array.from(
      new Set(legs.filter((l) => l.status === "OPEN").map((l) => l.contract_id))
    );
    wsRef.current.subscribe(symbol, selectedChainExpiry, activeContracts);
  }, [symbol, selectedChainExpiry, legs, mode]);

  // Debounced backend margin estimation (/api/v1/analytics/evaluate)
  useEffect(() => {
    const activeLegs = legs.filter((l) => l.enabled && l.status === "OPEN");
    if (activeLegs.length === 0) {
      setMargin(null);
      return;
    }

    const timer = setTimeout(() => {
      setIsLoadingMargin(true);
      evaluateAnalytics({
        symbol,
        spot,
        as_of: asOfIso || new Date().toISOString(),
        legs: activeLegs,
        realized_pnl: realizedPnl,
        include_charges: includeCharges,
        atm_iv: Math.max(indiaVix / 100.0, 0.08),
      })
        .then((res) => setMargin(res.margin))
        .catch(() => undefined)
        .finally(() => setIsLoadingMargin(false));
    }, 180);

    return () => clearTimeout(timer);
  }, [legs, symbol, spot, asOfIso, realizedPnl, includeCharges, indiaVix, setMargin, setIsLoadingMargin]);

  // Simulator AutoPlay loop
  useEffect(() => {
    if (mode !== "simulator" || !isPlaying) return;
    const delayMs = Math.max(180, Math.round(1000 / playbackSpeed));
    const timer = setInterval(() => {
      void stepTime(autoStepSize);
    }, delayMs);
    return () => clearInterval(timer);
  }, [mode, isPlaying, playbackSpeed, autoStepSize, stepTime]);

  return (
    <div className="min-h-screen bg-[#0b0f17] text-slate-100">
      <TopBar />
      <SimulatorBar />

      {error && (
        <div className="mx-auto mt-3 max-w-[1680px] px-4">
          <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-3 py-2 text-xs text-rose-200">
            Backend connection note: {error} (ensure FastAPI is running on port 8000)
          </div>
        </div>
      )}

      <main className="mx-auto grid max-w-[1680px] grid-cols-1 gap-4 p-4 xl:grid-cols-12">
        {/* Left: 61-strike Option Chain */}
        <div className="xl:col-span-5">
          <OptionChainTable />
        </div>

        {/* Right: Strategy Builder + ECharts Payoff & What-If */}
        <div className="flex flex-col gap-4 xl:col-span-7">
          <StrategyBuilderPanel />
          <PayoffPanel />
        </div>
      </main>

      <PartialExitDialog />
      <StrategiesDrawer />
      <OrdersDrawer />
    </div>
  );
}

