/**
 * @module sse
 * @description Server-Sent Events (SSE) handler for the Node.js bridge.
 * Proxies a streaming response from the Python backend and re-emits it
 * as a standards-compliant SSE stream to the browser client.
 *
 * Features:
 * - Proper SSE framing (event, data, id, retry fields)
 * - Client disconnect detection via `req.on('close')`
 * - Back-pressure: pauses the upstream read when the client cannot keep up
 * - Automatic keep-alive comments to prevent proxy timeouts
 */

import type { Request, Response } from 'express';
import { Readable } from 'node:stream';
import { appConfig } from './config.js';
import { logger } from './middleware/logging.js';

// ──────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────

/** A single SSE frame to be written to the client. */
interface SSEFrame {
  /** Event name (defaults to "message" per SSE spec). */
  event?: string;
  /** JSON-serialisable data payload. */
  data: string;
  /** Optional event ID for resumption via Last-Event-ID. */
  id?: string;
  /** Suggested reconnect delay in milliseconds. */
  retry?: number;
}

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

/** Format an SSEFrame into the wire format expected by EventSource clients. */
function formatSSE(frame: SSEFrame): string {
  let output = '';
  if (frame.event) output += `event: ${frame.event}\n`;
  if (frame.id) output += `id: ${frame.id}\n`;
  if (frame.retry !== undefined) output += `retry: ${frame.retry}\n`;

  // Each line of data must be prefixed with "data: "
  for (const line of frame.data.split('\n')) {
    output += `data: ${line}\n`;
  }

  output += '\n'; // Blank line terminates the frame.
  return output;
}

/** Write a formatted SSE frame to the response, respecting back-pressure. */
function writeSSE(res: Response, frame: SSEFrame): boolean {
  const formatted = formatSSE(frame);
  return res.write(formatted);
}

// ──────────────────────────────────────────────
// SSE Handler
// ──────────────────────────────────────────────

/** Keep-alive interval to prevent intermediate proxies from closing idle connections. */
const KEEP_ALIVE_MS = 15_000;

/**
 * Express handler that opens an SSE connection to the client and relays
 * streaming events from the Python backend.
 *
 * The Python backend is expected to return a newline-delimited JSON stream
 * or native SSE when `Accept: text/event-stream` is set.
 */
export async function sseHandler(req: Request, res: Response): Promise<void> {
  const requestId = req.requestId ?? 'unknown';

  // ── Set SSE headers ──────────────────────────────────────────
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no', // Disable Nginx buffering.
    'X-Request-ID': requestId,
  });

  // Flush headers immediately.
  res.flushHeaders();

  // Send an initial retry directive so clients know when to reconnect.
  writeSSE(res, { data: '', retry: 3000 });

  // ── Track client disconnect ──────────────────────────────────
  let clientClosed = false;
  req.on('close', () => {
    clientClosed = true;
    logger.info({ requestId }, 'SSE client disconnected');
  });

  // ── Keep-alive timer ─────────────────────────────────────────
  const keepAlive = setInterval(() => {
    if (clientClosed) {
      clearInterval(keepAlive);
      return;
    }
    // SSE comment lines (prefixed with `:`) are ignored by EventSource.
    res.write(': keep-alive\n\n');
  }, KEEP_ALIVE_MS);

  // ── Proxy from upstream ──────────────────────────────────────
  const upstreamUrl = `${appConfig.pythonBackendUrl}${req.originalUrl}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), appConfig.requestTimeoutMs * 4); // streams get longer timeout

  try {
    const headers: Record<string, string> = {
      'Accept': 'text/event-stream',
      'X-Request-ID': requestId,
    };

    const authHeader = req.headers['authorization'];
    if (authHeader) {
      headers['Authorization'] = authHeader;
    }

    // Forward body for POST-based SSE endpoints.
    let body: string | undefined;
    if (req.method === 'POST' && req.body) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(req.body);
    }

    const upstream = await fetch(upstreamUrl, {
      method: req.method,
      headers,
      body,
      signal: controller.signal,
    });

    if (!upstream.ok) {
      const errorBody = await upstream.text().catch(() => 'Unknown error');
      writeSSE(res, { event: 'error', data: JSON.stringify({ status: upstream.status, error: errorBody }) });
      clearInterval(keepAlive);
      clearTimeout(timeout);
      res.end();
      return;
    }

    if (!upstream.body) {
      writeSSE(res, { event: 'error', data: JSON.stringify({ error: 'No upstream body' }) });
      clearInterval(keepAlive);
      clearTimeout(timeout);
      res.end();
      return;
    }

    // Convert the web ReadableStream into a Node.js Readable.
    const nodeStream = Readable.fromWeb(upstream.body as ReadableStream<Uint8Array>);
    const decoder = new TextDecoder();
    let buffer = '';
    let eventCounter = 0;

    nodeStream.on('data', (chunk: Buffer) => {
      if (clientClosed) {
        nodeStream.destroy();
        return;
      }

      buffer += decoder.decode(chunk, { stream: true });

      // Split on double-newline (SSE frame boundary) or single newline (NDJSON).
      const frames = buffer.split('\n');
      buffer = frames.pop() ?? '';

      for (const line of frames) {
        const trimmed = line.trim();
        if (trimmed.length === 0) continue;

        eventCounter++;

        // Attempt to determine event type from JSON payload.
        let eventName = 'message';
        try {
          const parsed = JSON.parse(trimmed) as Record<string, unknown>;
          if (typeof parsed['type'] === 'string') {
            eventName = parsed['type'];
          }
        } catch {
          // Non-JSON — relay as-is.
        }

        const canWrite = writeSSE(res, {
          event: eventName,
          data: trimmed,
          id: String(eventCounter),
        });

        // Back-pressure: pause reading until the client drains.
        if (!canWrite) {
          nodeStream.pause();
          res.once('drain', () => {
            if (!clientClosed) nodeStream.resume();
          });
        }
      }
    });

    nodeStream.on('end', () => {
      if (!clientClosed) {
        writeSSE(res, { event: 'done', data: JSON.stringify({ status: 'complete' }) });
      }
      clearInterval(keepAlive);
      clearTimeout(timeout);
      res.end();
    });

    nodeStream.on('error', (err) => {
      logger.error({ requestId, error: err.message }, 'Upstream stream error');
      if (!clientClosed) {
        writeSSE(res, { event: 'error', data: JSON.stringify({ error: err.message }) });
      }
      clearInterval(keepAlive);
      clearTimeout(timeout);
      res.end();
    });
  } catch (error: unknown) {
    clearInterval(keepAlive);
    clearTimeout(timeout);

    const message = error instanceof Error ? error.message : String(error);
    logger.error({ requestId, error: message }, 'SSE proxy error');

    if (!clientClosed) {
      writeSSE(res, { event: 'error', data: JSON.stringify({ error: message }) });
      res.end();
    }
  }
}
