/**
 * @module types
 * @description Complete API type definitions for Horizon Orchestra.
 * Maps 1:1 with Python Pydantic models across all 29 API routes.
 */

// ──────────────────────────────────────────────
// Shared / Envelope
// ──────────────────────────────────────────────

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

// ──────────────────────────────────────────────
// Auth — /v1/auth/*
// ──────────────────────────────────────────────

/** POST /v1/auth/register — create a new account. */
export interface RegisterRequest {
  email: string;
  name: string;
  password: string;
}

/** POST /v1/auth/login — obtain tokens. */
export interface LoginRequest {
  email: string;
  password: string;
}

/** POST /v1/auth/refresh — exchange a refresh token. */
export interface RefreshRequest {
  refresh_token: string;
}

/** Response returned by all authentication endpoints. */
export interface AuthResponse {
  user_id: string;
  email: string;
  name: string;
  token: string;
  refresh_token: string;
  tier: string;
}

/** GET /v1/auth/me — current user profile. */
export interface UserProfile {
  user_id: string;
  email: string;
  name: string;
  tier: string;
  created_at: string;
}

// ──────────────────────────────────────────────
// Task Execution — /v1/run, /v1/query
// ──────────────────────────────────────────────

/** Supported agent architectures. */
export type AgentType = 'monolithic' | 'rag' | 'swarm' | 'mcp' | 'production';

/** Architecture variant identifiers. */
export type Architecture = 'A' | 'B' | 'C' | 'D' | 'E';

/** POST /v1/run — execute a task through an agent. */
export interface RunRequest {
  task: string;
  agent_type?: AgentType;
  context?: Record<string, unknown>;
  model?: string;
  stream?: boolean;
  architecture?: Architecture;
}

/** Response from a synchronous task run. */
export interface RunResponse {
  result: string;
  tool_calls: number;
  tokens_used: number;
  duration_ms: number;
  architecture: string;
}

/** POST /v1/query — direct model query without agent routing. */
export interface QueryRequest {
  prompt: string;
  model?: string;
  system?: string;
  temperature?: number;
  max_tokens?: number;
}

/** Token usage breakdown for a query. */
export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

/** Response from a direct model query. */
export interface QueryResponse {
  content: string;
  model: string;
  usage: TokenUsage;
}

// ──────────────────────────────────────────────
// Billing & Subscription — /v1/billing/*
// ──────────────────────────────────────────────

/** POST /v1/billing/checkout — create a Stripe checkout session. */
export interface CheckoutRequest {
  tier: string;
  success_url: string;
  cancel_url: string;
}

/** POST /v1/billing/portal — create a Stripe customer portal link. */
export interface PortalRequest {
  return_url: string;
}

/** Current subscription details. */
export interface Subscription {
  tier: string;
  status: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
}

/** Aggregated usage counters for the current billing period. */
export interface UsageData {
  requests_used_today: number;
  tokens_used_this_month: number;
  agents_active: number;
}

/** A single invoice record. */
export interface Invoice {
  id: string;
  amount: number;
  status: string;
  period_start: string;
  period_end: string;
  pdf_url?: string;
}

// ──────────────────────────────────────────────
// Memory — /v1/memory/*
// ──────────────────────────────────────────────

/** POST /v1/memory/search — semantic search across memory entries. */
export interface MemorySearchRequest {
  query: string;
  limit?: number;
  filters?: Record<string, unknown>;
}

/** POST /v1/memory/store — persist a new memory entry. */
export interface MemoryStoreRequest {
  content: string;
  metadata?: Record<string, unknown>;
  tags?: string[];
}

/** A single memory entry returned by search or list. */
export interface MemoryEntry {
  id: string;
  content: string;
  category: string;
  score: number;
  created_at: string;
}

// ──────────────────────────────────────────────
// Files — /v1/files/*
// ──────────────────────────────────────────────

/** Metadata about an uploaded file. */
export interface FileInfo {
  filename: string;
  size_bytes: number;
  content_type: string;
  uploaded_at: string;
}

/** A time-limited shareable link to a file. */
export interface ShareLink {
  url: string;
  expires_at: string;
}

// ──────────────────────────────────────────────
// Models & Connectors — /v1/models, /v1/connectors
// ──────────────────────────────────────────────

/** Information about a supported AI model. */
export interface ModelInfo {
  model_id: string;
  provider: string;
  strengths: string[];
  cost_input: number;
  cost_output: number;
}

/** Status and capabilities of an external connector. */
export interface ConnectorInfo {
  name: string;
  connected: boolean;
  description: string;
  tools: string[];
}

/** Configuration sent when connecting an external service. */
export interface ConnectorConfig {
  [key: string]: unknown;
}

// ──────────────────────────────────────────────
// Push Notifications — /v1/push/*
// ──────────────────────────────────────────────

