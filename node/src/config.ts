/**
 * @module config
 * @description Centralised configuration for the Node.js bridge server.
 * Values are drawn from environment variables with sensible defaults.
 */

import { config as loadDotenv } from 'dotenv';

// Load .env in development — silently ignored if the file is absent.
loadDotenv();

/** Application configuration. */
export interface Config {
  /** Port the HTTP server listens on (default: 3001). */
  port: number;
  /** URL of the upstream Python FastAPI backend (default: http://localhost:8000). */
  pythonBackendUrl: string;
  /** WebSocket URL of the upstream Python backend (derived from pythonBackendUrl). */
  pythonWsUrl: string;
  /** Allowed CORS origins (default: ["*"]). */
  corsOrigins: string[];
  /** Maximum requests per minute per IP (default: 100). */
  rateLimitPerMinute: number;
  /** WebSocket heartbeat interval in ms (default: 30 000). */
  wsHeartbeatMs: number;
  /** HTTP proxy request timeout in ms (default: 30 000). */
  requestTimeoutMs: number;
  /** Minimum log level for pino (default: "info"). */
  logLevel: string;
  /** Whether to expose Prometheus-style metrics (default: true). */
  enableMetrics: boolean;
  /** JWT secret used to verify bearer tokens. */
  jwtSecret: string;
  /** Number of consecutive proxy failures before circuit opens (default: 5). */
  circuitBreakerThreshold: number;
  /** Time in ms before a tripped circuit attempts a probe (default: 30 000). */
  circuitBreakerResetMs: number;
  /** Maximum proxy retry attempts on 502/503 (default: 3). */
  proxyRetries: number;
  /** Node environment (default: "development"). */
  nodeEnv: string;
}

/**
 * Parse a comma-separated string into an array, trimming whitespace.
 * Returns `fallback` when the input is empty or undefined.
 */
function parseList(value: string | undefined, fallback: string[]): string[] {
  if (!value || value.trim().length === 0) return fallback;
  return value.split(',').map((s) => s.trim()).filter(Boolean);
}

/**
 * Parse an integer from an environment variable, returning `fallback`
 * when the value is missing or non-numeric.
 */
function parseIntEnv(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = parseInt(value, 10);
  return Number.isNaN(parsed) ? fallback : parsed;
}

/**
 * Parse a boolean from an environment variable.
 * Recognises "true", "1", and "yes" as truthy (case-insensitive).
 */
function parseBoolEnv(value: string | undefined, fallback: boolean): boolean {
  if (!value) return fallback;
  return ['true', '1', 'yes'].includes(value.toLowerCase());
}

/**
 * Build a fully-resolved {@link Config} from environment variables.
 */
export function loadConfig(): Config {
  const pythonBackendUrl = (
    process.env['PYTHON_BACKEND_URL'] ?? 'http://localhost:8000'
  ).replace(/\/+$/, '');

  const pythonWsUrl = pythonBackendUrl.replace(/^http/, 'ws');

  return {
    port: parseIntEnv(process.env['PORT'], 3001),
    pythonBackendUrl,
    pythonWsUrl,
    corsOrigins: parseList(process.env['CORS_ORIGINS'], ['*']),
    rateLimitPerMinute: parseIntEnv(process.env['RATE_LIMIT_PER_MIN'], 100),
    wsHeartbeatMs: parseIntEnv(process.env['WS_HEARTBEAT_MS'], 30_000),
    requestTimeoutMs: parseIntEnv(process.env['REQUEST_TIMEOUT_MS'], 30_000),
    logLevel: process.env['LOG_LEVEL'] ?? 'info',
    enableMetrics: parseBoolEnv(process.env['ENABLE_METRICS'], true),
    jwtSecret: process.env['JWT_SECRET'] ?? 'change-me-in-production',
    circuitBreakerThreshold: parseIntEnv(process.env['CIRCUIT_BREAKER_THRESHOLD'], 5),
    circuitBreakerResetMs: parseIntEnv(process.env['CIRCUIT_BREAKER_RESET_MS'], 30_000),
    proxyRetries: parseIntEnv(process.env['PROXY_RETRIES'], 3),
    nodeEnv: process.env['NODE_ENV'] ?? 'development',
  };
}

/** Singleton config instance for the running process. */
export const appConfig: Config = loadConfig();
