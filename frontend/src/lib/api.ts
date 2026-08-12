// Server-side API client (BFF layer). This module must only ever run on the server:
// it reads CAREPLAN_API_KEY and attaches it as X-API-Key so the secret never reaches
// the browser. Client components talk to Next.js route handlers, which call these.
import "server-only";

import type { ApiEnvelope } from "./types";

const BASE = process.env.CAREPLAN_API_URL ?? "http://localhost:8000";
const KEY = process.env.CAREPLAN_API_KEY ?? "";

/** A structured error carrying the backend's {type, code, message, detail} envelope. */
export class ApiError extends Error {
  status: number;
  type: ApiEnvelope["type"] | "unknown";
  code?: string;
  detail?: Record<string, unknown>;
  constructor(status: number, env: Partial<ApiEnvelope> & { message: string }) {
    super(env.message);
    this.name = "ApiError";
    this.status = status;
    this.type = (env.type as ApiEnvelope["type"]) ?? "unknown";
    this.code = env.code;
    this.detail = env.detail;
  }
}

export interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  // FastAPI's WarningException returns HTTP 200 with {type:"warning"}. By default we
  // surface it as an ApiError so callers can branch on .type === "warning".
  json?: boolean;
}

/**
 * Fetch from the FastAPI backend with the API key attached.
 * Throws ApiError on non-2xx OR on a 200 `{type:"warning"}` envelope.
 */
export async function apiFetch<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const { body, json = true, headers, ...rest } = opts;
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(KEY ? { "X-API-Key": KEY } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    // Reads should not be cached by Next's data cache — statuses change.
    cache: "no-store",
  });

  const text = await res.text();
  const data: unknown = text ? safeJson(text) : undefined;

  // 200 warning envelope → treat as an ApiError of type "warning".
  if (res.ok) {
    if (isEnvelope(data) && data.type === "warning") {
      throw new ApiError(res.status, data);
    }
    return (json ? data : (text as unknown)) as T;
  }

  if (isEnvelope(data)) throw new ApiError(res.status, data);
  throw new ApiError(res.status, {
    message: `Backend error ${res.status}`,
    type: "error",
  });
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function isEnvelope(x: unknown): x is ApiEnvelope {
  return (
    typeof x === "object" &&
    x !== null &&
    "type" in x &&
    "message" in x &&
    typeof (x as Record<string, unknown>).message === "string"
  );
}
