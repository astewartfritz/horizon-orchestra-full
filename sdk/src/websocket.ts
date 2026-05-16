/**
 * @module websocket
 * @description Type-safe WebSocket wrapper for Horizon Orchestra.
 * Provides automatic reconnection with exponential back-off, heartbeat
 * (ping / pong), and strongly-typed event dispatch.
 *
 * Works in both browser (native WebSocket) and Node.js 18+ environments.
 */

import type {
  StreamEvent,
  WebSocketConnection,
  WebSocketOptions,
  WebSocketCallbacks,
} from './types.js';

/** Internal state machine for the reconnecting socket. */
const enum SocketState {
  Idle = 0,
  Connecting = 1,
  Open = 2,
  Closing = 3,
  Closed = 4,
}

/** Default option values. */
const DEFAULTS: Required<WebSocketOptions> = {
  autoReconnect: true,
  maxReconnectAttempts: 10,
  reconnectDelay: 1_000,
  maxReconnectDelay: 30_000,
  heartbeatInterval: 30_000,
  heartbeatTimeout: 10_000,
  protocols: [],
};

/**
 * A reconnecting, heartbeat-aware WebSocket client that dispatches
 * typed {@link StreamEvent} objects to a caller-supplied callback.
 */
export class HorizonWebSocket implements WebSocketConnection {
  private ws: WebSocket | null = null;
  private _state: SocketState = SocketState.Idle;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private heartbeatTimeoutTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly url: string;
  private readonly opts: Required<WebSocketOptions>;
  private readonly callbacks: WebSocketCallbacks;
  private intentionallyClosed = false;

  /**
   * Create a new WebSocket connection.
   * @param url      - WebSocket endpoint (ws:// or wss://).
   * @param callbacks - Lifecycle callbacks for events, close, error and reconnect.
   * @param options   - Optional reconnect and heartbeat tuning.
   */
  constructor(
    url: string,
    callbacks: WebSocketCallbacks,
    options: WebSocketOptions = {},
  ) {
    this.url = url;
    this.callbacks = callbacks;
    this.opts = { ...DEFAULTS, ...options };
    this.connect();
  }

  // ── Public API (WebSocketConnection) ────────────────────────────

  /** Current underlying readyState (or CLOSED if no socket exists). */
  get readyState(): number {
    return this.ws?.readyState ?? WebSocket.CLOSED;
  }

  /** Whether the socket is currently in an open state. */
  get isConnected(): boolean {
    return this._state === SocketState.Open;
  }

  /** Send a text frame. Throws if the socket is not open. */
  send(message: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket is not open');
    }
    this.ws.send(message);
  }

  /** Cleanly close the connection, suppressing reconnection. */
  close(): void {
    this.intentionallyClosed = true;
    this.stopHeartbeat();
    this.clearReconnectTimer();
    if (this.ws) {
      this._state = SocketState.Closing;
      this.ws.close(1000, 'Client closed');
    }
    this._state = SocketState.Closed;
  }

  // ── Connection lifecycle ────────────────────────────────────────

  /** Open (or re-open) the underlying WebSocket connection. */
  private connect(): void {
    this._state = SocketState.Connecting;
    this.ws = new WebSocket(this.url, this.opts.protocols);

    this.ws.onopen = this.handleOpen.bind(this);
    this.ws.onmessage = this.handleMessage.bind(this);
    this.ws.onclose = this.handleClose.bind(this);
    this.ws.onerror = this.handleError.bind(this);
  }

  private handleOpen(): void {
    this._state = SocketState.Open;
    this.reconnectAttempt = 0;
    this.startHeartbeat();
  }

  private handleMessage(event: MessageEvent): void {
    this.resetHeartbeatTimeout();

    // Ignore pong frames sent as text.
    if (event.data === 'pong' || event.data === '') return;

    try {
      const parsed: StreamEvent = JSON.parse(event.data as string);
      this.callbacks.onEvent(parsed);
    } catch {
      // Non-JSON frame — emit as a raw event.
      this.callbacks.onEvent({
        type: 'token',
        data: { raw: event.data },
        timestamp: Date.now(),
      });
    }
  }

  private handleClose(event: CloseEvent): void {
    this._state = SocketState.Closed;
    this.stopHeartbeat();
    this.callbacks.onClose?.(event.code, event.reason);

    if (!this.intentionallyClosed && this.opts.autoReconnect) {
      this.scheduleReconnect();
    }
  }

  private handleError(_event: Event): void {
    const err = new Error('WebSocket error');
    this.callbacks.onError?.(err);
  }

  // ── Reconnection ───────────────────────────────────────────────

  /** Schedule a reconnection with exponential back-off + jitter. */
  private scheduleReconnect(): void {
    if (this.reconnectAttempt >= this.opts.maxReconnectAttempts) {
      this.callbacks.onError?.(
        new Error(`Max reconnect attempts (${this.opts.maxReconnectAttempts}) exceeded`),
      );
      return;
    }

    const baseDelay = Math.min(
      this.opts.reconnectDelay * Math.pow(2, this.reconnectAttempt),
      this.opts.maxReconnectDelay,
    );
    const jitter = Math.random() * baseDelay * 0.3;
    const delay = baseDelay + jitter;

    this.reconnectAttempt++;
    this.callbacks.onReconnect?.(this.reconnectAttempt);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  // ── Heartbeat ──────────────────────────────────────────────────

  /** Start periodic ping frames to keep the connection alive. */
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send('ping');
        this.startHeartbeatTimeout();
      }
    }, this.opts.heartbeatInterval);
  }

  private startHeartbeatTimeout(): void {
    this.clearHeartbeatTimeout();
    this.heartbeatTimeoutTimer = setTimeout(() => {
      // Server failed to respond in time — force close so reconnect kicks in.
      this.ws?.close(4000, 'Heartbeat timeout');
    }, this.opts.heartbeatTimeout);
  }

  private resetHeartbeatTimeout(): void {
    this.clearHeartbeatTimeout();
  }

  private clearHeartbeatTimeout(): void {
    if (this.heartbeatTimeoutTimer !== null) {
      clearTimeout(this.heartbeatTimeoutTimer);
      this.heartbeatTimeoutTimer = null;
    }
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this.clearHeartbeatTimeout();
  }
}
