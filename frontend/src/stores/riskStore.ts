import { create } from "zustand";
import {
  getDhanFunds,
  getEgressIp,
  getRiskStatus,
  switchExecutionMode,
  triggerKillSwitch,
  unlockKillSwitch,
  updateRiskConfig,
} from "@/lib/api/client";
import type {
  BrokerOrderType,
  EgressIpResponse,
  ExecutionMode,
  FundLimitResponse,
  KillSwitchTriggerResponse,
  ProductType,
  RiskConfigUpdateRequest,
  RiskStateResponse,
} from "@/lib/api/types";
import { useSimulatorStore } from "./simulatorStore";

export interface RiskStoreState {
  executionMode: ExecutionMode;
  riskState: RiskStateResponse | null;
  egressIp: EgressIpResponse | null;
  funds: FundLimitResponse | null;
  productType: ProductType;
  orderType: BrokerOrderType;
  limitBufferTicks: number;
  isKillArmed: boolean;
  isTriggeringKill: boolean;
  lastRiskError: string | null;

  loadRiskState: () => Promise<void>;
  loadEgressIp: () => Promise<void>;
  loadFunds: (env?: "SANDBOX" | "LIVE") => Promise<FundLimitResponse | null>;
  setProductType: (product: ProductType) => void;
  setOrderType: (orderType: BrokerOrderType) => void;
  setLimitBufferTicks: (ticks: number) => void;
  setExecutionModeLocal: (mode: ExecutionMode) => void;
  requestModeSwitch: (
    targetMode: ExecutionMode,
    confirmed?: boolean
  ) => Promise<{ ok: boolean; error?: string }>;
  updateRiskLimits: (patch: RiskConfigUpdateRequest) => Promise<void>;
  armOrTriggerKillSwitch: (
    reason?: string
  ) => Promise<{ armed: boolean; triggered?: KillSwitchTriggerResponse; error?: string }>;
  disarmKillSwitch: () => void;
  unlockKillSwitch: (confirmationText: string) => Promise<{ ok: boolean; error?: string }>;
}

let armResetTimer: ReturnType<typeof setTimeout> | null = null;

export const useRiskStore = create<RiskStoreState>((set, get) => ({
  executionMode: "PAPER_LIVE",
  riskState: null,
  egressIp: null,
  funds: null,
  productType: "MARGIN",
  orderType: "LIMIT",
  limitBufferTicks: 2,
  isKillArmed: false,
  isTriggeringKill: false,
  lastRiskError: null,

  loadRiskState: async () => {
    try {
      const state = await getRiskStatus();
      set({
        riskState: state,
        executionMode: state.active_execution_mode,
        productType: state.product_type,
        limitBufferTicks: state.limit_buffer_ticks,
      });
    } catch {
      // Backend offline fallback preserves default PAPER_LIVE
    }
  },

  loadEgressIp: async () => {
    try {
      const ip = await getEgressIp();
      set({ egressIp: ip });
    } catch {
      // ignore egress check error
    }
  },

  loadFunds: async (env) => {
    try {
      const resolvedEnv = env ?? (get().executionMode === "DHAN_LIVE" ? "LIVE" : "SANDBOX");
      const funds = await getDhanFunds(resolvedEnv);
      set({ funds });
      return funds;
    } catch {
      set({ funds: null });
      return null;
    }
  },

  setProductType: (productType) => set({ productType }),
  setOrderType: (orderType) => set({ orderType }),
  setLimitBufferTicks: (ticks) =>
    set({ limitBufferTicks: Math.max(0, Math.min(50, Math.floor(ticks))) }),

  setExecutionModeLocal: (mode) => set({ executionMode: mode }),

  requestModeSwitch: async (targetMode, confirmed = false) => {
    set({ lastRiskError: null });
    try {
      const next = await switchExecutionMode({ mode: targetMode, confirmed });
      set({
        riskState: next,
        executionMode: next.active_execution_mode,
      });
      const sim = useSimulatorStore.getState();
      if (targetMode === "SIMULATOR" && sim.mode !== "simulator") {
        await sim.setMode("simulator");
      } else if (targetMode !== "SIMULATOR" && sim.mode !== "builder") {
        await sim.setMode("builder");
      }
      return { ok: true };
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to switch trading mode";
      set({ lastRiskError: message });
      return { ok: false, error: message };
    }
  },

  updateRiskLimits: async (patch) => {
    try {
      const next = await updateRiskConfig(patch);
      set({
        riskState: next,
        productType: next.product_type,
        limitBufferTicks: next.limit_buffer_ticks,
      });
    } catch (err) {
      set({
        lastRiskError: err instanceof Error ? err.message : "Failed to update risk config",
      });
    }
  },

  disarmKillSwitch: () => {
    if (armResetTimer) {
      clearTimeout(armResetTimer);
      armResetTimer = null;
    }
    set({ isKillArmed: false });
  },

  armOrTriggerKillSwitch: async (reason) => {
    if (!get().isKillArmed) {
      if (armResetTimer) clearTimeout(armResetTimer);
      set({ isKillArmed: true, lastRiskError: null });
      armResetTimer = setTimeout(() => {
        set({ isKillArmed: false });
        armResetTimer = null;
      }, 5000);
      return { armed: true };
    }

    if (armResetTimer) {
      clearTimeout(armResetTimer);
      armResetTimer = null;
    }
    set({ isKillArmed: false, isTriggeringKill: true, lastRiskError: null });
    try {
      const res = await triggerKillSwitch(reason);
      await get().loadRiskState();
      set({ isTriggeringKill: false });
      return { armed: false, triggered: res };
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Kill switch call failed";
      set({ isTriggeringKill: false, lastRiskError: msg });
      return { armed: false, error: msg };
    }
  },

  unlockKillSwitch: async (confirmationText) => {
    try {
      const next = await unlockKillSwitch(confirmationText);
      set({ riskState: next, lastRiskError: null });
      return { ok: true };
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unlock failed";
      set({ lastRiskError: msg });
      return { ok: false, error: msg };
    }
  },
}));