/** Supported push notification platforms. */
export type PushPlatform = 'apns' | 'fcm';

/** POST /v1/push/register — register a device for push notifications. */
export interface PushRegisterRequest {
  device_token: string;
  platform: PushPlatform;
  device_id: string;
}

/** POST /v1/push/send — send a push notification to a user. */
export interface PushSendRequest {
  user_id: string;
  title: string;
  body: string;
  data?: Record<string, unknown>;
}

// ──────────────────────────────────────────────
// WebSocket / Streaming
// ──────────────────────────────────────────────

/** Event types emitted over WebSocket and SSE connections. */
export type StreamEventType =
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'thinking'
  | 'final_answer'
  | 'error'
  | 'billing_update';

/** A single event emitted during streaming execution. */
export interface StreamEvent {
  type: StreamEventType;
  data: Record<string, unknown>;
  timestamp: number;
}

/** A Server-Sent Events frame. */
export interface SSEEvent {
  event: string;
  data: string;
}

// ──────────────────────────────────────────────
// Frontier Browser — /v1/frontier/*
// ──────────────────────────────────────────────

/** Status of a frontier browser automation task. */
export type FrontierTaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

/** Full details of a browser automation task. */
export interface FrontierTask {
  task_id: string;
  description: string;
  status: FrontierTaskStatus | string;
  result?: string;
  extracted_data?: Record<string, unknown>;
  pages_visited?: string[];
  error?: string;
}

/** POST /v1/frontier/submit — submit a new browser automation task. */
export interface FrontierSubmitRequest {
  description: string;
  start_url?: string;
  max_steps?: number;
  timeout_seconds?: number;
}

// ──────────────────────────────────────────────
// Architecture Billing — /v1/architecture/*
// ──────────────────────────────────────────────

/** Estimated cost for executing with a specific architecture. */
export interface CostEstimate {
  architecture: string;
  total_units: number;
  multiplier: number;
  within_tier_limits: boolean;
  breakdown: Record<string, number>;
  warnings: string[];
}

/** Whether the user has access to a specific architecture. */
export interface ArchitectureAccess {
  allowed: boolean;
  reason: string;
  tier: string;
  architecture: string;
  upgrade_options: string[];
}

// ──────────────────────────────────────────────
// Admin — /v1/admin/*
// ──────────────────────────────────────────────

/** Admin-level usage statistics. */
export interface AdminUsageStats {
  total_users: number;
  active_users_today: number;
  total_requests_today: number;
  total_tokens_today: number;
  revenue_this_month: number;
  [key: string]: unknown;
}

/** Admin-level health check details. */
export interface AdminHealthStatus {
  status: string;
  uptime_seconds: number;
  python_backend: string;
  database: string;
  redis: string;
  [key: string]: unknown;
}

// ──────────────────────────────────────────────
// SDK Configuration
// ──────────────────────────────────────────────

/** Configuration options for the HorizonClient constructor. */
export interface HorizonClientConfig {
  /** Base URL of the Horizon Orchestra API (e.g. https://api.horizon.ai). */
  baseUrl: string;
  /** API key for server-to-server authentication. */
  apiKey?: string;
  /** Bearer token for user-scoped requests. */
  token?: string;
  /** Request timeout in milliseconds (default: 30000). */
  timeout?: number;
  /** Maximum number of retries on transient failures (default: 3). */
  maxRetries?: number;
  /** Custom headers to include on every request. */
  headers?: Record<string, string>;
}

/** Interface for an active WebSocket connection. */
export interface WebSocketConnection {
  /** Send a text message over the connection. */
  send(message: string): void;
  /** Cleanly close the connection. */
  close(): void;
  /** Current connection state (mirrors WebSocket.readyState). */
  readonly readyState: number;
}

/** Options controlling WebSocket reconnection behaviour. */
export interface WebSocketOptions {
  /** Auto-reconnect on unexpected close (default: true). */
  autoReconnect?: boolean;
  /** Maximum number of reconnection attempts (default: 10). */
  maxReconnectAttempts?: number;
  /** Initial reconnect delay in milliseconds (default: 1000). */
  reconnectDelay?: number;
  /** Maximum reconnect delay in milliseconds (default: 30000). */
  maxReconnectDelay?: number;
  /** Heartbeat interval in milliseconds (default: 30000). */
  heartbeatInterval?: number;
  /** Heartbeat timeout in milliseconds (default: 10000). */
  heartbeatTimeout?: number;
  /** Protocols to request during the handshake. */
  protocols?: string[];
}

/** Callback signatures for WebSocket lifecycle events. */
export interface WebSocketCallbacks {
  onEvent: (event: StreamEvent) => void;
  onClose?: (code: number, reason: string) => void;
  onError?: (error: Error) => void;
  onReconnect?: (attempt: number) => void;
}
