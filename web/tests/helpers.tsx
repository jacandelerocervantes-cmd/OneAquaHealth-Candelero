import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { AppProvider } from "@/lib/client/app-context";
import type { ServerConfig } from "@/lib/server/config";
import { handleProxy } from "@/lib/server/proxy";

export const MOCK_CONFIG: ServerConfig = { mode: "mock", backendUrl: null, apiKey: null };

/**
 * Routes the browser's same-origin calls (`/api/oah/...`) to the real proxy handler running on
 * mock data, so component tests exercise the whole path without a network.
 */
export function installProxyFetch(overrides?: (url: URL, init?: RequestInit) => Response | undefined) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input.toString(), "http://localhost");
    calls.push({ url: url.pathname + url.search, init });
    const custom = overrides?.(url, init);
    if (custom) return custom;
    const segments = url.pathname.replace(/^\/api\/oah\//, "").split("/").filter(Boolean);
    return handleProxy(new Request(url, init), segments, MOCK_CONFIG);
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function renderWithApp(ui: ReactElement) {
  return render(<AppProvider>{ui}</AppProvider>);
}

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}
