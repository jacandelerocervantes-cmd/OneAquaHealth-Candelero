import { render } from "@testing-library/react";
import { useEffect, type ReactElement, type ReactNode } from "react";
import { vi } from "vitest";
import { AppProvider, useApp, type PickedPlace } from "@/lib/client/app-context";
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

export const SITE_GR: PickedPlace = { kind: "site", id: "mock-gr-001", name: "Mock site", country: "GR", latitude: 38, longitude: 23 };
export const BATHING_GR: PickedPlace = { kind: "bathing-water", id: "MOCKGR0001", name: "Mock Beach Aegean", country: "GR", latitude: 37, longitude: 23 };

function Seed({ place, children }: { place: PickedPlace; children: ReactNode }) {
  const { setPlace } = useApp();
  useEffect(() => setPlace(place), [place, setPlace]);
  return <>{children}</>;
}

/** Renders with a place already picked, as if it had been chosen in the sidebar or on the map. */
export function renderWithPlace(ui: ReactElement, place: PickedPlace) {
  return render(
    <AppProvider>
      <Seed place={place}>{ui}</Seed>
    </AppProvider>,
  );
}

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}
