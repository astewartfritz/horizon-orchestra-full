/**
 * @module server
 * @description Production-grade Express server for the Horizon Orchestra
 * Node.js bridge.  Ties together security middleware, rate limiting,
 * request validation, HTTP proxying, WebSocket relay, SSE streaming,
 * health / readiness endpoints, and graceful shutdown.
 *
 * Start with:
 *   npm run dev      (tsx, auto-reload)
 *   npm start        (compiled JS)
 */

import express from 'express';
import helmet from 'helmet';
import cors from 'cors';
import compression from 'compression';
import rateLimit from 'express-rate-limit';
import { createServer } from 'node:http';

import { appConfig } from './config.js';
import { requestLogger, logger } from './middleware/logging.js';
import { authMiddleware } from './middleware/auth.js';
import { globalErrorHandler, notFoundHandler } from './middleware/error-handler.js';
import { autoValidate } from './validation.js';
import { proxyRequest, circuitBreaker } from './proxy.js';
import { attachWebSocketRelay, getConnectionMetrics, closeAllConnections } from './websocket-relay.js';
import { sseHandler } from './sse.js';

// ──────────────────────────────────────────────
// App initialisation
// ──────────────────────────────────────────────

const app = express();
const server = createServer(app);

// ── Security headers ────────────────────────────────────────────
app.use(helmet({
  contentSecurityPolicy: false, // Allow proxied content.
  crossOriginResourcePolicy: { policy: 'cross-origin' },
}));

// ── CORS ────────────────────────────────────────────────────────
app.use(cors({
  origin: appConfig.corsOrigins.includes('*')
    ? true
    : appConfig.corsOrigins,
  credentials: true,
  methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization', 'X-API-Key', 'X-Request-ID'],
  exposedHeaders: ['X-Request-ID', 'X-RateLimit-Remaining', 'Retry-After'],
}));

// ── Compression ─────────────────────────────────────────────────
app.use(compression());

// ── Body parsing ────────────────────────────────────────────────
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

// ── Request logging ─────────────────────────────────────────────
app.use(requestLogger);

// ── Rate limiting ───────────────────────────────────────────────
const limiter = rateLimit({
  windowMs: 60_000,
  max: appConfig.rateLimitPerMinute,
  standardHeaders: true,
  legacyHeaders: false,
  keyGenerator: (req) => {
    return req.ip ?? req.headers['x-forwarded-for']?.toString() ?? 'unknown';
  },
  handler: (_req, res) => {
    res.status(429).json({
      data: null,
      error: 'Too many requests — please slow down',
      code: 'RATE_LIMITED',
      meta: { request_id: 'unknown', duration_ms: 0 },
    });
  },
});
app.use(limiter);

// ── Trust proxy (needed for rate-limit behind reverse proxy) ───
app.set('trust proxy', 1);

// ──────────────────────────────────────────────
// Health & readiness
// ──────────────────────────────────────────────

const startedAt = Date.now();

/** GET /health — shallow health check (always 200 if the process is up). */
app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    uptime_seconds: Math.floor((Date.now() - startedAt) / 1000),
    timestamp: new Date().toISOString(),
  });
});

/** GET /ready — deep readiness probe (checks upstream + circuit). */
app.get('/ready', async (_req, res) => {
  const circuitState = circuitBreaker.currentState;

  // Attempt a lightweight ping to the Python backend.
  let pythonOk = false;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5_000);
    const upstream = await fetch(`${appConfig.pythonBackendUrl}/health`, {
      signal: controller.signal,
    });
    clearTimeout(timer);
    pythonOk = upstream.ok;
  } catch {
    pythonOk = false;
  }

  const ready = pythonOk && circuitState !== 'OPEN';

  res.status(ready ? 200 : 503).json({
    status: ready ? 'ready' : 'not_ready',
    python_backend: pythonOk ? 'reachable' : 'unreachable',
    circuit_breaker: circuitState,
    websocket_connections: getConnectionMetrics().length,
    uptime_seconds: Math.floor((Date.now() - startedAt) / 1000),
  });
});

