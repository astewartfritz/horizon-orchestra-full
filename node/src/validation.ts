/**
 * @module validation
 * @description Zod request-validation schemas and Express middleware.
 * Each schema mirrors the corresponding Python Pydantic model.
 *
 * The {@link validate} middleware factory plugs into route definitions so
 * that invalid payloads are rejected with a 422 before reaching the proxy.
 */

import { z } from 'zod';
import type { Request, Response, NextFunction } from 'express';

// ──────────────────────────────────────────────
// Auth schemas
// ──────────────────────────────────────────────

/** POST /v1/auth/register */
export const RegisterSchema = z.object({
  email: z.string().email('Must be a valid email address'),
  name: z.string().min(1, 'Name is required').max(200, 'Name must be at most 200 characters'),
  password: z.string().min(8, 'Password must be at least 8 characters').max(128),
});

/** POST /v1/auth/login */
export const LoginSchema = z.object({
  email: z.string().email('Must be a valid email address'),
  password: z.string().min(1, 'Password is required'),
});

/** POST /v1/auth/refresh */
export const RefreshSchema = z.object({
  refresh_token: z.string().min(1, 'Refresh token is required'),
});

// ──────────────────────────────────────────────
// Task execution schemas
// ──────────────────────────────────────────────

/** POST /v1/run */
export const RunSchema = z.object({
  task: z.string().min(1, 'Task description is required').max(50_000),
  agent_type: z.enum(['monolithic', 'rag', 'swarm', 'mcp', 'production']).optional(),
  context: z.record(z.unknown()).optional(),
  model: z.string().optional(),
  stream: z.boolean().optional(),
  architecture: z.enum(['A', 'B', 'C', 'D', 'E']).optional(),
});

/** POST /v1/query */
export const QuerySchema = z.object({
  prompt: z.string().min(1, 'Prompt is required').max(100_000),
  model: z.string().optional(),
  system: z.string().optional(),
  temperature: z.number().min(0).max(2).optional(),
  max_tokens: z.number().int().min(1).max(200_000).optional(),
});

// ──────────────────────────────────────────────
// Billing schemas
// ──────────────────────────────────────────────

/** POST /v1/billing/checkout */
export const CheckoutSchema = z.object({
  tier: z.string().min(1, 'Tier is required'),
  success_url: z.string().url('Must be a valid URL'),
  cancel_url: z.string().url('Must be a valid URL'),
});

/** POST /v1/billing/portal */
export const PortalSchema = z.object({
  return_url: z.string().url('Must be a valid URL'),
});

// ──────────────────────────────────────────────
// Memory schemas
// ──────────────────────────────────────────────

/** POST /v1/memory/search */
export const MemorySearchSchema = z.object({
  query: z.string().min(1, 'Search query is required').max(10_000),
  limit: z.number().int().min(1).max(100).optional(),
  filters: z.record(z.unknown()).optional(),
});

/** POST /v1/memory/store */
export const MemoryStoreSchema = z.object({
  content: z.string().min(1, 'Content is required').max(100_000),
  metadata: z.record(z.unknown()).optional(),
  tags: z.array(z.string()).optional(),
});

// ──────────────────────────────────────────────
// Push notification schemas
// ──────────────────────────────────────────────

/** POST /v1/push/register */
export const PushRegisterSchema = z.object({
  device_token: z.string().min(1, 'Device token is required'),
  platform: z.enum(['apns', 'fcm']),
  device_id: z.string().min(1, 'Device ID is required'),
});

/** POST /v1/push/send */
export const PushSendSchema = z.object({
  user_id: z.string().min(1, 'User ID is required'),
  title: z.string().min(1, 'Title is required').max(200),
  body: z.string().min(1, 'Body is required').max(4096),
  data: z.record(z.unknown()).optional(),
});

// ──────────────────────────────────────────────
// Frontier browser schemas
// ──────────────────────────────────────────────

/** POST /v1/frontier/submit */
export const FrontierSubmitSchema = z.object({
  description: z.string().min(1, 'Task description is required').max(10_000),
  start_url: z.string().url('Must be a valid URL').optional(),
  max_steps: z.number().int().min(1).max(1000).optional(),
  timeout_seconds: z.number().int().min(1).max(600).optional(),
});

// ──────────────────────────────────────────────
// Architecture billing schemas
// ──────────────────────────────────────────────

/** POST /v1/architecture/:arch/estimate */
export const CostEstimateSchema = z.record(
  z.number(),
  { message: 'Body must be a record of numeric parameters' },
);

// ──────────────────────────────────────────────
// Connector schema
// ──────────────────────────────────────────────

/** POST /v1/connectors/:name/connect */
export const ConnectorConfigSchema = z.record(z.unknown()).optional();

// ──────────────────────────────────────────────
// Route → Schema mapping
// ──────────────────────────────────────────────

/** Map of route patterns to their corresponding Zod schema. */
const ROUTE_SCHEMAS: Record<string, z.ZodTypeAny> = {
  'POST /v1/auth/register': RegisterSchema,
  'POST /v1/auth/login': LoginSchema,
  'POST /v1/auth/refresh': RefreshSchema,
  'POST /v1/run': RunSchema,
  'POST /v1/run/sse': RunSchema,
  'POST /v1/query': QuerySchema,
  'POST /v1/billing/checkout': CheckoutSchema,
  'POST /v1/billing/portal': PortalSchema,
  'POST /v1/memory/search': MemorySearchSchema,
  'POST /v1/memory/store': MemoryStoreSchema,
  'POST /v1/push/register': PushRegisterSchema,
  'POST /v1/push/send': PushSendSchema,
  'POST /v1/frontier/submit': FrontierSubmitSchema,
};

// ──────────────────────────────────────────────
// Middleware
// ──────────────────────────────────────────────

/**
 * Create an Express middleware that validates `req.body` against the
 * given Zod schema, passing a `ZodError` to `next()` on failure.
 *
 * @param schema - The Zod schema to validate against.
 */
export function validate(schema: z.ZodTypeAny) {
  return (req: Request, _res: Response, next: NextFunction): void => {
    const result = schema.safeParse(req.body);
    if (!result.success) {
      next(result.error);
      return;
    }
    // Replace body with parsed (and coerced) data.
    req.body = result.data;
    next();
  };
}

/**
 * Auto-validation middleware that looks up the schema from {@link ROUTE_SCHEMAS}
 * based on `req.method` and `req.path`. If no schema is registered the
 * request passes through unvalidated (read-only routes).
 */
export function autoValidate(req: Request, _res: Response, next: NextFunction): void {
  const key = `${req.method} ${req.path}`;
  const schema = ROUTE_SCHEMAS[key];

  if (!schema) {
    next();
    return;
  }

  const result = schema.safeParse(req.body);
  if (!result.success) {
    next(result.error);
    return;
  }

  req.body = result.data;
  next();
}
