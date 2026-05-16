/**
 * @module @horizon-orchestra/sdk
 * @description Public API surface for the Horizon Orchestra TypeScript SDK.
 *
 * @example
 * ```ts
 * import { HorizonClient } from '@horizon-orchestra/sdk';
 *
 * const client = new HorizonClient({ baseUrl: 'https://api.horizon.ai' });
 * const { data } = await client.login({ email: 'user@example.com', password: 'secret' });
 * client.setToken(data!.token);
 * ```
 */

// ── Client ────────────────────────────────────────────────────────
export { HorizonClient } from './client.js';

// ── WebSocket ─────────────────────────────────────────────────────
export { HorizonWebSocket } from './websocket.js';

// ── Errors ────────────────────────────────────────────────────────
export {
  HorizonError,
  AuthError,
  BillingError,
  RateLimitError,
  ValidationError,
  TimeoutError,
  ServerError,
  NetworkError,
  createErrorFromResponse,
} from './errors.js';

// ── Types ─────────────────────────────────────────────────────────
export type {
  // Envelope
  ApiResponse,
  ResponseMeta,
  PaginationParams,
  PaginatedResponse,
  // Auth
  RegisterRequest,
  LoginRequest,
  RefreshRequest,
  AuthResponse,
  UserProfile,
  // Task execution
  AgentType,
  Architecture,
  RunRequest,
  RunResponse,
  QueryRequest,
  TokenUsage,
  QueryResponse,
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
  ConnectorConfig,
  // Push
  PushPlatform,
  PushRegisterRequest,
  PushSendRequest,
  // Streaming
  StreamEventType,
  StreamEvent,
  SSEEvent,
  // Frontier
  FrontierTaskStatus,
  FrontierTask,
  FrontierSubmitRequest,
  // Architecture billing
  CostEstimate,
  ArchitectureAccess,
  // Admin
  AdminUsageStats,
  AdminHealthStatus,
  // Config
  HorizonClientConfig,
  WebSocketConnection,
  WebSocketOptions,
  WebSocketCallbacks,
} from './types.js';