// ── Metrics endpoint (optional) ─────────────────────────────────
if (appConfig.enableMetrics) {
  app.get('/metrics', (_req, res) => {
    const wsMetrics = getConnectionMetrics();
    res.json({
      uptime_seconds: Math.floor((Date.now() - startedAt) / 1000),
      circuit_breaker: circuitBreaker.currentState,
      websocket: {
        active_connections: wsMetrics.length,
        total_frames_relayed: wsMetrics.reduce((sum, m) => sum + m.framesRelayed, 0),
        total_bytes_relayed: wsMetrics.reduce((sum, m) => sum + m.bytesRelayed, 0),
      },
    });
  });
}

// ──────────────────────────────────────────────
// Auth middleware (applied to /v1/* routes)
// ──────────────────────────────────────────────

app.use('/v1', authMiddleware);

// ──────────────────────────────────────────────
// Validation middleware (applied to /v1/* routes)
// ──────────────────────────────────────────────

app.use('/v1', autoValidate);

// ──────────────────────────────────────────────
// SSE routes (must be defined before the catch-all proxy)
// ──────────────────────────────────────────────

app.post('/v1/run/sse', sseHandler);
app.get('/v1/frontier/:taskId/events', sseHandler);

// ──────────────────────────────────────────────
// Proxy catch-all — forward everything else to Python
// ──────────────────────────────────────────────

app.all('/v1/*', async (req, res, next) => {
  try {
    await proxyRequest(req, res);
  } catch (error) {
    next(error);
  }
});

// ──────────────────────────────────────────────
// 404 + Error handlers (must be last)
// ──────────────────────────────────────────────

app.use(notFoundHandler);
app.use(globalErrorHandler);

// ──────────────────────────────────────────────
// WebSocket relay
// ──────────────────────────────────────────────

const wss = attachWebSocketRelay(server);

// ──────────────────────────────────────────────
// Start listening
// ──────────────────────────────────────────────

server.listen(appConfig.port, () => {
  logger.info(
    {
      port: appConfig.port,
      pythonBackend: appConfig.pythonBackendUrl,
      corsOrigins: appConfig.corsOrigins,
      rateLimit: appConfig.rateLimitPerMinute,
      env: appConfig.nodeEnv,
    },
    `Horizon Orchestra Node.js bridge listening on :${appConfig.port}`,
  );
});

// ──────────────────────────────────────────────
// Graceful shutdown
// ──────────────────────────────────────────────

/** Maximum time to wait for in-flight requests during shutdown. */
const SHUTDOWN_TIMEOUT_MS = 15_000;

/**
 * Perform an orderly shutdown:
 * 1. Stop accepting new connections.
 * 2. Close all WebSocket relays.
 * 3. Wait for in-flight HTTP requests to drain.
 * 4. Exit the process.
 */
function gracefulShutdown(signal: string): void {
  logger.info({ signal }, 'Received shutdown signal — starting graceful shutdown');

  // Stop accepting new connections.
  server.close(() => {
    logger.info('HTTP server closed');
    process.exit(0);
  });

  // Close WebSocket connections.
  closeAllConnections();
  wss.close(() => {
    logger.info('WebSocket server closed');
  });

  // Force exit after timeout to prevent hanging.
  setTimeout(() => {
    logger.warn('Graceful shutdown timed out — forcing exit');
    process.exit(1);
  }, SHUTDOWN_TIMEOUT_MS);
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

// Catch unhandled rejections to prevent silent crashes.
process.on('unhandledRejection', (reason) => {
  logger.error({ reason }, 'Unhandled promise rejection');
});

process.on('uncaughtException', (error) => {
  logger.fatal({ error: error.message, stack: error.stack }, 'Uncaught exception — shutting down');
  process.exit(1);
});

// ──────────────────────────────────────────────
// Exports (for testing / programmatic use)
// ──────────────────────────────────────────────

export { app, server, wss };
