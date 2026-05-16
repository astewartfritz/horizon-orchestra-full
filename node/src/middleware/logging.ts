/**
 * @module middleware/logging
 * @description Request logging middleware powered by pino.
 * Assigns a unique request ID to every inbound request and logs
 * method, URL, status, and latency on response completion.
 */

import type { Request, Response, NextFunction } from 'express';
import pino from 'pino';
import { randomUUID } from 'node:crypto';
import { appConfig } from '../config.js';

// ──────────────────────────────────────────────
// Logger instance
// ──────────────────────────────────────────────

/** Shared pino logger instance used across the application. */
export const logger = pino({
  level: appConfig.logLevel,
  transport:
    appConfig.nodeEnv === 'development'
      ? { target: 'pino/file', options: { destination: 1 } }
      : undefined,
  formatters: {
    level(label) {
      return { level: label };
    },
  },
  timestamp: pino.stdTimeFunctions.isoTime,
  serializers: {
    req: pino.stdSerializers.req,
    res: pino.stdSerializers.res,
    err: pino.stdSerializers.err,
  },
});

// ──────────────────────────────────────────────
// Middleware
// ──────────────────────────────────────────────

/**
 * Express middleware that:
 * 1. Generates and attaches an `X-Request-ID` header.
 * 2. Records the start time for latency measurement.
 * 3. Logs the request on response finish with status and duration.
 */
export function requestLogger(req: Request, res: Response, next: NextFunction): void {
  const start = process.hrtime.bigint();

  // Use client-supplied request ID if present, otherwise generate one.
  const requestId =
    (req.headers['x-request-id'] as string | undefined) ?? randomUUID();

  req.requestId = requestId;
  res.setHeader('X-Request-ID', requestId);

  // Log on response finish so we capture the status code and timing.
  res.on('finish', () => {
    const durationNs = process.hrtime.bigint() - start;
    const durationMs = Number(durationNs / 1_000_000n);

    const logData = {
      requestId,
      method: req.method,
      url: req.originalUrl,
      status: res.statusCode,
      durationMs,
      contentLength: res.getHeader('content-length'),
      userAgent: req.headers['user-agent'],
      ip: req.ip,
    };

    if (res.statusCode >= 500) {
      logger.error(logData, 'request completed with server error');
    } else if (res.statusCode >= 400) {
      logger.warn(logData, 'request completed with client error');
    } else {
      logger.info(logData, 'request completed');
    }
  });

  next();
}
