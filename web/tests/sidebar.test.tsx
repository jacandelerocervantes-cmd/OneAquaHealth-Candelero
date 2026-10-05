import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Sidebar, { indexHref, visibleFamilies } from "@/components/sidebar";
import type { CatalogResponse } from "@/lib/api";
import { updateSettings } from "@/lib/client/settings-store";
import { buildCatalog } from "@/lib/server/mock/catalog";
import { installProxyFetch, renderWithApp } from "./helpers";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/i/water-parameters",
  useRouter: () => ({ push }),
}));

beforeEach(() => {
  window.localStorage.clear();
  updateSettings({ country: "GR", defaultCountry: "GR", language: "en", defaultLanguage: "en" });
  push.mockClear();
});
afterEach(() => vi.unstubAllGlobals());

describe("brand", () => {
  it("shows the product name at the top of the sidebar, in every language", async () => {
    installProxyFetch();
    renderWithApp(<Sidebar />);
    expect(screen.getByTestId("brand")).toHaveTextContent("AquaLedger");
    updateSettings({ language: "de" });
    expect(await screen.findByRole("button", { name: "+ Neue Frage" })).toBeInTheDocument();
    expect(screen.getByTestId("brand")).toHaveTextContent("AquaLedger");
  });
});

describe("language selector in the sidebar", () => {
  it("sits next to the country, offers the 26 languages as short codes with the full name as a tooltip", async () => {
    installProxyFetch();
    renderWithApp(<Sidebar />);
    const select = screen.getByTestId("language-select");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(26));
    expect(select).toHaveValue("en");
    const options = within(select).getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((o) => o.textContent)).toEqual(expect.arrayContaining(["EN", "IT", "FR", "ES-MX", "ES-ES", "NB"]));
    expect(options.find((o) => o.value === "fr")?.title).toBe("Français");
    expect(screen.getByTestId("country-select").parentElement?.parentElement).toBe(select.parentElement?.parentElement);
  });

  it("changes the language of the whole interface when another one is picked", async () => {
    installProxyFetch();
    renderWithApp(<Sidebar />);
    const select = screen.getByTestId("language-select");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(26));
    expect(screen.getByRole("button", { name: "+ New question" })).toBeInTheDocument();
    await userEvent.selectOptions(select, "es-MX");
    expect(await screen.findByRole("button", { name: "+ Nueva pregunta" })).toBeInTheDocument();
    expect(screen.getByLabelText("País")).toBeInTheDocument();
  });
});

describe("visibleFamilies", () => {
  it("hides indices that do not apply and drops empty sections", () => {
    const no = buildCatalog("NO", "en");
    const names = visibleFamilies(no).flatMap((f) => f.indices.map((i) => i.id));
    expect(names).not.toContain("organic-matter");
    expect(names).not.toContain("bathing-classes");
    expect(names).not.toContain("bathing-samples");
    expect(visibleFamilies(no).map((f) => f.id)).not.toContain("microbiology");
    expect(visibleFamilies(no).map((f) => f.id)).toContain("synthetic-labs");
  });

  it("shows everything for a country where every index applies", () => {
    const gr = buildCatalog("GR", "en");
    expect(visibleFamilies(gr).flatMap((f) => f.indices)).toHaveLength(13);
  });

  it("is driven only by `applies`", () => {
    const c: CatalogResponse = buildCatalog("GR", "en");
    const first = c.families[0]!.indices[0]!;
    first.applies = false;
    expect(visibleFamilies(c)[0]!.indices.map((i) => i.id)).not.toContain(first.id);
  });

  it("sends synthetic labs to /labs and the rest to /i", () => {
    expect(indexHref({ id: "river-risk", family_id: "synthetic-labs" })).toBe("/labs/river-risk");
    expect(indexHref({ id: "weather", family_id: "context" })).toBe("/i/weather");
  });
});

