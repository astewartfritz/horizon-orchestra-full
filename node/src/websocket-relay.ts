/**
 * @module websocket-relay
 * @description Bidirectional WebSocket relay between browser clients and
 * the Python backend.  Each client connection spawns a corresponding
 * upstream connection.  Heartbeat / ping-pong keeps both legs alive.
 *
 * Features:
 * - Frame-level relay (text & binary)
 * - Heartbeat with configurable interval
 * - Auto-reconnect to the upstream Python backend on drop
 * - Per-connection metrics (frames relayed, bytes, latency)
 * - Graceful teardown when either side closes
 */

import { WebSocket, WebSocketServer } from 'ws';
import type { Server as HttpServer } from 'node:http';
import type { IncomingMessage } from 'node:http';
import { URL } from 'node:url';
import { appConfig } from './config.js';
import { logger } from './middleware/logging.js';

// ──────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────

/** Per-connection tracking data. */
interface ConnectionMetrics {
  clientId: string;
  connectedAt: number;
  framesRelayed: number;
  bytesRelayed: number;
  lastActivityAt: number;
}

/** Per-connection context stored alongside the client WebSocket. */
interface RelayConnection {
  client: WebSocket;
  upstream: WebSocket | null;
  metrics: ConnectionMetrics;
  heartbeatTimer: ReturnType<typeof setInterval> | null;
  heartbeatPending: boolean;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  reconnectAttempts: number;
  intentionallyClosed: boolean;
}

// ──────────────────────────────────────────────
// State
// ──────────────────────────────────────────────

const connections = new Map<string, RelayConnection>();
let connectionCounter = 0;

// ──────────────────────────────────────────────
// Public API
// ──────────────────────────────────────────────

/**
 * Attach a WebSocket relay to an existing HTTP server.
 * Upgrades matching requests and establishes bidirectional relaying.
 *
 * @param server - The Node.js HTTP server to attach to.
 * @returns The underlying WebSocketServer for lifecycle control.
 */
