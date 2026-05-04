/**
 * @module client
 * @description Main HorizonClient class — the primary entry point for the
 * Horizon Orchestra SDK.  Provides typed methods for every API route, plus
 * streaming helpers that yield async iterators over token / event streams.
 *
 * Uses the native `fetch` API (Node.js 18+, all modern browsers).
 */

import type {
  ApiResponse,
  HorizonClientConfig,
  WebSocketConnection,
  WebSocketOptions,
  // Auth
  RegisterRequest,
  LoginRequest,
  RefreshRequest,
  AuthResponse,
  UserProfile,
  // Task execution
  RunRequest,
  RunResponse,
  QueryRequest,
  QueryResponse,
  // Streaming
  StreamEvent,
  SSEEvent,
  // Billing
  CheckoutRequest,
  PortalRequest,
  Subscription,
  UsageData,
  Invoice,
  // Memory
  MemorySearchRequest,
  MemoryStoreRequest,
  MemoryEntry,
  // Files
  FileInfo,
  ShareLink,
  // Models & Connectors
  ModelInfo,
  ConnectorInfo,
  // Push
  PushRegisterRequest,
  PushSendRequest,
  // Frontier
  FrontierSubmitRequest,
  FrontierTask,
  // Architecture billing
  ArchitectureAccess,
  CostEstimate,
  // Admin
  AdminUsageStats,
  AdminHealthStatus,
} from './types.js';

import {
  HorizonError,
  NetworkError,
  TimeoutError,
  createErrorFromResponse,
} from './errors.js';

import { HorizonWebSocket } from './websocket.js';

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