describe("Sidebar", () => {
  it("shows the country selector on top, the sections and their indices, with origin dots", async () => {
    installProxyFetch();
    renderWithApp(<Sidebar />);
    expect(screen.getByTestId("country-select")).toBeInTheDocument();
    const body = screen.getByTestId("sidebar-body");
    await within(body).findByText("Water quality");
    for (const title of ["Water", "Microbiology", "Context", "Data", "Synthetic labs"]) {
      expect(within(body).getByRole("region", { name: title })).toBeInTheDocument();
    }
    expect(within(body).getAllByRole("img", { name: "Synthetic" })).toHaveLength(3);
    expect(within(body).getAllByRole("img", { name: "External modelled context" })).toHaveLength(3);
    expect(screen.getByText("Judge account")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("shows no numbers anywhere in the entries", async () => {
    installProxyFetch();
    renderWithApp(<Sidebar />);
    const body = screen.getByTestId("sidebar-body");
    await within(body).findByText("Water quality");
    for (const link of within(body).getAllByRole("link")) expect(link.textContent).not.toMatch(/\d/);
    for (const btn of within(body).getAllByRole("button")) expect(btn.textContent).not.toMatch(/\d/);
  });

  it("re-reads the catalogue for the chosen country and hides what does not apply", async () => {
    const { calls } = installProxyFetch();
    renderWithApp(<Sidebar />);
    await screen.findByText("Bathing classes");
    await userEvent.selectOptions(screen.getByTestId("country-select"), "NO");
    await waitFor(() => expect(screen.queryByText("Bathing classes")).toBeNull());
    expect(screen.queryByText("Organic matter")).toBeNull();
    // The catalogue is asked in the selected language, so the reasons it returns are written in it.
    expect(calls.some((c) => c.url === "/api/oah/catalog?country=NO&language=en")).toBe(true);
    expect(screen.getByText("Water quality")).toBeInTheDocument();
  });

  it("falls back to a known country when the stored one is not offered", async () => {
    updateSettings({ country: "FR" });
    installProxyFetch();
    renderWithApp(<Sidebar />);
    await waitFor(() => expect(screen.getByTestId("country-select")).toHaveValue("GR"));
    expect(await screen.findByText("Water quality")).toBeInTheDocument();
  });

  it("lists the three countries from GET /countries", async () => {
    installProxyFetch();
    renderWithApp(<Sidebar />);
    await screen.findByText("Water quality");
    const options = within(screen.getByTestId("country-select")).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Greece", "Italy", "Norway"]);
  });

  it("has no '+' on the sections: a question starts from the one '+ New question' button or from an index", async () => {
    installProxyFetch();
    renderWithApp(<Sidebar />);
    await screen.findByText("Weather");
    expect(screen.queryByRole("button", { name: /New question in/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "+" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "+ New question" }));
    expect(push).toHaveBeenCalledWith("/");
  });

  it("collapses a section", async () => {
    installProxyFetch();
    renderWithApp(<Sidebar />);
    await screen.findByText("Weather");
    await userEvent.click(screen.getByRole("button", { name: /Context/, expanded: true }));
    expect(screen.queryByText("Weather")).toBeNull();
  });

  it("shows a loading state, then an error state with retry when the catalogue fails", async () => {
    let fail = true;
    installProxyFetch((url) => {
      if (url.pathname.endsWith("/catalog") && fail) return new Response(JSON.stringify({ detail: "down" }), { status: 502 });
      return undefined;
    });
    renderWithApp(<Sidebar />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
    expect(await screen.findByTestId("error-box")).toHaveTextContent("The data service is unavailable");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Water quality")).toBeInTheDocument();
  });

  it("shows an empty state when no index applies", async () => {
    installProxyFetch((url) => {
      if (!url.pathname.endsWith("/catalog")) return undefined;
      const c = buildCatalog("GR", "en");
      for (const f of c.families) for (const i of f.indices) i.applies = false;
      return new Response(JSON.stringify(c), { status: 200 });
    });
    renderWithApp(<Sidebar />);
    expect(await screen.findByTestId("empty-state")).toHaveTextContent("No indices apply to this country");
  });

  it("shows a notice for a store that is not built", async () => {
    installProxyFetch((url) => {
      if (!url.pathname.endsWith("/catalog")) return undefined;
      const c = buildCatalog("GR", "en");
      c.stores.waterbase = { ...c.stores.waterbase, state: "not-built" };
      return new Response(JSON.stringify(c), { status: 200 });
    });
    renderWithApp(<Sidebar />);
    expect(await screen.findByText(/Not loaded in this service: EEA Waterbase/)).toBeInTheDocument();
  });
});
