/**
 * @module types
 * @description Duplicate of SDK types for use within the Node.js bridge.
 *
 * The canonical type definitions live in `@horizon-orchestra/sdk`.
 * These are re-declared here to avoid cross-project rootDir issues
 * during compilation.  Keep in sync with the SDK `src/types.ts`.
 */

// ── Envelope ──────────────────────────────────────────────────────

/** Standard API response envelope wrapping every endpoint return value. */
export interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  meta: ResponseMeta;
}

/** Metadata attached to every API response. */
export interface ResponseMeta {
  request_id: string;
  duration_ms: number;
}

/** Pagination parameters accepted by list endpoints. */
export interface PaginationParams {
  offset?: number;
  limit?: number;
}

/** Paginated list envelope for collection endpoints. */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

// ── Auth ──────────────────────────────────────────────────────────

export interface RegisterRequest { email: string; name: string; password: string; }
export interface LoginRequest { email: string; password: string; }
export interface RefreshRequest { refresh_token: string; }
export interface AuthResponse { user_id: string; email: string; name: string; token: string; refresh_token: string; tier: string; }
export interface UserProfile { user_id: string; email: string; name: string; tier: string; created_at: string; }

// ── Task Execution ────────────────────────────────────────────────

export type AgentType = 'monolithic' | 'rag' | 'swarm' | 'mcp' | 'production';
export type Architecture = 'A' | 'B' | 'C' | 'D' | 'E';

export interface RunRequest { task: string; agent_type?: AgentType; context?: Record<string, unknown>; model?: string; stream?: boolean; architecture?: Architecture; }
export interface RunResponse { result: string; tool_calls: number; tokens_used: number; duration_ms: number; architecture: string; }
export interface QueryRequest { prompt: string; model?: string; system?: string; temperature?: number; max_tokens?: number; }
export interface TokenUsage { input_tokens: number; output_tokens: number; }
export interface QueryResponse { content: string; model: string; usage: TokenUsage; }

// ── Billing ───────────────────────────────────────────────────────

export interface CheckoutRequest { tier: string; success_url: string; cancel_url: string; }
export interface PortalRequest { return_url: string; }
export interface Subscription { tier: string; status: string; current_period_end: string; cancel_at_period_end: boolean; }
export interface UsageData { requests_used_today: number; tokens_used_this_month: number; agents_active: number; }
export interface Invoice { id: string; amount: number; status: string; period_start: string; period_end: string; pdf_url?: string; }

// ── Memory ────────────────────────────────────────────────────────

export interface MemorySearchRequest { query: string; limit?: number; filters?: Record<string, unknown>; }
export interface MemoryStoreRequest { content: string; metadata?: Record<string, unknown>; tags?: string[]; }
export interface MemoryEntry { id: string; content: string; category: string; score: number; created_at: string; }

// ── Files ─────────────────────────────────────────────────────────

export interface FileInfo { filename: string; size_bytes: number; content_type: string; uploaded_at: string; }
export interface ShareLink { url: string; expires_at: string; }

// ── Models & Connectors ───────────────────────────────────────────

export interface ModelInfo { model_id: string; provider: string; strengths: string[]; cost_input: number; cost_output: number; }
export interface ConnectorInfo { name: string; connected: boolean; description: string; tools: string[]; }
export interface ConnectorConfig { [key: string]: unknown; }

// ── Push ──────────────────────────────────────────────────────────

export type PushPlatform = 'apns' | 'fcm';
export interface PushRegisterRequest { device_token: string; platform: PushPlatform; device_id: string; }
export interface PushSendRequest { user_id: string; title: string; body: string; data?: Record<string, unknown>; }

// ── Streaming ─────────────────────────────────────────────────────

export type StreamEventType = 'token' | 'tool_call' | 'tool_result' | 'thinking' | 'final_answer' | 'error' | 'billing_update';
export interface StreamEvent { type: StreamEventType; data: Record<string, unknown>; timestamp: number; }
export interface SSEEvent { event: string; data: string; }

// ── Frontier ──────────────────────────────────────────────────────

export type FrontierTaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
export interface FrontierTask { task_id: string; description: string; status: FrontierTaskStatus | string; result?: string; extracted_data?: Record<string, unknown>; pages_visited?: string[]; error?: string; }
export interface FrontierSubmitRequest { description: string; start_url?: string; max_steps?: number; timeout_seconds?: number; }

// ── Architecture Billing ──────────────────────────────────────────

export interface CostEstimate { architecture: string; total_units: number; multiplier: number; within_tier_limits: boolean; breakdown: Record<string, number>; warnings: string[]; }
export interface ArchitectureAccess { allowed: boolean; reason: string; tier: string; architecture: string; upgrade_options: string[]; }

// ── Admin ─────────────────────────────────────────────────────────

export interface AdminUsageStats { total_users: number; active_users_today: number; total_requests_today: number; total_tokens_today: number; revenue_this_month: number; [key: string]: unknown; }
export interface AdminHealthStatus { status: string; uptime_seconds: number; python_backend: string; database: string; redis: string; [key: string]: unknown; }

// ── SDK Config ────────────────────────────────────────────────────

export interface HorizonClientConfig { baseUrl: string; apiKey?: string; token?: string; timeout?: number; maxRetries?: number; headers?: Record<string, string>; }
export interface WebSocketConnection { send(message: string): void; close(): void; readonly readyState: number; }
export interface WebSocketOptions { autoReconnect?: boolean; maxReconnectAttempts?: number; reconnectDelay?: number; maxReconnectDelay?: number; heartbeatInterval?: number; heartbeatTimeout?: number; protocols?: string[]; }
export interface WebSocketCallbacks { onEvent: (event: StreamEvent) => void; onClose?: (code: number, reason: string) => void; onError?: (error: Error) => void; onReconnect?: (attempt: number) => void; }
