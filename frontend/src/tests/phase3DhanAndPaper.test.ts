import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatDhanPill } from "@/lib/dhanStatus";
import { useMarketStore } from "@/stores/marketStore";
import { useStrategyStore } from "@/stores/strategyStore";

const executeOrdersMock = vi.fn();

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    executeOrders: (...args: unknown[]) => executeOrdersMock(...args),
  };
});

describe("Phase 3: Dhan API status pill & Daily Max-Loss Circuit Breaker", () => {
  beforeEach(() => {
    executeOrdersMock.mockReset();
    useMarketStore.setState({
      feedStatus: "MOCK_FALLBACK",
      dhanStatus: null,
      wsStatus: "connected",
      activeLegQuotes: {},
    });
    useStrategyStore.setState({
      legs: [],
      closedLegs: [],
      realizedPnl: 0,
      lotMultiplier: 1,
      dailyMaxLossLimit: null,
      autoSquareOffOnMaxLoss: true,
      maxLossTriggered: false,
      lastExecutionNotice: null,
      isExecuting: false,
    });
  });

  it("formats TopBar pill across LIVE_DHAN, TOKEN_EXPIRED, and MOCK_FALLBACK", () => {
    const live = formatDhanPill(
      "LIVE_DHAN",
      {
        connected: true,
        mode: "LIVE_DHAN",
        account_name: "Avi Dhan",
        seconds_remaining: 18 * 3600 + 60,
      },
      "connected"
    );
    expect(live.label).toBe("Dhan Live (18h left)");
    expect(live.tone).toBe("emerald");

    const expired = formatDhanPill(
      "TOKEN_EXPIRED",
      { connected: false, mode: "TOKEN_EXPIRED" },
      "connected"
    );
    expect(expired.label).toBe("Token Expired — Paste Token");
    expect(expired.tone).toBe("rose");

    const mock = formatDhanPill("MOCK_FALLBACK", null, "disconnected");
    expect(mock.label).toBe("Mock Mode — Connect Dhan");
    expect(mock.tone).toBe("slate");
  });

  it("triggers maxLossTriggered and executes PAPER_LIVE square-off when breached in live feed", async () => {
    executeOrdersMock.mockResolvedValue({
      idempotency_key: "11111111-1111-1111-1111-111111111111",
      deduplicated: false,
      trading_mode: "PAPER_LIVE",
      action: "SQUARE_OFF_ALL",
      realized_pnl_delta: "-5200.00",
      fills: [
        {
          order_id: "22222222-2222-2222-2222-222222222222",
          parent_order_id: null,
          slice_index: 1,
          total_slices: 1,
          is_parent: false,
          contract_id: "NSE_FNO:NIFTY:2026-11-26:24350:CE",
          side: "BUY",
          action: "SQUARE_OFF_ALL",
          lots: 1,
          quantity: 65,
          fill_price: "220.00",
          status: "FILLED",
          executed_at: "2026-11-25T09:30:00Z",
        },
      ],
    });

    useMarketStore.setState({
      feedStatus: "LIVE_DHAN",
      activeLegQuotes: {
        "NSE_FNO:NIFTY:2026-11-26:24350:CE": {
          contract_id: "NSE_FNO:NIFTY:2026-11-26:24350:CE",
          expiry: "2026-11-26",
          strike: 24350,
          option_type: "CE",
          ltp: 220,
          bid: 219.95,
          ask: 220.05,
          iv: 0.14,
          delta: 0.5,
          gamma: 0.001,
          theta: -12,
          vega: 8,
          forward_price: 24375,
          updated_at: "2026-11-25T09:30:00+05:30",
        },
      },
    });

    useStrategyStore.setState({
      dailyMaxLossLimit: 5000,
      autoSquareOffOnMaxLoss: true,
      legs: [
        {
          leg_id: "leg-1",
          contract_id: "NSE_FNO:NIFTY:2026-11-26:24350:CE",
          symbol: "NIFTY",
          exchange: "NSE_FNO",
          expiry: "2026-11-26",
          strike: 24350,
          option_type: "CE",
          side: "SELL",
          lots: 1,
          lot_size: 65,
          entry_price: 140,
          entry_iv: 0.14,
          enabled: true,
          status: "OPEN",
        },
      ],
    });

    useStrategyStore.getState().checkMaxLossCircuitBreaker(-5200);

    // Wait a microtask for async squareOffAll inside checkMaxLossCircuitBreaker
    await vi.waitFor(() => {
      expect(executeOrdersMock).toHaveBeenCalledTimes(1);
    });

    const callArg = executeOrdersMock.mock.calls[0]?.[0] as { trading_mode: string; action: string };
    expect(callArg.trading_mode).toBe("PAPER_LIVE");
    expect(callArg.action).toBe("SQUARE_OFF_ALL");
    expect(useStrategyStore.getState().maxLossTriggered).toBe(true);
    expect(useStrategyStore.getState().legs).toHaveLength(0);
  });
});
