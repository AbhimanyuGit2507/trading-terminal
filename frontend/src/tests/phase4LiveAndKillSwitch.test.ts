import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRiskStore } from "@/stores/riskStore";
import { useStrategyStore } from "@/stores/strategyStore";

const switchExecutionModeMock = vi.fn();
const triggerKillSwitchMock = vi.fn();
const unlockKillSwitchMock = vi.fn();

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    switchExecutionMode: (...args: unknown[]) => switchExecutionModeMock(...args),
    triggerKillSwitch: (...args: unknown[]) => triggerKillSwitchMock(...args),
    unlockKillSwitch: (...args: unknown[]) => unlockKillSwitchMock(...args),
  };
});

describe("Phase 4: Live Trading Mode Guards, 2-Click Kill Switch & Super Order Params", () => {
  beforeEach(() => {
    switchExecutionModeMock.mockReset();
    triggerKillSwitchMock.mockReset();
    unlockKillSwitchMock.mockReset();
    useRiskStore.getState().disarmKillSwitch();
    useRiskStore.setState({
      executionMode: "PAPER_LIVE",
      riskState: null,
      isKillArmed: false,
      isTriggeringKill: false,
      lastRiskError: null,
    });
    useStrategyStore.setState({
      legs: [],
    });
  });

  it("blocks unconfirmed DHAN_LIVE switch and succeeds only with explicit confirmation", async () => {
    switchExecutionModeMock.mockImplementation(async (req: { mode: string; confirmed: boolean }) => {
      if (req.mode === "DHAN_LIVE" && !req.confirmed) {
        throw new Error("Switching to DHAN_LIVE real-money mode requires explicit user confirmation.");
      }
      return {
        active_execution_mode: req.mode,
        daily_kill_switch_active: false,
        daily_max_loss_inr: 25000,
        max_lots_per_order: 50,
        max_open_lots: 100,
        max_daily_trades: 50,
        product_type: "MARGIN",
        limit_buffer_ticks: 2,
        trades_today: 0,
        net_mtm_inr: 0,
      };
    });

    const denied = await useRiskStore.getState().requestModeSwitch("DHAN_LIVE", false);
    expect(denied.ok).toBe(false);
    expect(useRiskStore.getState().executionMode).toBe("PAPER_LIVE");

    const allowed = await useRiskStore.getState().requestModeSwitch("DHAN_LIVE", true);
    expect(allowed.ok).toBe(true);
    expect(useRiskStore.getState().executionMode).toBe("DHAN_LIVE");
  });

  it("enforces 2-click armed Kill Switch flow and manual UNLOCK", async () => {
    triggerKillSwitchMock.mockResolvedValue({
      kill_switch_active: true,
      cancelled_orders: 2,
      exited_positions: 1,
      fallback_exits: 0,
      errors: [],
      triggered_at: "2026-11-25T10:00:00Z",
      reason: "Manual click",
    });
    unlockKillSwitchMock.mockResolvedValue({
      active_execution_mode: "PAPER_LIVE",
      daily_kill_switch_active: false,
      daily_max_loss_inr: 25000,
      max_lots_per_order: 50,
      max_open_lots: 100,
      max_daily_trades: 50,
      product_type: "MARGIN",
      limit_buffer_ticks: 2,
      trades_today: 0,
      net_mtm_inr: 0,
    });

    // Click 1: only arms
    const step1 = await useRiskStore.getState().armOrTriggerKillSwitch("Manual click");
    expect(step1.armed).toBe(true);
    expect(useRiskStore.getState().isKillArmed).toBe(true);
    expect(triggerKillSwitchMock).not.toHaveBeenCalled();

    // Click 2: executes kill switch
    const step2 = await useRiskStore.getState().armOrTriggerKillSwitch("Manual click");
    expect(step2.armed).toBe(false);
    expect(step2.triggered?.cancelled_orders).toBe(2);
    expect(triggerKillSwitchMock).toHaveBeenCalledTimes(1);

    // Typed unlock resets backend kill switch
    const unlocked = await useRiskStore.getState().unlockKillSwitch("UNLOCK");
    expect(unlocked.ok).toBe(true);
    expect(unlockKillSwitchMock).toHaveBeenCalledWith("UNLOCK");
  });

  it("attaches Super Order SL & Target prices per leg cleanly", () => {
    useStrategyStore.getState().addLeg({
      leg_id: "super-1",
      contract_id: "NSE_FNO:NIFTY:2026-12-01:24400:CE",
      symbol: "NIFTY",
      exchange: "NSE_FNO",
      expiry: "2026-12-01",
      strike: 24400,
      option_type: "CE",
      side: "SELL",
      lots: 1,
      lot_size: 65,
      entry_price: 145,
      entry_iv: 0.14,
      enabled: true,
      status: "OPEN",
      product_type: "MARGIN",
    });
    useStrategyStore.getState().updateLegRisk("super-1", {
      stop_loss_price: 210,
      target_price: 75,
      trailing_jump: 10,
    });

    const leg = useStrategyStore.getState().legs[0];
    expect(leg.stop_loss_price).toBe(210);
    expect(leg.target_price).toBe(75);
    expect(leg.trailing_jump).toBe(10);
  });
});