/** Generate a UUID v4-style request ID. */
function requestId(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Sleep for `ms` milliseconds. */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ──────────────────────────────────────────────
// Client
// ──────────────────────────────────────────────

/**
 * Type-safe client for the Horizon Orchestra API.
 *
 * @example
 * ```ts
 * const client = new HorizonClient({ baseUrl: 'https://api.horizon.ai' });
 * const { data } = await client.login({ email: 'a@b.com', password: 'secret' });
 * ```
 */
export class HorizonClient {
  private readonly baseUrl: string;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private readonly customHeaders: Record<string, string>;

  private apiKey: string | undefined;
  private token: string | undefined;

  /**
   * Create a new SDK client instance.
   * @param config - Connection and authentication configuration.
   */
  constructor(config: HorizonClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, '');
    this.apiKey = config.apiKey;
    this.token = config.token;
    this.timeout = config.timeout ?? 30_000;
    this.maxRetries = config.maxRetries ?? 3;
    this.customHeaders = config.headers ?? {};
  }

  // ── Auth helpers ────────────────────────────────────────────────

  /** Replace the bearer token at runtime (e.g. after login). */
  setToken(token: string): void {
    this.token = token;
  }

  /** Replace the API key at runtime. */
  setApiKey(apiKey: string): void {
    this.apiKey = apiKey;
  }

  // ──────────────────────────────────────────────
  // Auth — /v1/auth
  // ──────────────────────────────────────────────

  /** Register a new user account. */
  async register(req: RegisterRequest): Promise<ApiResponse<AuthResponse>> {
    return this.post<AuthResponse>('/v1/auth/register', req);
  }

  /** Authenticate and obtain access + refresh tokens. */
  async login(req: LoginRequest): Promise<ApiResponse<AuthResponse>> {
    return this.post<AuthResponse>('/v1/auth/login', req);
  }

  /** Exchange a refresh token for a new token pair. */
  async refreshToken(req: RefreshRequest): Promise<ApiResponse<AuthResponse>> {
    return this.post<AuthResponse>('/v1/auth/refresh', req);
  }

  /** Get the profile of the currently authenticated user. */
  async getMe(): Promise<ApiResponse<UserProfile>> {
    return this.get<UserProfile>('/v1/auth/me');
  }

  // ──────────────────────────────────────────────
  // Task Execution — /v1/run, /v1/query
  // ──────────────────────────────────────────────

  /** Submit a task for execution via an agent architecture. */
  async run(req: RunRequest): Promise<ApiResponse<RunResponse>> {
    return this.post<RunResponse>('/v1/run', req);
  }

  /** Query a model directly without agent routing. */
  async query(req: QueryRequest): Promise<ApiResponse<QueryResponse>> {
    return this.post<QueryResponse>('/v1/query', req);
  }

  /**
   * Stream a task run as an async generator of {@link StreamEvent} objects.
   * The request is sent with `stream: true` automatically.
   */
  async *streamRun(req: RunRequest): AsyncGenerator<StreamEvent> {
    const body = { ...req, stream: true };
    const response = await this.rawFetch('/v1/run', {
      method: 'POST',
      body: JSON.stringify(body),
    });

    if (!response.body) {
      throw new HorizonError('No response body for stream', 500, 'NO_STREAM_BODY', requestId());
    }

    yield* this.readNDJSON<StreamEvent>(response.body);
  }

  /**
   * Stream a task run as Server-Sent Events (SSE).
   * Returns an async generator yielding parsed {@link SSEEvent} frames.
   */
  async *streamSSE(req: RunRequest): AsyncGenerator<SSEEvent> {
    const body = { ...req, stream: true };
    const response = await this.rawFetch('/v1/run/sse', {
      method: 'POST',
      body: JSON.stringify(body),
      headers: { Accept: 'text/event-stream' },
    });

    if (!response.body) {
      throw new HorizonError('No response body for SSE', 500, 'NO_SSE_BODY', requestId());
    }

    yield* this.readSSE(response.body);
  }

  // ──────────────────────────────────────────────
  // Billing — /v1/billing
  // ──────────────────────────────────────────────

  /** Create a Stripe checkout session for upgrading the subscription tier. */
  async createCheckout(req: CheckoutRequest): Promise<ApiResponse<{ url: string }>> {
    return this.post<{ url: string }>('/v1/billing/checkout', req);
  }

  /** Create a Stripe customer portal link. */
  async createPortal(req: PortalRequest): Promise<ApiResponse<{ url: string }>> {
    return this.post<{ url: string }>('/v1/billing/portal', req);
  }

  /** Get the current subscription details. */
  async getSubscription(): Promise<ApiResponse<Subscription>> {
    return this.get<Subscription>('/v1/billing/subscription');
  }

  /** Get aggregated usage data for the current billing period. */
  async getUsage(): Promise<ApiResponse<UsageData>> {
    return this.get<UsageData>('/v1/billing/usage');
  }

  /** List recent invoices. */
  async getInvoices(limit?: number): Promise<ApiResponse<Invoice[]>> {
    const params = limit !== undefined ? `?limit=${limit}` : '';
    return this.get<Invoice[]>(`/v1/billing/invoices${params}`);
  }

  // ──────────────────────────────────────────────
  // Memory — /v1/memory
  // ──────────────────────────────────────────────

  /** Semantic search across stored memory entries. */
  async memorySearch(req: MemorySearchRequest): Promise<ApiResponse<MemoryEntry[]>> {
    return this.post<MemoryEntry[]>('/v1/memory/search', req);
  }

  /** Store a new memory entry with optional metadata and tags. */
  async memoryStore(req: MemoryStoreRequest): Promise<ApiResponse<{ id: string }>> {
    return this.post<{ id: string }>('/v1/memory/store', req);
  }

  /** List recent memory entries. */
  async memoryList(limit?: number): Promise<ApiResponse<MemoryEntry[]>> {
    const params = limit !== undefined ? `?limit=${limit}` : '';
    return this.get<MemoryEntry[]>(`/v1/memory${params}`);
  }

  // ──────────────────────────────────────────────
  // Files — /v1/files
  // ──────────────────────────────────────────────

  /** Upload a file to the user's storage. */
  async uploadFile(file: Blob | Buffer, filename: string): Promise<ApiResponse<FileInfo>> {
    const formData = new FormData();
    const blob = file instanceof Blob ? file : new Blob([new Uint8Array(file)]);
    formData.append('file', blob, filename);

    const response = await this.rawFetch('/v1/files/upload', {
      method: 'POST',
      body: formData,
      // Let the browser / runtime set Content-Type with boundary.
      headers: {},
      isFormData: true,
    });

    return this.parseResponse<FileInfo>(response);
  }

  /** List all files belonging to the current user. */
  async listFiles(): Promise<ApiResponse<FileInfo[]>> {
    return this.get<FileInfo[]>('/v1/files');
  }

  /** Download a file by name. */
  async getFile(filename: string): Promise<Blob> {
    const response = await this.rawFetch(`/v1/files/${encodeURIComponent(filename)}`, {
      method: 'GET',
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw createErrorFromResponse(
        response.status,
        body as Record<string, unknown>,
        response.headers.get('Retry-After'),
      );
    }

    return response.blob();
  }

  /** Generate a time-limited share link for a file. */
  async shareFile(filename: string, ttl_hours?: number): Promise<ApiResponse<ShareLink>> {
    const body = ttl_hours !== undefined ? { ttl_hours } : {};
    return this.post<ShareLink>(`/v1/files/${encodeURIComponent(filename)}/share`, body);
  }

  // ──────────────────────────────────────────────
  // Models & Connectors — /v1/models, /v1/connectors
  // ──────────────────────────────────────────────

  /** List all available AI models. */
  async listModels(): Promise<ApiResponse<ModelInfo[]>> {
    return this.get<ModelInfo[]>('/v1/models');
  }

  /** List all external connectors and their status. */
  async listConnectors(): Promise<ApiResponse<ConnectorInfo[]>> {
    return this.get<ConnectorInfo[]>('/v1/connectors');
  }

  /** Connect (or reconfigure) an external service connector. */
  async connectService(name: string, config?: Record<string, unknown>): Promise<ApiResponse<ConnectorInfo>> {
    return this.post<ConnectorInfo>(`/v1/connectors/${encodeURIComponent(name)}/connect`, config ?? {});
  }

  // ──────────────────────────────────────────────
  // Push Notifications — /v1/push
  // ──────────────────────────────────────────────

  /** Register a device for push notifications. */
  async registerDevice(req: PushRegisterRequest): Promise<ApiResponse<{ registered: boolean }>> {
    return this.post<{ registered: boolean }>('/v1/push/register', req);
  }

  /** Send a push notification to a specific user. */
  async sendPush(req: PushSendRequest): Promise<ApiResponse<{ sent: boolean }>> {
    return this.post<{ sent: boolean }>('/v1/push/send', req);
  }

  // ──────────────────────────────────────────────
  // Frontier Browser — /v1/frontier
  // ──────────────────────────────────────────────

  /** Submit a new browser automation task. */
  async submitBrowserTask(req: FrontierSubmitRequest): Promise<ApiResponse<FrontierTask>> {
    return this.post<FrontierTask>('/v1/frontier/submit', req);
  }

  /** Cancel a running browser automation task. */
  async cancelBrowserTask(taskId: string): Promise<ApiResponse<{ cancelled: boolean }>> {
    return this.post<{ cancelled: boolean }>(`/v1/frontier/${encodeURIComponent(taskId)}/cancel`, {});
  }

  /** Get the current status and result of a browser task. */
  async getBrowserTask(taskId: string): Promise<ApiResponse<FrontierTask>> {
    return this.get<FrontierTask>(`/v1/frontier/${encodeURIComponent(taskId)}`);
  }

  /** List all browser tasks for the current user. */
  async listBrowserTasks(): Promise<ApiResponse<FrontierTask[]>> {
    return this.get<FrontierTask[]>('/v1/frontier');
  }

  /**
   * Stream live events from a running browser task as an async generator.
   */
  async *streamBrowserEvents(taskId: string): AsyncGenerator<StreamEvent> {
    const response = await this.rawFetch(
      `/v1/frontier/${encodeURIComponent(taskId)}/events`,
      { method: 'GET', headers: { Accept: 'text/event-stream' } },
    );

    if (!response.body) {
      throw new HorizonError('No response body for browser events', 500, 'NO_STREAM_BODY', requestId());
    }

    yield* this.readNDJSON<StreamEvent>(response.body);
  }

  // ──────────────────────────────────────────────
  // Architecture Billing — /v1/architecture
  // ──────────────────────────────────────────────

  /** Check whether the current user can access a specific architecture. */
  async checkArchitectureAccess(architecture: string): Promise<ApiResponse<ArchitectureAccess>> {
    return this.get<ArchitectureAccess>(`/v1/architecture/${encodeURIComponent(architecture)}/access`);
  }

  /** Estimate the cost of running with a specific architecture. */
  async estimateCost(
    architecture: string,
    params: Record<string, number>,
  ): Promise<ApiResponse<CostEstimate>> {
    return this.post<CostEstimate>(`/v1/architecture/${encodeURIComponent(architecture)}/estimate`, params);
  }

  // ──────────────────────────────────────────────
  // Admin — /v1/admin
  // ──────────────────────────────────────────────

  /** List all registered users (admin only). */
  async adminListUsers(): Promise<ApiResponse<UserProfile[]>> {
    return this.get<UserProfile[]>('/v1/admin/users');
  }

  /** Get platform-wide usage statistics (admin only). */
  async adminGetUsage(): Promise<ApiResponse<AdminUsageStats>> {
    return this.get<AdminUsageStats>('/v1/admin/usage');
  }

  /** Get platform health status (admin only). */
  async adminHealth(): Promise<ApiResponse<AdminHealthStatus>> {
    return this.get<AdminHealthStatus>('/v1/admin/health');
  }

  // ──────────────────────────────────────────────
  // WebSocket
  // ──────────────────────────────────────────────

  /**
   * Open a persistent WebSocket connection for real-time streaming events.
   * @param onEvent - Callback invoked for every received {@link StreamEvent}.
   * @param onClose - Optional callback invoked when the connection closes.
   * @param options - Optional WebSocket configuration overrides.
   * @returns A {@link WebSocketConnection} handle.
   */
  connectWebSocket(
    onEvent: (event: StreamEvent) => void,
    onClose?: () => void,
    options?: WebSocketOptions,
  ): WebSocketConnection {
    const wsUrl = this.baseUrl.replace(/^http/, 'ws') + '/v1/ws';
    const fullUrl = this.token ? `${wsUrl}?token=${encodeURIComponent(this.token)}` : wsUrl;

    return new HorizonWebSocket(
      fullUrl,
      {
        onEvent,
        onClose: onClose ? (_code, _reason) => onClose() : undefined,
      },
      options,
    );
  }

  // ──────────────────────────────────────────────
  // Internal HTTP helpers
  // ──────────────────────────────────────────────

  /** Build the full set of request headers. */
  private buildHeaders(extra?: Record<string, string>, isFormData?: boolean): Record<string, string> {
    const headers: Record<string, string> = {
      ...this.customHeaders,
      ...(extra ?? {}),
    };

    if (!isFormData) {
      headers['Content-Type'] = 'application/json';
    }
    headers['Accept'] = headers['Accept'] ?? 'application/json';
    headers['X-Request-ID'] = requestId();

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    } else if (this.apiKey) {
      headers['X-API-Key'] = this.apiKey;
    }

    return headers;
  }

  /** Perform a raw fetch with timeout support. */
  private async rawFetch(
    path: string,
    init: {
      method: string;
      body?: string | FormData;
      headers?: Record<string, string>;
      isFormData?: boolean;
    },
  ): Promise<Response> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(url, {
        method: init.method,
        headers: this.buildHeaders(init.headers, init.isFormData),
        body: init.body,
        signal: controller.signal,
      });
      return response;
    } catch (error: unknown) {
      const rid = requestId();
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new TimeoutError(`Request to ${path} timed out after ${this.timeout}ms`, rid);
      }
      throw new NetworkError(
        `Network error fetching ${path}: ${error instanceof Error ? error.message : String(error)}`,
        rid,
      );
    } finally {
      clearTimeout(timer);
    }
  }

  /** Parse a JSON response into an ApiResponse envelope, throwing on error status. */
  private async parseResponse<T>(response: Response): Promise<ApiResponse<T>> {
    const body = await response.json() as Record<string, unknown>;

    if (!response.ok) {
      throw createErrorFromResponse(
        response.status,
        body,
        response.headers.get('Retry-After'),
      );
    }

    return body as unknown as ApiResponse<T>;
  }

  /** GET with automatic retry on transient failures. */
  private async get<T>(path: string): Promise<ApiResponse<T>> {
    return this.requestWithRetry<T>('GET', path);
  }

  /** POST with automatic retry on transient failures. */
  private async post<T>(path: string, body: unknown): Promise<ApiResponse<T>> {
    return this.requestWithRetry<T>('POST', path, JSON.stringify(body));
  }

  /** Execute a request with retry logic for 502 / 503. */
  private async requestWithRetry<T>(
    method: string,
    path: string,
    body?: string,
  ): Promise<ApiResponse<T>> {
    let lastError: HorizonError | undefined;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const response = await this.rawFetch(path, { method, body });
        return await this.parseResponse<T>(response);
      } catch (error: unknown) {
        if (error instanceof HorizonError) {
          // Only retry on 502 / 503 (transient upstream failures).
          if ((error.status === 502 || error.status === 503) && attempt < this.maxRetries) {
            lastError = error;
            await sleep(Math.pow(2, attempt) * 500);
            continue;
          }
        }
        throw error;
      }
    }

    // Should not be reachable, but satisfies the compiler.
    throw lastError ?? new HorizonError('Unknown error', 500, 'UNKNOWN', requestId());
  }

  // ── Streaming helpers ──────────────────────────────────────────

  /** Read newline-delimited JSON from a ReadableStream. */
  private async *readNDJSON<T>(stream: ReadableStream<Uint8Array>): AsyncGenerator<T> {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.length === 0) continue;
          try {
            yield JSON.parse(trimmed) as T;
          } catch {
            // Skip malformed lines.
          }
        }
      }

      // Flush remaining buffer.
      if (buffer.trim().length > 0) {
        try {
          yield JSON.parse(buffer.trim()) as T;
        } catch {
          // Ignore.
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /** Read Server-Sent Events from a ReadableStream. */
  private async *readSSE(stream: ReadableStream<Uint8Array>): AsyncGenerator<SSEEvent> {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() ?? '';

        for (const part of parts) {
          const event = this.parseSSEFrame(part);
          if (event) yield event;
        }
      }

      // Flush remaining.
      if (buffer.trim().length > 0) {
        const event = this.parseSSEFrame(buffer);
        if (event) yield event;
      }
    } finally {
      reader.releaseLock();
    }
  }

  /** Parse a single SSE frame (multi-line block) into an SSEEvent. */
  private parseSSEFrame(frame: string): SSEEvent | null {
    let eventName = 'message';
    let data = '';

    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        data += (data ? '\n' : '') + line.slice(5).trim();
      }
    }

    if (!data) return null;
    return { event: eventName, data };
  }
}
