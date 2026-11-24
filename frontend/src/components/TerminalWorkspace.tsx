"use client";

import { useEffect, useRef } from "react";
import { evaluateAnalytics, getDhanStatus, getInstruments } from "@/lib/api/client";
import { MarketStreamClient } from "@/lib/api/wsClient";
import { useMarketStore } from "@/stores/marketStore";
import { useSimulatorStore } from "@/stores/simulatorStore";
import { getEffectiveLegs, useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";
import { StrategyBuilderPanel } from "./builder/StrategyBuilderPanel";
import { DhanConnectModal } from "./modals/DhanConnectModal";
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
  const activeLegQuotes = useMarketStore((s) => s.activeLegQuotes);
  const error = useMarketStore((s) => s.error);

  const legs = useStrategyStore((s) => s.legs);
  const lotMultiplier = useStrategyStore((s) => s.lotMultiplier);
  const realizedPnl = useStrategyStore((s) => s.realizedPnl);
  const dailyMaxLossLimit = useStrategyStore((s) => s.dailyMaxLossLimit);
  const checkMaxLossCircuitBreaker = useStrategyStore((s) => s.checkMaxLossCircuitBreaker);
  const setMargin = useStrategyStore((s) => s.setMargin);
  const setIsLoadingMargin = useStrategyStore((s) => s.setIsLoadingMargin);

  const mode = useSimulatorStore((s) => s.mode);
  const isPlaying = useSimulatorStore((s) => s.isPlaying);
  const playbackSpeed = useSimulatorStore((s) => s.playbackSpeed);
  const autoStepSize = useSimulatorStore((s) => s.autoStepSize);
  const stepTime = useSimulatorStore((s) => s.stepTime);

  const includeCharges = useUiStore((s) => s.includeCharges);
  const hydrateThemeFromStorage = useUiStore((s) => s.hydrateThemeFromStorage);

  // Hydrate persisted light/dark theme + initial market data
  useEffect(() => {
    hydrateThemeFromStorage();
    const onStorage = (e: StorageEvent) => {
      if (e.key === "stockmock-theme") hydrateThemeFromStorage();
    };
    window.addEventListener("storage", onStorage);

    let mounted = true;
    const market = useMarketStore.getState();
    const strategy = useStrategyStore.getState();

    getInstruments()
      .then((specs) => {
        if (mounted) market.setInstruments(specs);
      })
      .catch(() => undefined);

    getDhanStatus()
      .then((st) => {
        if (mounted) market.setDhanStatus(st);
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
      window.removeEventListener("storage", onStorage);
    };
  }, [hydrateThemeFromStorage]);

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

  // Debounced backend margin estimation (/api/v1/analytics/evaluate) with lotMultiplier
  useEffect(() => {
    const activeLegs = getEffectiveLegs(
      legs.filter((l) => l.enabled && l.status === "OPEN"),
      lotMultiplier
    );
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
  }, [
    legs,
    lotMultiplier,
    symbol,
    spot,
    asOfIso,
    realizedPnl,
    includeCharges,
    indiaVix,
    setMargin,
    setIsLoadingMargin,
  ]);

  // Daily Max-Loss Circuit Breaker monitor in Builder / Paper-Live mode
  useEffect(() => {
    if (mode !== "builder" || dailyMaxLossLimit === null) return;
    const openLegs = getEffectiveLegs(
      legs.filter((l) => l.status === "OPEN" && l.enabled),
      lotMultiplier
    );
    if (openLegs.length === 0) return;
    let unrealized = 0;
    for (const leg of openLegs) {
      const ltp = activeLegQuotes[leg.contract_id]?.ltp ?? leg.entry_price;
      const diff = leg.side === "BUY" ? ltp - leg.entry_price : leg.entry_price - ltp;
      unrealized += diff * leg.lots * leg.lot_size;
    }
    checkMaxLossCircuitBreaker(unrealized + realizedPnl);
  }, [
    mode,
    dailyMaxLossLimit,
    legs,
    lotMultiplier,
    activeLegQuotes,
    realizedPnl,
    checkMaxLossCircuitBreaker,
  ]);

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
    <div className="min-h-screen bg-[#f4f6f9] text-slate-900 dark:bg-[#0b0f17] dark:text-slate-100">
      <TopBar />
      <SimulatorBar />

      {error && (
        <div className="mx-auto mt-3 max-w-[1680px] px-4">
          <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-rose-500/40 dark:bg-rose-950/30 dark:text-rose-200">
            Backend connection note: {error} (ensure FastAPI is running on port 8000)
          </div>
        </div>
      )}

      <main className="mx-auto grid max-w-[1680px] grid-cols-1 gap-4 p-4 xl:grid-cols-12">
        {/* Left: 61-strike Option Chain */}
        <div className="xl:col-span-5">
          <OptionChainTable />
        </div>

        {/* Right: Strategy Builder + ECharts Payoff / Table / Greeks */}
        <div className="flex flex-col gap-4 xl:col-span-7">
          <StrategyBuilderPanel />
          <PayoffPanel />
        </div>
      </main>

      <PartialExitDialog />
      <StrategiesDrawer />
      <OrdersDrawer />
      <DhanConnectModal />
    </div>
  );
}