export function attachWebSocketRelay(server: HttpServer): WebSocketServer {
  const wss = new WebSocketServer({ noServer: true });

  server.on('upgrade', (req: IncomingMessage, socket, head) => {
    const pathname = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`).pathname;

    if (pathname === '/v1/ws') {
      wss.handleUpgrade(req, socket, head, (ws) => {
        wss.emit('connection', ws, req);
      });
    } else {
      socket.destroy();
    }
  });

  wss.on('connection', (clientWs: WebSocket, req: IncomingMessage) => {
    handleNewClient(clientWs, req);
  });

  logger.info('WebSocket relay attached on /v1/ws');
  return wss;
}

/**
 * Return a snapshot of current connection metrics.
 */
export function getConnectionMetrics(): ConnectionMetrics[] {
  return Array.from(connections.values()).map((c) => ({ ...c.metrics }));
}

/**
 * Gracefully close all relay connections.
 */
export function closeAllConnections(): void {
  for (const [id, conn] of connections) {
    teardown(id, conn, 1001, 'Server shutting down');
  }
}

// ──────────────────────────────────────────────
// Internals
// ──────────────────────────────────────────────

/** Extract a bearer token from the query string or headers. */
function extractToken(req: IncomingMessage): string | undefined {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
  const fromQuery = url.searchParams.get('token');
  if (fromQuery) return fromQuery;

  const authHeader = req.headers['authorization'];
  if (authHeader?.startsWith('Bearer ')) return authHeader.slice(7);

  return undefined;
}

/** Set up a new client connection and its upstream counterpart. */
function handleNewClient(clientWs: WebSocket, req: IncomingMessage): void {
  connectionCounter++;
  const clientId = `ws-${connectionCounter}-${Date.now().toString(36)}`;

  const conn: RelayConnection = {
    client: clientWs,
    upstream: null,
    metrics: {
      clientId,
      connectedAt: Date.now(),
      framesRelayed: 0,
      bytesRelayed: 0,
      lastActivityAt: Date.now(),
    },
    heartbeatTimer: null,
    heartbeatPending: false,
    reconnectTimer: null,
    reconnectAttempts: 0,
    intentionallyClosed: false,
  };

  connections.set(clientId, conn);

  const token = extractToken(req);
  logger.info({ clientId, ip: req.socket.remoteAddress }, 'Client connected');

  // Open upstream connection.
  connectUpstream(clientId, conn, token);

  // ── Client event handlers ───────────────────────────────────
  clientWs.on('message', (data, isBinary) => {
    conn.metrics.lastActivityAt = Date.now();

    // Handle pong responses for heartbeat.
    if (!isBinary && data.toString() === 'pong') {
      conn.heartbeatPending = false;
      return;
    }

    // Relay to upstream.
    if (conn.upstream?.readyState === WebSocket.OPEN) {
      const payload = isBinary ? data as Buffer : data.toString();
      conn.upstream.send(payload);
      conn.metrics.framesRelayed++;
      conn.metrics.bytesRelayed += typeof payload === 'string' ? Buffer.byteLength(payload) : (payload as Buffer).length;
    }
  });

  clientWs.on('close', (code, reason) => {
    logger.info({ clientId, code, reason: reason.toString() }, 'Client disconnected');
    conn.intentionallyClosed = true;
    teardown(clientId, conn, code, reason.toString());
  });

  clientWs.on('error', (err) => {
    logger.error({ clientId, error: err.message }, 'Client WebSocket error');
  });

  // ── Heartbeat ───────────────────────────────────────────────
  conn.heartbeatTimer = setInterval(() => {
    if (conn.heartbeatPending) {
      // Previous ping was not answered — consider the connection stale.
      logger.warn({ clientId }, 'Client heartbeat timeout');
      clientWs.terminate();
      return;
    }

    if (clientWs.readyState === WebSocket.OPEN) {
      clientWs.ping();
      conn.heartbeatPending = true;
    }
  }, appConfig.wsHeartbeatMs);

  clientWs.on('pong', () => {
    conn.heartbeatPending = false;
  });
}

/** Open (or reopen) the upstream WebSocket to the Python backend. */
function connectUpstream(clientId: string, conn: RelayConnection, token?: string): void {
  const upstreamUrl = token
    ? `${appConfig.pythonWsUrl}/v1/ws?token=${encodeURIComponent(token)}`
    : `${appConfig.pythonWsUrl}/v1/ws`;

  const upstream = new WebSocket(upstreamUrl);

  upstream.on('open', () => {
    logger.info({ clientId }, 'Upstream connection established');
    conn.upstream = upstream;
    conn.reconnectAttempts = 0;
  });

  upstream.on('message', (data, isBinary) => {
    conn.metrics.lastActivityAt = Date.now();

    if (conn.client.readyState === WebSocket.OPEN) {
      const payload = isBinary ? data as Buffer : data.toString();
      conn.client.send(payload);
      conn.metrics.framesRelayed++;
      conn.metrics.bytesRelayed += typeof payload === 'string' ? Buffer.byteLength(payload) : (payload as Buffer).length;
    }
  });

  upstream.on('close', (code, reason) => {
    logger.warn({ clientId, code, reason: reason.toString() }, 'Upstream closed');
    conn.upstream = null;

    if (!conn.intentionallyClosed && conn.client.readyState === WebSocket.OPEN) {
      scheduleUpstreamReconnect(clientId, conn, token);
    }
  });

  upstream.on('error', (err) => {
    logger.error({ clientId, error: err.message }, 'Upstream WebSocket error');
  });

  conn.upstream = upstream;
}

/** Schedule an upstream reconnect with exponential back-off. */
function scheduleUpstreamReconnect(
  clientId: string,
  conn: RelayConnection,
  token?: string,
): void {
  const MAX_ATTEMPTS = 10;
  if (conn.reconnectAttempts >= MAX_ATTEMPTS) {
    logger.error({ clientId }, 'Max upstream reconnect attempts reached — closing client');
    conn.client.close(1011, 'Upstream unreachable');
    teardown(clientId, conn, 1011, 'Upstream unreachable');
    return;
  }

  const delay = Math.min(1000 * Math.pow(2, conn.reconnectAttempts), 30_000);
  conn.reconnectAttempts++;

  logger.info({ clientId, attempt: conn.reconnectAttempts, delayMs: delay }, 'Scheduling upstream reconnect');

  conn.reconnectTimer = setTimeout(() => {
    conn.reconnectTimer = null;
    if (conn.client.readyState === WebSocket.OPEN) {
      connectUpstream(clientId, conn, token);
    }
  }, delay);
}

/** Clean up all resources for a connection. */
function teardown(clientId: string, conn: RelayConnection, code: number, reason: string): void {
  conn.intentionallyClosed = true;

  if (conn.heartbeatTimer) {
    clearInterval(conn.heartbeatTimer);
    conn.heartbeatTimer = null;
  }

  if (conn.reconnectTimer) {
    clearTimeout(conn.reconnectTimer);
    conn.reconnectTimer = null;
  }

  if (conn.upstream && conn.upstream.readyState <= WebSocket.OPEN) {
    conn.upstream.close(code, reason);
  }

  if (conn.client.readyState <= WebSocket.OPEN) {
    conn.client.close(code, reason);
  }

  connections.delete(clientId);
  logger.info({ clientId, framesRelayed: conn.metrics.framesRelayed }, 'Connection teardown complete');
}
