import { randomUUID } from "node:crypto";
import { matchRoute } from "./allowlist";
import { publicStatus, readConfig, type ServerConfig } from "./config";
import { mockRoute } from "./mock/handlers";
import type { ChatRequest } from "@/lib/api";

export const VISITOR_COOKIE = "oah_visitor";
const MAX_BODY_BYTES = 16 * 1024;
const UPSTREAM_TIMEOUT_MS = 70_000;
const TOKEN = /^[A-Za-z0-9_-]{16,64}$/;
const INDEXES = ["water-quality", "water-parameters", "data-quality", "microbiology"] as const;

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

function json(status: number, body: unknown, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...JSON_HEADERS, ...extra } });
}

/** Parse a Retry-After value (seconds only); clamp to a sane range, otherwise ignore it. */
export function sanitiseRetryAfter(value: string | null | undefined): string | null {
  if (!value || !/^\d{1,5}$/.test(value.trim())) return null;
  const seconds = Number(value);
  return seconds >= 1 && seconds <= 86_400 ? String(seconds) : null;
}

/** Validate and rebuild the chat body: unknown keys are dropped, limits mirror docs/openapi.json. */
export function parseChatBody(raw: unknown): ChatRequest | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  const text = (v: unknown) => (typeof v === "string" && v.trim().length >= 1 && v.length <= 500 ? v : null);
  const message = text(o.message);
  if (!message) return null;
  const out: ChatRequest = { message };
  if (o.country != null) {
    if (typeof o.country !== "string" || !/^[A-Za-z]{2}$/.test(o.country)) return null;
    out.country = o.country;
  }
  if (o.language != null) {
    if (typeof o.language !== "string" || o.language.length < 2 || o.language.length > 12) return null;
    out.language = o.language;
  }
  if (o.index != null) {
    if (typeof o.index !== "string" || !(INDEXES as readonly string[]).includes(o.index)) return null;
    out.index = o.index as ChatRequest["index"];
  }
  if (o.history != null) {
    if (!Array.isArray(o.history) || o.history.length > 6) return null;
    const history: NonNullable<ChatRequest["history"]> = [];
    for (const turn of o.history) {
      if (typeof turn !== "object" || turn === null) return null;
      const t = turn as Record<string, unknown>;
      const body = text(t.text);
      if ((t.role !== "user" && t.role !== "assistant") || !body) return null;
      history.push({ role: t.role, text: body });
    }
    out.history = history;
  }
  return out;
}

function readCookie(header: string | null, name: string): string | null {
  for (const part of (header ?? "").split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return rest.join("=");
  }
  return null;
}

/** Cross-site POSTs are refused: when the browser sends an Origin it must be this host. */
function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/** Reduce any upstream failure to the documented `{detail}` shape; never pass raw upstream text through. */
async function upstreamError(res: Response): Promise<Response> {
  let detail = "The service could not complete the request.";
  try {
    const parsed: unknown = JSON.parse(await res.text());
    if (typeof parsed === "object" && parsed !== null && typeof (parsed as { detail?: unknown }).detail === "string") {
      detail = (parsed as { detail: string }).detail.slice(0, 300);
    }
  } catch {
    // keep the generic message
  }
  const extra: Record<string, string> = {};
  const retry = sanitiseRetryAfter(res.headers.get("retry-after"));
  if (retry) extra["retry-after"] = retry;
  // 401 means the server-side key is wrong: that is the operator's problem, never the visitor's.
  if (res.status === 401) return json(502, { detail: "The data service rejected this app's access. Please try again later." }, extra);
  const status = [404, 422, 429, 502, 503].includes(res.status) ? res.status : 502;
  return json(status, { detail }, extra);
}

export async function handleProxy(
  request: Request,
  segments: string[],
  config: ServerConfig = readConfig(),
): Promise<Response> {
  const url = new URL(request.url);
  const method = request.method.toUpperCase();
  const match = matchRoute(method, segments, url.searchParams);
  if (!match) return json(404, { detail: "Not Found" });

  let chatBody: ChatRequest | null = null;
  let newVisitor: string | null = null;
  let visitor = readCookie(request.headers.get("cookie"), VISITOR_COOKIE);
  if (method === "POST") {
    if (!sameOrigin(request)) return json(403, { detail: "Cross-site requests are not accepted." });
    const text = await request.text();
    if (text.length > MAX_BODY_BYTES) return json(422, { detail: "Request body too large." });
    let raw: unknown;
    try {
      raw = JSON.parse(text);
    } catch {
      return json(422, { detail: "Invalid JSON." });
    }
    chatBody = parseChatBody(raw);
    if (!chatBody) return json(422, { detail: "Invalid chat request." });
    if (!visitor || !TOKEN.test(visitor)) {
      visitor = randomUUID();
      newVisitor = visitor;
    }
  }

  const modeHeader = { "x-oah-data-mode": config.mode };
  let response: Response;

  if (config.mode === "mock") {
    const result = mockRoute(method, match.path, new URLSearchParams(match.search.slice(1)), chatBody);
    response = json(result.status, result.body, { ...modeHeader, ...(result.headers ?? {}) });
  } else {
    if (!config.backendUrl || !config.apiKey) {
      return json(503, { detail: "The data service is not configured." }, modeHeader);
    }
    const headers: Record<string, string> = { accept: "application/json", "x-api-key": config.apiKey };
    if (chatBody) {
      headers["content-type"] = "application/json";
      if (visitor && TOKEN.test(visitor)) headers["x-oah-end-user"] = visitor;
    }
    try {
      const upstream = await fetch(config.backendUrl + match.path + match.search, {
        method,
        headers,
        body: chatBody ? JSON.stringify(chatBody) : undefined,
        redirect: "error",
        cache: "no-store",
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      });
      response = upstream.ok
        ? new Response(await upstream.text(), { status: 200, headers: { ...JSON_HEADERS, ...modeHeader } })
        : await upstreamError(upstream);
      if (!upstream.ok) response.headers.set("x-oah-data-mode", config.mode);
    } catch {
      response = json(502, { detail: "The data service could not be reached." }, modeHeader);
    }
  }

  if (newVisitor) {
    const secure = url.protocol === "https:" ? "; Secure" : "";
    response.headers.append("set-cookie", `${VISITOR_COOKIE}=${newVisitor}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000${secure}`);
  }
  return response;
}

export function statusResponse(config: ServerConfig = readConfig()): Response {
  return json(200, publicStatus(config));
}
