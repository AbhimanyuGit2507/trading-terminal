import { afterEach, describe, expect, it, vi } from "vitest";
import type { OptionChainSnapshot, SimulatorStepResponse } from "@/lib/api/types";
import { useMarketStore } from "@/stores/marketStore";
import { useSimulatorStore } from "@/stores/simulatorStore";
import { useStrategyStore } from "@/stores/strategyStore";

function makeSnapshot(asOf: string, spot: number, ceLtp: number): OptionChainSnapshot {
  return {
    symbol: "NIFTY",
    exchange: "NSE_FNO",
    expiry: "2026-11-23",
    as_of: asOf,
    spot,
    futures_price: spot + 10,
    forward_price: spot + 10,
    india_vix: 13.5,
    atm_strike: 24350,
    lot_size: 65,
    strike_step: 50,
    futures_contract_id: "NSE_FNO:NIFTY:2026-11-23:FUT",
    expiries: [
      {
        expiry_date: "2026-11-23",
        label: "23 Nov 26 (M)",
        is_weekly: false,
        is_monthly: true,
        dte: 0,
        lot_size: 65,
      },
    ],
    rows: [
      {
        strike: 24350,
        ce_contract_id: "NSE_FNO:NIFTY:2026-11-23:24350:CE",
        pe_contract_id: "NSE_FNO:NIFTY:2026-11-23:24350:PE",
        ce_ltp: ceLtp,
        ce_bid: ceLtp - 0.5,
        ce_ask: ceLtp + 0.5,
        ce_iv: 14.0,
        ce_delta: 0.5,
        ce_gamma: 0.0005,
        ce_theta: -12,
        ce_vega: 10,
        ce_oi: 100000,
        ce_oi_change: 0,
        pe_ltp: 85,
        pe_bid: 84.5,
        pe_ask: 85.5,
        pe_iv: 14.0,
        pe_delta: -0.5,
        pe_gamma: 0.0005,
        pe_theta: -12,
        pe_vega: 10,
        pe_oi: 100000,
        pe_oi_change: 0,
      },
    ],
  };
}

describe("Phase 2 Simulator Store: Clock Step, Auto-Settlement, and Mode Isolation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("isolates open legs between Builder and Simulator modes", () => {
    useStrategyStore.getState().clearStrategy();
    useSimulatorStore.setState({ mode: "builder" });

    useStrategyStore.getState().addLeg({
      leg_id: "builder-leg",
      contract_id: "NSE_FNO:NIFTY:2026-12-01:24350:CE",
      symbol: "NIFTY",
      exchange: "NSE_FNO",
      expiry: "2026-12-01",
      strike: 24350,
      option_type: "CE",
      side: "SELL",
      lots: 1,
      lot_size: 65,
      entry_price: 150,
      entry_iv: 0.14,
      enabled: true,
      status: "OPEN",
    });
    expect(useStrategyStore.getState().legs).toHaveLength(1);

    // Switch workspace to simulator -> builder legs are isolated away
    useStrategyStore.getState().switchWorkspaceMode("builder", "simulator");
    expect(useStrategyStore.getState().legs).toHaveLength(0);

    useStrategyStore.getState().addLeg({
      leg_id: "sim-leg",
      contract_id: "NSE_FNO:NIFTY:2026-11-23:24350:PE",
      symbol: "NIFTY",
      exchange: "NSE_FNO",
      expiry: "2026-11-23",
      strike: 24350,
      option_type: "PE",
      side: "BUY",
      lots: 2,
      lot_size: 65,
      entry_price: 90,
      entry_iv: 0.14,
      enabled: true,
      status: "OPEN",
    });
    expect(useStrategyStore.getState().legs).toHaveLength(1);

    // Switch back to builder -> original builder leg is intact
    useStrategyStore.getState().switchWorkspaceMode("simulator", "builder");
    const builderLegs = useStrategyStore.getState().legs;
    expect(builderLegs).toHaveLength(1);
    expect(builderLegs[0].leg_id).toBe("builder-leg");
  });

  it("updates clock, leg quotes, and settles expired legs while pausing AutoPlay", async () => {
    useStrategyStore.getState().clearStrategy();
    useSimulatorStore.setState({
      mode: "simulator",
      simDatetimeIso: "2026-11-23T15:25:00+05:30",
      isPlaying: true,
    });

    useStrategyStore.getState().addLeg({
      leg_id: "exp-leg",
      contract_id: "NSE_FNO:NIFTY:2026-11-23:24350:CE",
      symbol: "NIFTY",
      exchange: "NSE_FNO",
      expiry: "2026-11-23",
      strike: 24350,
      option_type: "CE",
      side: "SELL",
      lots: 1,
      lot_size: 65,
      entry_price: 120,
      entry_iv: 0.14,
      enabled: true,
      status: "OPEN",
    });

    const mockResp: SimulatorStepResponse = {
      symbol: "NIFTY",
      previous_as_of: "2026-11-23T15:25:00+05:30",
      new_as_of: "2026-11-25T09:15:00+05:30",
      data_source: "parquet",
      end_of_data: false,
      chain: makeSnapshot("2026-11-25T09:15:00+05:30", 24420, 140),
      leg_quotes: {
        "NSE_FNO:NIFTY:2026-11-23:24350:CE": {
          contract_id: "NSE_FNO:NIFTY:2026-11-23:24350:CE",
          expiry: "2026-11-23",
          strike: 24350,
          option_type: "CE",
          ltp: 70,
          bid: 69.5,
          ask: 70.5,
          iv: 12.0,
          delta: 1.0,
          gamma: 0,
          theta: 0,
          vega: 0,
          forward_price: 24420,
          updated_at: "2026-11-25T09:15:00+05:30",
        },
      },
      settled_legs: [
        {
          leg_id: "exp-leg",
          contract_id: "NSE_FNO:NIFTY:2026-11-23:24350:CE",
          symbol: "NIFTY",
          expiry: "2026-11-23",
          strike: 24350,
          option_type: "CE",
          side: "SELL",
          lots_settled: 1,
          lot_size: 65,
          entry_price: 120,
          settlement_price: 70,
          realized_pnl: 3250,
          settled_at: "2026-11-23T15:30:00+05:30",
          order_id: null,
        },
      ],
      realized_pnl_delta: "3250.00",
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => mockResp,
      }))
    );

    await useSimulatorStore.getState().stepTime("+5m");

    const sim = useSimulatorStore.getState();
    expect(sim.simDatetimeIso).toBe("2026-11-25T09:15:00+05:30");
    expect(sim.isPlaying).toBe(false); // auto-paused on expiry settlement
    expect(useMarketStore.getState().spot).toBe(24420);
    expect(useStrategyStore.getState().legs).toHaveLength(0);
    expect(useStrategyStore.getState().closedLegs).toHaveLength(1);
    expect(useStrategyStore.getState().realizedPnl).toBe(3250);
  });
});

