import type { components } from "@shared/types/api";

export type ApiSchemas = components["schemas"];

export type IndexSymbol = ApiSchemas["InstrumentSpecSchema"]["symbol"];
export type ExchangeSegment = ApiSchemas["InstrumentSpecSchema"]["exchange"];
export type OptionSide = ApiSchemas["StrategyLegSchema"]["side"];
export type LegOptionType = ApiSchemas["StrategyLegSchema"]["option_type"];
export type TradingMode = NonNullable<ApiSchemas["BatchOrderRequest"]["trading_mode"]>;
export type SimulatorStepSize = ApiSchemas["SimulatorStepRequest"]["step"];

export type InstrumentSpec = ApiSchemas["InstrumentSpecSchema"];
export type ExpiryInfo = ApiSchemas["ExpiryInfoSchema"];
export type LegQuote = ApiSchemas["LegQuoteSchema"];
export type OptionChainRow = ApiSchemas["OptionChainRowSchema"];
export type OptionChainSnapshot = ApiSchemas["OptionChainSnapshotSchema"];
export type StrategyLeg = ApiSchemas["StrategyLegSchema"];
export type ClosedLegRecord = ApiSchemas["ClosedLegRecordSchema"];
export type PayoffEvaluateRequest = ApiSchemas["PayoffEvaluateRequest"];
export type PayoffEvaluateResponse = ApiSchemas["PayoffEvaluateResponse"];
export type MarginBreakdown = ApiSchemas["MarginBreakdownSchema"];
export type BatchOrderRequest = ApiSchemas["BatchOrderRequest"];
export type ExecutionResult = ApiSchemas["ExecutionResultSchema"];
export type OrderAuditLog = ApiSchemas["OrderAuditLogSchema"];
export type StrategyCreateRequest = ApiSchemas["StrategyCreateRequest"];
export type StrategyUpdateRequest = ApiSchemas["StrategyUpdateRequest"];
export type StrategyResponse = ApiSchemas["StrategyResponse"];
export type SimulatorStepRequest = ApiSchemas["SimulatorStepRequest"];
export type SimulatorStepResponse = ApiSchemas["SimulatorStepResponse"];
export type WsSubscribeMessage = ApiSchemas["WsSubscribeMessage"];
export type WsTickFrame = ApiSchemas["WsTickFrameSchema"];
