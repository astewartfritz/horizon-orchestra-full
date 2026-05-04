/**
 * @module errors
 * @description Error hierarchy for the Horizon Orchestra SDK.
 * Every error carries the HTTP status, a machine-readable code, and the
 * originating request ID for traceability.
 */

/**
 * Base error class for all Horizon Orchestra API errors.
 * Carries structured metadata beyond a plain Error message.
 */
export class HorizonError extends Error {
  /** HTTP status code returned by the API. */
  public readonly status: number;

  /** Machine-readable error code (e.g. "INSUFFICIENT_CREDITS"). */
  public readonly code: string;

  /** Unique request identifier for support and log correlation. */
  public readonly requestId: string;

  constructor(
    message: string,
    status: number,
    code: string,
    requestId: string,
  ) {
    super(message);
    this.name = 'HorizonError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;

    // Maintain correct prototype chain for instanceof checks.
    Object.setPrototypeOf(this, new.target.prototype);
  }

  /** Serialise the error to a plain object for logging / transport. */
  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      message: this.message,
      status: this.status,
      code: this.code,
      requestId: this.requestId,
    };
  }
}

/**
 * Raised when authentication fails (401) or authorisation is denied (403).
 */
export class AuthError extends HorizonError {
  constructor(message: string, status: number, code: string, requestId: string) {
    super(message, status, code, requestId);
    this.name = 'AuthError';
  }
}

/**
 * Raised for billing-related errors such as expired subscriptions or
 * insufficient credits (402 / 403 with billing code).
 */
export class BillingError extends HorizonError {
  constructor(message: string, status: number, code: string, requestId: string) {
    super(message, status, code, requestId);
    this.name = 'BillingError';
  }
}

/**
 * Raised when the client exceeds rate limits (429).
 * Includes the number of seconds the caller should wait before retrying.
 */
export class RateLimitError extends HorizonError {
  /** Seconds until the rate-limit window resets. */
  public readonly retryAfter: number;

  constructor(
    message: string,
    status: number,
    code: string,
    requestId: string,
    retryAfter: number,
  ) {
    super(message, status, code, requestId);
    this.name = 'RateLimitError';
    this.retryAfter = retryAfter;
  }

  override toJSON(): Record<string, unknown> {
    return {
      ...super.toJSON(),
      retryAfter: this.retryAfter,
    };
  }
}

/**
 * Raised when the server rejects a request due to invalid input (422).
 * Includes a per-field error map for rendering inline validation messages.
 */
export class ValidationError extends HorizonError {
  /** Map of field names to human-readable validation messages. */
  public readonly fields: Record<string, string>;

  constructor(
    message: string,
    status: number,
    code: string,
    requestId: string,
    fields: Record<string, string>,
  ) {
    super(message, status, code, requestId);
    this.name = 'ValidationError';
    this.fields = fields;
  }

  override toJSON(): Record<string, unknown> {
    return {
      ...super.toJSON(),
      fields: this.fields,
    };
  }
}

/**
 * Raised when a request times out before the server responds.
 */
export class TimeoutError extends HorizonError {
  constructor(message: string, requestId: string) {
    super(message, 408, 'REQUEST_TIMEOUT', requestId);
    this.name = 'TimeoutError';
  }
}

/**
 * Raised when the server returns a 5xx status code.
 */
export class ServerError extends HorizonError {
  constructor(message: string, status: number, code: string, requestId: string) {
    super(message, status, code, requestId);
    this.name = 'ServerError';
  }
}

/**
 * Raised when the network is unreachable or the request fails before
 * receiving any HTTP response.
 */
export class NetworkError extends HorizonError {
  constructor(message: string, requestId: string) {
    super(message, 0, 'NETWORK_ERROR', requestId);
    this.name = 'NetworkError';
  }
}

/**
 * Factory that inspects an HTTP status code and body to produce the
 * appropriate error subclass.
 */
export function createErrorFromResponse(
  status: number,
  body: {
    error?: string;
    code?: string;
    fields?: Record<string, string>;
    meta?: { request_id?: string };
  },
  retryAfterHeader?: string | null,
): HorizonError {
  const message = body.error ?? `HTTP ${status}`;
  const code = body.code ?? `HTTP_${status}`;
  const requestId = body.meta?.request_id ?? 'unknown';

  if (status === 401 || status === 403) {
    return new AuthError(message, status, code, requestId);
  }
  if (status === 402) {
    return new BillingError(message, status, code, requestId);
  }
  if (status === 422) {
    return new ValidationError(message, status, code, requestId, body.fields ?? {});
  }
  if (status === 429) {
    const retryAfter = retryAfterHeader ? parseInt(retryAfterHeader, 10) : 60;
    return new RateLimitError(message, status, code, requestId, retryAfter);
  }
  if (status >= 500) {
    return new ServerError(message, status, code, requestId);
  }

  return new HorizonError(message, status, code, requestId);
}
