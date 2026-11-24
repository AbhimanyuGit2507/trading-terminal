import type { IndexSymbol, WsSubscribeMessage, WsTickFrame } from "./types";

const DEFAULT_WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/api/v1/ws/stream";

export type WsConnectionStatus = "disconnected" | "connecting" | "connected";

interface MarketWsOptions {
  onFrame: (frame: WsTickFrame) => void;
  onStatusChange: (status: WsConnectionStatus) => void;
  flushIntervalMs?: number;
}

/**
 * Coalescing WebSocket client that buffers high-frequency ticks and flushes
 * at most once per flushIntervalMs (default 100ms) to keep React & ECharts jank-free.
 */
export class MarketStreamClient {
  private ws: WebSocket | null = null;
  private latestFrame: WsTickFrame | null = null;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private currentSub: WsSubscribeMessage | null = null;
  private closedByCaller = false;
  private readonly opts: MarketWsOptions;

  constructor(opts: MarketWsOptions) {
    this.opts = opts;
  }

  connect(): void {
    if (typeof window === "undefined") return;
    this.closedByCaller = false;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.opts.onStatusChange("connecting");
    const ws = new WebSocket(DEFAULT_WS_URL);
    this.ws = ws;

    ws.onopen = () => {
      this.opts.onStatusChange("connected");
      this.startFlushLoop();
      if (this.currentSub) {
        this.sendRaw(this.currentSub);
      }
    };

    ws.onmessage = (evt) => {
      try {
        const frame = JSON.parse(String(evt.data)) as WsTickFrame;
        if (frame.type === "tick") {
          this.latestFrame = frame;
        }
      } catch {
        // ignore malformed packets
      }
    };

    ws.onclose = () => {
      this.stopFlushLoop();
      this.ws = null;
      this.opts.onStatusChange("disconnected");
      if (!this.closedByCaller) {
        this.reconnectTimer = setTimeout(() => this.connect(), 1500);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  subscribe(symbol: IndexSymbol, chainExpiry: string | null, activeContracts: string[]): void {
    this.currentSub = {
      action: "subscribe",
      symbol,
      chain_expiry: chainExpiry,
      active_contracts: activeContracts,
    };
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.sendRaw(this.currentSub);
    }
  }

  disconnect(): void {
    this.closedByCaller = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopFlushLoop();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.opts.onStatusChange("disconnected");
  }

  private sendRaw(msg: WsSubscribeMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  private startFlushLoop(): void {
    this.stopFlushLoop();
    const interval = this.opts.flushIntervalMs ?? 100;
    this.flushTimer = setInterval(() => {
      if (this.latestFrame) {
        const frame = this.latestFrame;
        this.latestFrame = null;
        this.opts.onFrame(frame);
      }
    }, interval);
  }

  private stopFlushLoop(): void {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
  }
}

