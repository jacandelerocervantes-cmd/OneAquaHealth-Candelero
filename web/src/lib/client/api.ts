import type { ChatRequest, ChatResponse } from "@/lib/api";
import { translateEnglish, type TFunction } from "@/lib/i18n-core";

export class ApiError extends Error {
  readonly status: number;
  readonly retryAfter: number | null;
  constructor(status: number, detail: string, retryAfter: number | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

/** Human wording for an error; always plain text. Pass `t` (from `useT`) to get it in the selected language. */
export function describeError(error: unknown, t: TFunction = translateEnglish): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return error.retryAfter
        ? t("Too many requests. You can try again in {n} s.", { n: error.retryAfter })
        : t("Too many requests. Please try again later.");
    }
    if (error.status === 503) return t("The service is busy or not configured. Please try again later.");
    if (error.status === 502) return t("The data service is unavailable. Please try again later.");
    if (error.status === 404) return t("Nothing was found for this request.");
    if (error.status === 422) return t("The request was not accepted. Check the values and try again.");
    return t("The request failed. Please try again.");
  }
  return t("The network request failed. Check your connection and try again.");
}

function parseRetryAfter(value: string | null): number | null {
  if (!value || !/^\d{1,5}$/.test(value.trim())) return null;
  const n = Number(value);
  return n >= 1 ? n : null;
}

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api/oah${path}`, { ...init, signal, cache: "no-store" });
  if (!res.ok) {
    let detail = "Request failed";
    try {
      const body: unknown = await res.json();
      if (typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string") {
        detail = (body as { detail: string }).detail;
      }
    } catch {
      // keep the default
    }
    throw new ApiError(res.status, detail, parseRetryAfter(res.headers.get("retry-after")));
  }
  return (await res.json()) as T;
}

export type Query = Record<string, string | number | null | undefined>;

export function buildPath(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== null && v !== undefined && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export function apiGet<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  return request<T>(buildPath(path, query), undefined, signal);
}

export function apiChat(body: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  return request<ChatResponse>(
    "/chat",
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) },
    signal,
  );
}

/** The epoch-millisecond deadline `seconds` from now (kept out of components: it reads the clock). */
export function deadlineFrom(seconds: number): number {
  return Date.now() + seconds * 1000;
}
