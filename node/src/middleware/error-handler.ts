/**
 * @module middleware/error-handler
 * @description Global Express error-handling middleware.
 * Catches all unhandled errors, normalises them into the standard API
 * envelope, and logs them via pino.
 */

import type { Request, Response, NextFunction } from 'express';
import { ZodError } from 'zod';
import { logger } from './logging.js';

/** Shape of the standard error response body. */
interface ErrorResponseBody {
  data: null;
  error: string;
  code: string;
  fields?: Record<string, string>;
  meta: {
    request_id: string;
    duration_ms: number;
  };
}

/**
 * Map Zod validation issues into a flat field → message record.
 */
function formatZodErrors(error: ZodError): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const issue of error.issues) {
    const path = issue.path.join('.');
    fields[path] = issue.message;
  }
  return fields;
}

/**
 * Express error-handling middleware (four-argument signature).
 * Must be registered after all route handlers.
 */
export function globalErrorHandler(
  err: unknown,
  req: Request,
  res: Response,
  _next: NextFunction,
): void {
  const requestId = req.requestId ?? 'unknown';

  // ── Zod validation errors → 422 ──────────────────────────────
  if (err instanceof ZodError) {
    const body: ErrorResponseBody = {
      data: null,
      error: 'Validation failed',
      code: 'VALIDATION_ERROR',
      fields: formatZodErrors(err),
      meta: { request_id: requestId, duration_ms: 0 },
    };
    logger.warn({ requestId, fields: body.fields }, 'Validation error');
    res.status(422).json(body);
    return;
  }

  // ── Known HTTP-like errors ───────────────────────────────────
  if (err instanceof Error && 'status' in err) {
    const status = (err as Error & { status: number }).status;
    const code = 'code' in err ? String((err as Error & { code: string }).code) : `HTTP_${status}`;
    const body: ErrorResponseBody = {
      data: null,
      error: err.message,
      code,
      meta: { request_id: requestId, duration_ms: 0 },
    };
    logger.warn({ requestId, status, code }, err.message);
    res.status(status).json(body);
    return;
  }

  // ── Unexpected errors → 500 ──────────────────────────────────
  const message = err instanceof Error ? err.message : 'Internal server error';
  const stack = err instanceof Error ? err.stack : undefined;

  logger.error({ requestId, err: { message, stack } }, 'Unhandled error');

  const body: ErrorResponseBody = {
    data: null,
    error: process.env['NODE_ENV'] === 'production'
      ? 'Internal server error'
      : message,
    code: 'INTERNAL_ERROR',
    meta: { request_id: requestId, duration_ms: 0 },
  };

  res.status(500).json(body);
}

/**
 * Catch-all 404 handler for unmatched routes.
 * Should be registered after all route definitions but before the error handler.
 */
export function notFoundHandler(req: Request, res: Response): void {
  res.status(404).json({
    data: null,
    error: `Route ${req.method} ${req.path} not found`,
    code: 'NOT_FOUND',
    meta: { request_id: req.requestId ?? 'unknown', duration_ms: 0 },
  });
}
