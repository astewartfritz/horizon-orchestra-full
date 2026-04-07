/**
 * @module proxy
 * @description HTTP reverse proxy that forwards /v1/* requests to the
 * upstream Python FastAPI backend.  Includes a circuit breaker that trips
 * after consecutive failures, exponential-backoff retries on 502/503, and
 * configurable timeouts.
 */

import type { Request, Response } from 'express';
import { Readable } from 'node:stream';
import { appConfig } from './config.js';
import { logger } from './middleware/logging.js';

// ──────────────────────────────────────────────
// Circuit Breaker
// ──────────────────────────────────────────────

/** Possible states of the circuit breaker. */
const enum CircuitState {
  Closed = 'CLOSED',
  Open = 'OPEN',
  HalfOpen = 'HALF_OPEN',
}

/** Simple circuit breaker protecting the upstream proxy calls. */
class CircuitBreaker {
  private state: CircuitState = CircuitState.Closed;
  private failures = 0;
  private lastFailureTime = 0;
  private readonly threshold: number;
  private readonly resetMs: number;

  constructor(threshold: number, resetMs: number) {
    this.threshold = threshold;
    this.resetMs = resetMs;
  }

  /** Whether the circuit currently allows requests through. */
  get isOpen(): boolean {
    if (this.state === CircuitState.Open) {
      // Transition to half-open once the reset window elapses.
      if (Date.now() - this.lastFailureTime >= this.resetMs) {
        this.state = CircuitState.HalfOpen;
        logger.info('Circuit breaker transitioning to HALF_OPEN');
        return false;
      }
      return true;
    }
    return false;
  }

  /** Record a successful upstream response, resetting the breaker. */
  recordSuccess(): void {
    if (this.state === CircuitState.HalfOpen) {
      logger.info('Circuit breaker closing after successful probe');
    }
    this.failures = 0;
    this.state = CircuitState.Closed;
  }

  /** Record a failed upstream response. Opens the circuit if threshold is exceeded. */
  recordFailure(): void {
    this.failures++;
    this.lastFailureTime = Date.now();
    if (this.failures >= this.threshold) {
      this.state = CircuitState.Open;
      logger.error(
        { failures: this.failures },
        `Circuit breaker OPEN after ${this.failures} consecutive failures`,
      );
    }
  }

  /** Current state for health-check reporting. */
  get currentState(): string {
    return this.state;
  }
}

/** Shared circuit breaker instance. */
export const circuitBreaker = new CircuitBreaker(
  appConfig.circuitBreakerThreshold,
  appConfig.circuitBreakerResetMs,
);

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

/** Sleep for `ms` milliseconds. */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Headers that should not be forwarded. */
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

/** Construct a filtered header record suitable for forwarding. */
function forwardHeaders(
  incoming: Record<string, string | string[] | undefined>,
  requestId: string,
  clientIp: string | undefined,
): Record<string, string> {
  const out: Record<string, string> = {};

  for (const [key, value] of Object.entries(incoming)) {
    if (HOP_BY_HOP.has(key.toLowerCase())) continue;
    if (value === undefined) continue;
    out[key] = Array.isArray(value) ? value.join(', ') : value;
  }

  // Inject tracing / forwarding headers.
  out['X-Request-ID'] = requestId;
  if (clientIp) {
    out['X-Forwarded-For'] = clientIp;
  }

  return out;
}

// ──────────────────────────────────────────────
// Proxy handler
// ──────────────────────────────────────────────

/**
 * Forward an Express request to the Python backend, streaming the
 * response back to the original client.
 *
 * Implements:
 * - Timeout (configurable via {@link appConfig.requestTimeoutMs})
 * - Retry with exponential back-off on 502 / 503
 * - Circuit breaker trip after consecutive failures
 */
export async function proxyRequest(req: Request, res: Response): Promise<void> {
  const requestId = req.requestId ?? 'unknown';

  // ── Circuit breaker gate ──────────────────────────────────────
  if (circuitBreaker.isOpen) {
    logger.warn({ requestId }, 'Circuit breaker is OPEN — rejecting request');
    res.status(503).json({
      data: null,
      error: 'Service temporarily unavailable (circuit breaker open)',
      code: 'CIRCUIT_OPEN',
      meta: { request_id: requestId, duration_ms: 0 },
    });
    return;
  }

  const upstreamUrl = `${appConfig.pythonBackendUrl}${req.originalUrl}`;
  const headers = forwardHeaders(
    req.headers as Record<string, string | string[] | undefined>,
    requestId,
    req.ip,
  );

  // Collect request body (Express may have already parsed it).
  let bodyPayload: string | undefined;
  if (['POST', 'PUT', 'PATCH'].includes(req.method)) {
    bodyPayload = JSON.stringify(req.body);
    headers['Content-Type'] = 'application/json';
  }

  let lastStatus = 0;
  const maxAttempts = appConfig.proxyRetries + 1;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), appConfig.requestTimeoutMs);

    try {
      const upstream = await fetch(upstreamUrl, {
        method: req.method,
        headers,
        body: bodyPayload,
        signal: controller.signal,
      });

      clearTimeout(timer);
      lastStatus = upstream.status;

      // Retry on transient upstream errors.
      if ((upstream.status === 502 || upstream.status === 503) && attempt < maxAttempts) {
        circuitBreaker.recordFailure();
        const backoff = Math.pow(2, attempt - 1) * 500;
        logger.warn({ requestId, attempt, status: upstream.status, backoffMs: backoff }, 'Retrying proxy request');
        await sleep(backoff);
        continue;
      }

      // Successful (or non-retryable) response — forward to client.
      circuitBreaker.recordSuccess();

      res.status(upstream.status);

      // Forward response headers.
      upstream.headers.forEach((value, key) => {
        if (!HOP_BY_HOP.has(key.toLowerCase())) {
          res.setHeader(key, value);
        }
      });

      // Stream the body.
      if (upstream.body) {
        const nodeStream = Readable.fromWeb(upstream.body as ReadableStream<Uint8Array>);
        nodeStream.pipe(res);
      } else {
        res.end();
      }

      return;
    } catch (error: unknown) {
      clearTimeout(timer);
      circuitBreaker.recordFailure();

      const isAbort = error instanceof DOMException && error.name === 'AbortError';
      const message = isAbort
        ? `Upstream timeout after ${appConfig.requestTimeoutMs}ms`
        : `Upstream network error: ${error instanceof Error ? error.message : String(error)}`;

      logger.error({ requestId, attempt, error: message }, 'Proxy error');

      if (attempt < maxAttempts) {
        const backoff = Math.pow(2, attempt - 1) * 500;
        await sleep(backoff);
        continue;
      }

      const statusCode = isAbort ? 504 : 502;
      res.status(statusCode).json({
        data: null,
        error: message,
        code: isAbort ? 'UPSTREAM_TIMEOUT' : 'UPSTREAM_ERROR',
        meta: { request_id: requestId, duration_ms: 0 },
      });
      return;
    }
  }

  // Fallback — should not be reached.
  res.status(lastStatus || 502).json({
    data: null,
    error: 'Proxy request failed after all retries',
    code: 'PROXY_EXHAUSTED',
    meta: { request_id: requestId, duration_ms: 0 },
  });
}
