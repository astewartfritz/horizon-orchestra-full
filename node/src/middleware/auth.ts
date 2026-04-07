/**
 * @module middleware/auth
 * @description JWT verification middleware for the Node.js bridge.
 * Validates the Authorization header, decodes the JWT payload, and
 * attaches the user context to `req.user` for downstream handlers.
 *
 * Uses a simple HMAC-SHA256 verification suitable for symmetric JWTs.
 * In production, replace with asymmetric RS256 / public-key verification.
 */

import type { Request, Response, NextFunction } from 'express';
import { createHmac, timingSafeEqual } from 'node:crypto';
import { appConfig } from '../config.js';
import { logger } from './logging.js';

// ──────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────

/** Decoded JWT payload attached to `req.user`. */
export interface JwtPayload {
  sub: string;
  email: string;
  name: string;
  tier: string;
  iat: number;
  exp: number;
}

/** Extend the Express Request interface to carry user context. */
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      user?: JwtPayload;
      requestId?: string;
    }
  }
}

// ──────────────────────────────────────────────
// JWT helpers
// ──────────────────────────────────────────────

/** Base64url-decode a string. */
function base64urlDecode(input: string): string {
  const padded = input.replace(/-/g, '+').replace(/_/g, '/');
  return Buffer.from(padded, 'base64').toString('utf-8');
}

/** Base64url-encode a buffer. */
function base64urlEncode(input: Buffer): string {
  return input.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * Verify a HS256 JWT and return the decoded payload.
 * Throws if the token is malformed, expired, or the signature is invalid.
 */
function verifyJwt(token: string, secret: string): JwtPayload {
  const parts = token.split('.');
  if (parts.length !== 3) {
    throw new Error('Malformed JWT: expected 3 parts');
  }

  const [headerB64, payloadB64, signatureB64] = parts as [string, string, string];

  // Verify signature.
  const data = `${headerB64}.${payloadB64}`;
  const expectedSig = base64urlEncode(
    createHmac('sha256', secret).update(data).digest(),
  );

  const sigBuffer = Buffer.from(signatureB64, 'utf-8');
  const expectedBuffer = Buffer.from(expectedSig, 'utf-8');

  if (sigBuffer.length !== expectedBuffer.length || !timingSafeEqual(sigBuffer, expectedBuffer)) {
    throw new Error('Invalid JWT signature');
  }

  // Decode payload.
  const payload = JSON.parse(base64urlDecode(payloadB64)) as JwtPayload;

  // Check expiry.
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (payload.exp && payload.exp < nowSeconds) {
    throw new Error('JWT has expired');
  }

  return payload;
}

// ──────────────────────────────────────────────
// Middleware
// ──────────────────────────────────────────────

/** Routes that can be accessed without a valid token. */
const PUBLIC_PATHS = new Set<string>([
  '/health',
  '/ready',
  '/v1/auth/register',
  '/v1/auth/login',
  '/v1/auth/refresh',
]);

/**
 * Express middleware that verifies the `Authorization: Bearer <token>` header.
 * Requests to {@link PUBLIC_PATHS} pass through unauthenticated.
 */
export function authMiddleware(req: Request, res: Response, next: NextFunction): void {
  // Allow public endpoints.
  if (PUBLIC_PATHS.has(req.path)) {
    next();
    return;
  }

  const authHeader = req.headers['authorization'];
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    res.status(401).json({
      data: null,
      error: 'Missing or malformed Authorization header',
      meta: { request_id: req.requestId ?? 'unknown', duration_ms: 0 },
    });
    return;
  }

  const token = authHeader.slice(7);

  try {
    const payload = verifyJwt(token, appConfig.jwtSecret);
    req.user = payload;
    next();
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Authentication failed';
    logger.warn({ path: req.path, error: message }, 'JWT verification failed');
    res.status(401).json({
      data: null,
      error: message,
      meta: { request_id: req.requestId ?? 'unknown', duration_ms: 0 },
    });
  }
}
