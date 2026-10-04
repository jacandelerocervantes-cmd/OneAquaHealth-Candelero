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
  it("the map shows everything on the home page and an index's own places inside an index", () => {
    expect(mapKinds("/")).toEqual(["site", "bathing-water"]);
    expect(mapKinds("/i/water-parameters")).toEqual(["site"]);
    expect(mapKinds("/i/data-quality")).toEqual(["site"]);
    expect(mapKinds("/i/bathing-classes")).toEqual(["bathing-water"]);
    expect(mapKinds("/i/bathing-samples")).toEqual(["bathing-water"]);
    expect(mapKinds("/labs/river-risk")).toEqual(["site"]);
  });

  it("the sidebar search is for sites only and is hidden where it cannot apply", () => {
    expect(finderKinds("/")).toEqual(["site"]);
    expect(finderKinds("/i/weather")).toEqual(["site"]);
    expect(finderKinds("/i/bathing-classes")).toEqual([]);
    expect(finderKinds("/i/bathing-samples")).toEqual([]);
    expect(finderKinds("/labs/citizen-science")).toEqual([]);
    expect(finderKinds("/settings")).toEqual([]);
    expect(indexIdFromPath("/i/weather")).toBe("weather");
    expect(indexIdFromPath("/")).toBeNull();
  });
});

describe("sidebar site search with suggestions", () => {
  it("lists nothing until something is typed, then suggests sites only", async () => {
    const { calls } = installProxyFetch();
    renderWithApp(<PlaceFinder />);
    const box = screen.getByRole("combobox", { name: "Site" });
    expect(box).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(calls.some((c) => c.url.includes("/sites"))).toBe(false);
    await userEvent.type(box, "Mock");
    const list = await screen.findByRole("listbox", { name: "Places" });
    expect(box).toHaveAttribute("aria-expanded", "true");
    expect(within(list).getByRole("option", { name: /Mock River Alpha/ })).toBeInTheDocument();
    expect(within(list).queryByText(/Beach/)).toBeNull();
    expect(calls.some((c) => c.url.includes("/bathing-waters"))).toBe(false);
  });

  it("emphasises what was typed inside each suggestion", async () => {
    installProxyFetch();
    renderWithApp(<PlaceFinder />);
    await userEvent.type(screen.getByRole("combobox", { name: "Site" }), "river a");
    const option = await screen.findByRole("option", { name: /Mock River Alpha/ });
    const bold = option.querySelector("b");
    expect(bold?.textContent).toBe("River A");
  });

  it("shows at most five suggestions in a list that never scrolls, and asks for five", async () => {
    const { calls } = installProxyFetch();
    renderWithApp(<PlaceFinder />);
    await userEvent.type(screen.getByRole("combobox", { name: "Site" }), "Mock");
    const list = await screen.findByRole("listbox", { name: "Places" });
    expect(within(list).getAllByRole("option").length).toBeLessThanOrEqual(5);
    expect(screen.getByTestId("place-suggestions").className).not.toMatch(/overflow-y|max-h/);
    expect(calls.some((c) => c.url.includes("limit=5"))).toBe(true);
  });

  it("says so when nothing matches", async () => {
    installProxyFetch();
    renderWithApp(<PlaceFinder />);
    await userEvent.type(screen.getByRole("combobox", { name: "Site" }), "zzzz");
    expect(await screen.findByTestId("no-places")).toBeInTheDocument();
  });

  it("works with the keyboard: arrows move, Enter picks, Escape closes", async () => {
    installProxyFetch();
    renderWithApp(<PlaceFinder />);
    const box = screen.getByRole("combobox", { name: "Site" });
    await userEvent.type(box, "Mock");
    await screen.findByRole("listbox", { name: "Places" });
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    await userEvent.keyboard("{ArrowDown}");
    const list = await screen.findByRole("listbox", { name: "Places" });
    const options = within(list).getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowDown}");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowUp}");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Enter}");
    const picked = await screen.findByTestId("picked-place");
    expect(picked).toHaveTextContent(options[0]?.textContent ?? "");
  });

  it("picking a site shows it under the search box, closes the list, and Clear removes it", async () => {
    pathname = "/i/weather";
    installProxyFetch();
    renderWithApp(<PlaceFinder />);
    await userEvent.type(screen.getByRole("combobox", { name: "Site" }), "Alpha");
    await userEvent.click(await screen.findByRole("option", { name: /Mock River Alpha/ }));
    const picked = await screen.findByTestId("picked-place");
    expect(picked).toHaveTextContent("Mock River Alpha");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByRole("combobox", { name: "Site" })).toHaveValue("");
    await userEvent.click(within(picked).getByRole("button", { name: "Clear" }));
    expect(screen.queryByTestId("picked-place")).toBeNull();
  });

  it.each(["/i/bathing-classes", "/i/bathing-samples", "/labs/river-risk", "/settings"])("renders nothing on %s", (path) => {
    pathname = path;
    installProxyFetch();
    const { container } = renderWithApp(<PlaceFinder />);
    expect(container).toBeEmptyDOMElement();
  });
});
