import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MapPane from "@/components/map-pane";
import { updateSettings } from "@/lib/client/settings-store";
import { installProxyFetch, renderWithApp } from "./helpers";

vi.mock("next/navigation", () => ({ usePathname: () => "/i/data-quality", useRouter: () => ({ push: vi.fn() }) }));
// Leaflet needs a real layout engine; the pane's own wiring is what is under test here.
vi.mock("leaflet", () => {
  const map = { setView: () => map, fitBounds: vi.fn(), invalidateSize: vi.fn(), remove: vi.fn() };
  const layer = { addTo: () => layer, clearLayers: vi.fn() };
  const L = {
    map: () => map,
    tileLayer: () => layer,
    layerGroup: () => layer,
    latLngBounds: () => ({}),
    circleMarker: () => ({ bindTooltip: vi.fn(), on: vi.fn(), addTo: vi.fn() }),
  };
  return { default: L, ...L };
});
vi.mock("leaflet/dist/leaflet.css", () => ({}));

beforeEach(() => {
  window.localStorage.clear();
  updateSettings({ country: "GR", defaultCountry: "GR", language: "en", defaultLanguage: "en" });
});
afterEach(() => vi.unstubAllGlobals());

function Harness() {
  const [wide, setWide] = useState(false);
  return <MapPane expanded={wide} onToggleExpanded={() => setWide((w) => !w)} />;
}

describe("map pane expand button", () => {
  it("switches between the default and the expanded map and says which one is active", async () => {
    installProxyFetch();
    renderWithApp(<Harness />);
    const button = await screen.findByTestId("map-expand");
    expect(button).toHaveTextContent("Expand");
    expect(button).toHaveAttribute("aria-pressed", "false");
    const canvas = await screen.findByTestId("map-canvas");
    expect(canvas.className).toContain("h-64");
    await userEvent.click(button);
    expect(button).toHaveTextContent("Shrink");
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(canvas.className).toContain("h-[60vh]");
    await userEvent.click(button);
    expect(canvas.className).toContain("h-64");
  });

  it("has no expand button when the parent does not provide one", async () => {
    installProxyFetch();
    renderWithApp(<MapPane />);
    await screen.findByRole("complementary", { name: "Map" });
    expect(screen.queryByTestId("map-expand")).toBeNull();
  });
});
