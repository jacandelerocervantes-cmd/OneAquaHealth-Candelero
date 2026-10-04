import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PlaceFinder from "@/components/place-finder";
import { updateSettings } from "@/lib/client/settings-store";
import { finderKinds, indexIdFromPath, mapKinds } from "@/lib/places";
import { installProxyFetch, renderWithApp } from "./helpers";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  pathname = "/";
  window.localStorage.clear();
  updateSettings({ country: "GR", defaultCountry: "GR", language: "en", defaultLanguage: "en" });
});
afterEach(() => vi.unstubAllGlobals());

describe("which places a screen is about", () => {
  it("the home page is about everything, an index about its own places", () => {
    expect(mapKinds("/")).toEqual(["site", "bathing-water"]);
    expect(mapKinds("/i/water-parameters")).toEqual(["site"]);
    expect(mapKinds("/i/data-quality")).toEqual(["site"]);
    expect(mapKinds("/i/bathing-classes")).toEqual(["bathing-water"]);
    expect(mapKinds("/i/bathing-samples")).toEqual(["bathing-water"]);
    expect(mapKinds("/labs/river-risk")).toEqual(["site"]);
  });

  it("the finder is hidden where no place can be picked", () => {
    expect(finderKinds("/labs/citizen-science")).toEqual([]);
    expect(finderKinds("/settings")).toEqual([]);
    expect(finderKinds("/i/weather")).toEqual(["site"]);
    expect(indexIdFromPath("/i/weather")).toBe("weather");
    expect(indexIdFromPath("/")).toBeNull();
  });
});

describe("sidebar place finder", () => {
  it("on the home page it finds sites and bathing waters together", async () => {
    installProxyFetch();
    renderWithApp(<PlaceFinder />);
    const list = await screen.findByRole("list", { name: "Places" });
    expect(within(list).getByRole("button", { name: /Mock River Alpha/ })).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: /Mock Beach Aegean/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Place")).toBeInTheDocument();
  });

  it("inside an index it lists only the places of that index", async () => {
    pathname = "/i/bathing-samples";
    installProxyFetch();
    renderWithApp(<PlaceFinder />);
    const list = await screen.findByRole("list", { name: "Places" });
    expect(within(list).getByRole("button", { name: /Mock Beach Aegean/ })).toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: /Mock River Alpha/ })).toBeNull();
    expect(screen.getByLabelText("Bathing water")).toBeInTheDocument();
  });

  it("searches by name and says so when nothing matches", async () => {
    pathname = "/i/weather";
    installProxyFetch();
    renderWithApp(<PlaceFinder />);
    await screen.findByRole("list", { name: "Places" });
    await userEvent.type(screen.getByLabelText("Site"), "zzzz");
    expect(await screen.findByTestId("no-places")).toBeInTheDocument();
  });

  it("picking a place shows it under the search box and Clear removes it", async () => {
    pathname = "/i/weather";
    installProxyFetch();
    renderWithApp(<PlaceFinder />);
    await userEvent.click(await screen.findByRole("button", { name: /Mock River Alpha/ }));
    const picked = await screen.findByTestId("picked-place");
    expect(picked).toHaveTextContent("Mock River Alpha");
    expect(screen.queryByRole("list", { name: "Places" })).toBeNull();
    await userEvent.click(within(picked).getByRole("button", { name: "Clear" }));
    expect(screen.queryByTestId("picked-place")).toBeNull();
  });

  it("renders nothing on a lab page", () => {
    pathname = "/labs/river-risk";
    installProxyFetch();
    const { container } = renderWithApp(<PlaceFinder />);
    expect(container).toBeEmptyDOMElement();
  });
});
