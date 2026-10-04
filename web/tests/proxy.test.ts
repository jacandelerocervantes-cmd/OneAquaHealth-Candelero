import { afterEach, describe, expect, it, vi } from "vitest";
import type { ServerConfig } from "@/lib/server/config";
import { handleProxy, parseChatBody, sanitiseRetryAfter, VISITOR_COOKIE } from "@/lib/server/proxy";

const REAL: ServerConfig = { mode: "real", backendUrl: "https://backend.example", apiKey: "test-key-0123456789-test-key-0123456789" };
const MOCK: ServerConfig = { mode: "mock", backendUrl: null, apiKey: null };

const get = (path: string, config: ServerConfig, init?: RequestInit) =>
  handleProxy(new Request(`http://localhost/api/oah/${path}`, init), path.split("?")[0]!.split("/"), config);

const post = (body: unknown, config: ServerConfig, headers: Record<string, string> = {}) =>
  handleProxy(
    new Request("http://localhost/api/oah/chat", {
      method: "POST",
      headers: { "content-type": "application/json", host: "localhost", ...headers },
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
    ["chat"],
    config,
  );

afterEach(() => vi.unstubAllGlobals());

describe("mock mode", () => {
  it("serves allow-listed routes with the mode header and without a backend", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const res = await get("languages", MOCK);
    expect(res.status).toBe(200);
    expect(res.headers.get("x-oah-data-mode")).toBe("mock");
    expect(((await res.json()) as { languages: unknown[] }).languages).toHaveLength(26);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("answers 404 for routes outside the allow-list", async () => {
    expect((await get("fhir/export", MOCK)).status).toBe(404);
  });

  it("simulates 429 with Retry-After, 502 and the other chat states", async () => {
    const limited = await post({ message: "hello [mock:429]" }, MOCK);
    expect(limited.status).toBe(429);
    expect(limited.headers.get("retry-after")).toBe("20");
    expect((await post({ message: "hello [mock:error]" }, MOCK)).status).toBe(502);
    const withheld = (await (await post({ message: "[mock:withheld]" }, MOCK)).json()) as { status: string; evidence: unknown[] };
    expect(withheld.status).toBe("withheld");
    expect(withheld.evidence.length).toBeGreaterThan(0);
  });
});

describe("real mode", () => {
  it("adds the key server-side and forwards only the filtered query", async () => {
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const res = await get("catalog?country=GR&admin=1", REAL, { headers: { "x-api-key": "client-supplied" } });
    expect(res.status).toBe(200);
    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://backend.example/catalog?country=GR");
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe(REAL.apiKey);
    expect(init.redirect).toBe("error");
    // The key never travels back to the browser.
    expect(JSON.stringify([...res.headers.entries()])).not.toContain(REAL.apiKey as string);
    expect(await res.text()).not.toContain(REAL.apiKey as string);
  });

  it("is a 503 without a backend URL or key, and never calls out", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    expect((await get("countries", { mode: "real", backendUrl: null, apiKey: null })).status).toBe(503);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("passes 429 through with a sanitised Retry-After and the documented body", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "slow down", extra: "<b>x</b>" }), { status: 429, headers: { "retry-after": "60" } })));
    const res = await get("countries", REAL);
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("60");
    expect(await res.json()).toEqual({ detail: "slow down" });
  });

  it("drops a malformed Retry-After and hides a rejected key as a 502", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("not json", { status: 401, headers: { "retry-after": "soon" } })));
    const res = await get("countries", REAL);
    expect(res.status).toBe(502);
    expect(res.headers.get("retry-after")).toBeNull();
    expect(((await res.json()) as { detail: string }).detail).not.toMatch(/key/i);
  });

  it("turns a network failure into a 502", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("boom"))));
    expect((await get("countries", REAL)).status).toBe(502);
  });

  it("sends the chat body rebuilt from validated fields and the visitor token as X-OAH-End-User", async () => {
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify({ status: "answered" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const res = await post({ message: "hi", country: "GR", language: "es-MX", index: "microbiology", injected: "x" }, REAL);
    expect(res.status).toBe(200);
    const [, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ message: "hi", country: "GR", language: "es-MX", index: "microbiology" });
    const headers = init.headers as Record<string, string>;
    expect(headers["x-oah-end-user"]).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
    expect(res.headers.get("set-cookie")).toContain(`${VISITOR_COOKIE}=${headers["x-oah-end-user"]}`);
    expect(res.headers.get("set-cookie")).toContain("HttpOnly");
  });

  it("reuses a valid visitor cookie and ignores an invalid one", async () => {
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const token = "a".repeat(24);
    await post({ message: "hi" }, REAL, { cookie: `${VISITOR_COOKIE}=${token}` });
    expect(((fetchSpy.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Record<string, string>)["x-oah-end-user"]).toBe(token);
    await post({ message: "hi" }, REAL, { cookie: `${VISITOR_COOKIE}=short` });
    expect(((fetchSpy.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>)["x-oah-end-user"]).not.toBe("short");
  });
});

describe("POST /chat guards", () => {
  it("refuses cross-site posts", async () => {
    expect((await post({ message: "hi" }, MOCK, { origin: "https://evil.example" })).status).toBe(403);
    expect((await post({ message: "hi" }, MOCK, { origin: "http://localhost" })).status).toBe(200);
  });

  it("rejects invalid JSON and invalid bodies with 422", async () => {
    expect((await post("{nope", MOCK)).status).toBe(422);
    expect((await post({ message: "" }, MOCK)).status).toBe(422);
    expect((await post({ message: "x".repeat(501) }, MOCK)).status).toBe(422);
    expect((await post({ message: "x".repeat(20_000) }, MOCK)).status).toBe(422);
  });
});

describe("parseChatBody", () => {
  it("applies the limits of docs/openapi.json", () => {
    expect(parseChatBody({ message: "hi", country: "GRC" })).toBeNull();
    expect(parseChatBody({ message: "hi", language: "x" })).toBeNull();
    expect(parseChatBody({ message: "hi", index: "weather" })).toBeNull();
    expect(parseChatBody({ message: "hi", history: Array.from({ length: 7 }, () => ({ role: "user", text: "a" })) })).toBeNull();
    expect(parseChatBody({ message: "hi", history: [{ role: "system", text: "a" }] })).toBeNull();
    expect(parseChatBody({ message: "hi", history: [{ role: "user", text: "a" }, { role: "assistant", text: "b" }] })).toEqual({
      message: "hi",
      history: [{ role: "user", text: "a" }, { role: "assistant", text: "b" }],
    });
    expect(parseChatBody(null)).toBeNull();
    expect(parseChatBody([])).toBeNull();
  });
});

describe("sanitiseRetryAfter", () => {
  it("keeps whole seconds in range only", () => {
    expect(sanitiseRetryAfter("60")).toBe("60");
    expect(sanitiseRetryAfter("0")).toBeNull();
    expect(sanitiseRetryAfter("999999")).toBeNull();
    expect(sanitiseRetryAfter("1e3")).toBeNull();
    expect(sanitiseRetryAfter("Wed, 21 Oct 2026 07:28:00 GMT")).toBeNull();
    expect(sanitiseRetryAfter(null)).toBeNull();
  });
});
