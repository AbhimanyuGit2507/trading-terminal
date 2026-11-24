import type {
  AvailableDatesResponse,
  BatchOrderRequest,
  ExecutionResult,
  ExpiryInfo,
  IndexSymbol,
  InstrumentSpec,
  LegQuote,
  OptionChainSnapshot,
  OrderAuditLog,
  PayoffEvaluateRequest,
  PayoffEvaluateResponse,
  SimulatorJumpRequest,
  SimulatorStepRequest,
  SimulatorStepResponse,
  StrategyCreateRequest,
  StrategyResponse,
  StrategyUpdateRequest,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const errBody = await res.json();
      if (errBody?.detail) {
        message = typeof errBody.detail === "string" ? errBody.detail : JSON.stringify(errBody.detail);
      }
    } catch {
      // ignore non-json body
    }
    throw new Error(message);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export function getInstruments(asOf?: string): Promise<InstrumentSpec[]> {
  const qs = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  return apiFetch<InstrumentSpec[]>(`/api/v1/market/instruments${qs}`);
}

export function getExpiries(symbol: IndexSymbol, asOf?: string): Promise<ExpiryInfo[]> {
  const params = new URLSearchParams({ symbol });
  if (asOf) params.set("as_of", asOf);
  return apiFetch<ExpiryInfo[]>(`/api/v1/market/expiries?${params.toString()}`);
}

export function getOptionChain(
  symbol: IndexSymbol,
  expiry?: string,
  asOf?: string
): Promise<OptionChainSnapshot> {
  const params = new URLSearchParams({ symbol });
  if (expiry) params.set("expiry", expiry);
  if (asOf) params.set("as_of", asOf);
  return apiFetch<OptionChainSnapshot>(`/api/v1/market/chain?${params.toString()}`);
}

export async function getBatchQuotes(
  contractIds: string[],
  asOf?: string
): Promise<Record<string, LegQuote>> {
  if (contractIds.length === 0) return {};
  const res = await apiFetch<{ as_of: string; quotes: Record<string, LegQuote> }>(
    "/api/v1/market/quotes",
    {
      method: "POST",
      body: JSON.stringify({ contract_ids: contractIds, as_of: asOf ?? null }),
    }
  );
  return res.quotes;
}

export function evaluateAnalytics(
  req: PayoffEvaluateRequest
): Promise<PayoffEvaluateResponse> {
  return apiFetch<PayoffEvaluateResponse>("/api/v1/analytics/evaluate", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function executeOrders(
  req: BatchOrderRequest,
  idempotencyKey?: string
): Promise<ExecutionResult> {
  const key = idempotencyKey ?? crypto.randomUUID();
  return apiFetch<ExecutionResult>("/api/v1/orders/execute", {
    method: "POST",
    headers: {
      "X-Idempotency-Key": key,
    },
    body: JSON.stringify({ ...req, idempotency_key: key }),
  });
}

export function listOrders(strategyId?: string, limit = 100): Promise<OrderAuditLog[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (strategyId) params.set("strategy_id", strategyId);
  return apiFetch<OrderAuditLog[]>(`/api/v1/orders?${params.toString()}`);
}

export function listStrategies(): Promise<StrategyResponse[]> {
  return apiFetch<StrategyResponse[]>("/api/v1/strategies");
}

export function createStrategy(req: StrategyCreateRequest): Promise<StrategyResponse> {
  return apiFetch<StrategyResponse>("/api/v1/strategies", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function updateStrategy(
  id: string,
  req: StrategyUpdateRequest
): Promise<StrategyResponse> {
  return apiFetch<StrategyResponse>(`/api/v1/strategies/${id}`, {
    method: "PUT",
    body: JSON.stringify(req),
  });
}

export function deleteStrategy(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/strategies/${id}`, {
    method: "DELETE",
  });
}

export function getAvailableSimulatorDates(symbol: IndexSymbol): Promise<AvailableDatesResponse> {
  return apiFetch<AvailableDatesResponse>(
    `/api/v1/simulator/available-dates?symbol=${encodeURIComponent(symbol)}`
  );
}

export function jumpSimulator(req: SimulatorJumpRequest): Promise<SimulatorStepResponse> {
  return apiFetch<SimulatorStepResponse>("/api/v1/simulator/jump", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function stepSimulator(req: SimulatorStepRequest): Promise<SimulatorStepResponse> {
  return apiFetch<SimulatorStepResponse>("/api/v1/simulator/step", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

