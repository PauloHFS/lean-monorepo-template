/**
 * Wrapper de fetch mínimo:
 * - sempre envia `credentials: "include"` (cookie HttpOnly de sessão)
 * - lança ApiError com status + body em caso de não-OK
 * - parseia JSON quando há body
 */

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const init: RequestInit = {
    method: opts.method ?? "GET",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    signal: opts.signal,
  };
  if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
  }

  const res = await fetch(path, init);
  const text = await res.text();
  const parsed: unknown = text ? safeJson(text) : undefined;

  if (!res.ok) {
    const detail = detailOf(parsed) ?? `HTTP ${res.status}`;
    throw new ApiError(res.status, detail, parsed);
  }

  return parsed as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function detailOf(body: unknown): string | null {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return null;
}

export const api = {
  get: <T>(p: string, signal?: AbortSignal) => request<T>(p, { signal }),
  post: <T>(p: string, body?: unknown) => request<T>(p, { method: "POST", body }),
  put: <T>(p: string, body?: unknown) => request<T>(p, { method: "PUT", body }),
  patch: <T>(p: string, body?: unknown) => request<T>(p, { method: "PATCH", body }),
  delete: <T>(p: string) => request<T>(p, { method: "DELETE" }),
};