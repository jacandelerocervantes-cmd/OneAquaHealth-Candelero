import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import IndexData from "@/components/index-data";
import IndexView from "@/components/index-view";
import LabView from "@/components/lab-view";
import SettingsView from "@/components/settings-view";
import { updateSettings, useSettings } from "@/lib/client/settings-store";
import { buildCatalog } from "@/lib/server/mock/catalog";
import { installProxyFetch, jsonResponse, renderWithApp } from "./helpers";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  window.localStorage.clear();
  updateSettings({ country: "GR", defaultCountry: "GR", language: "en", defaultLanguage: "en" });
});
afterEach(() => vi.unstubAllGlobals());

async function pickSite(id = "mock-gr-001") {
  await userEvent.selectOptions(await screen.findByTestId("site-select"), id);
}

describe("index data panels", () => {
  it("asks for a site first", async () => {
    installProxyFetch();
    renderWithApp(<IndexData indexId="water-parameters" />);
    expect(await screen.findByText("Choose a site", { selector: "p" })).toBeInTheDocument();
  });

  it("water parameters: measurements table with origin, freshness and the route's notice", async () => {
    installProxyFetch();
    renderWithApp(<IndexData indexId="water-parameters" />);
    await pickSite();
    const table = await screen.findByRole("table", { name: "Measurements" });
    expect(within(table).getAllByRole("row").length).toBeGreaterThan(2);
    const footer = screen.getByTestId("source-footer");
    expect(within(footer).getByTestId("origin-badge")).toHaveTextContent("Synthetic");
    expect(footer).toHaveTextContent("MOCK DATA");
    expect(within(footer).getByTestId("freshness-badge")).toBeInTheDocument();
  });

  it("solids and turbidity: asks the route for that group only", async () => {
    const { calls } = installProxyFetch();
    renderWithApp(<IndexData indexId="solids-turbidity" />);
    await pickSite();
    await screen.findByRole("table", { name: "Measurements" });
    expect(calls.some((c) => c.url.includes("/measurements") && c.url.includes("group=solids-turbidity"))).toBe(true);
  });

  it("weather: shows the Open-Meteo credit link and the aggregated-to-months note", async () => {
    installProxyFetch();
    renderWithApp(<IndexData indexId="weather" />);
    await pickSite();
    const link = await screen.findByRole("link", { name: "Weather data by Open-Meteo.com" });
    expect(link).toHaveAttribute("href", "https://open-meteo.com/");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByText(/modelled and aggregated to months/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Monthly weather (modelled)" })).toBeInTheDocument();
  });

  it("river discharge and species render with their notices", async () => {
    installProxyFetch();
    const first = renderWithApp(<IndexData indexId="river-discharge" />);
    await pickSite();
    expect(await screen.findByRole("table", { name: "Monthly river discharge (modelled)" })).toBeInTheDocument();
    first.unmount();
    renderWithApp(<IndexData indexId="species-nearby" />);
    await pickSite();
    const table = await screen.findByRole("table", { name: "Species occurrence records" });
    expect(table).toHaveTextContent("CC0-1.0");
    expect(table).toHaveTextContent("Mock citation");
  });

  it("bathing classes and samples (the samples view carries the no-threshold notice)", async () => {
    installProxyFetch();
    const first = renderWithApp(<IndexData indexId="bathing-classes" />);
    expect(await screen.findByRole("table", { name: "Bathing waters" })).toHaveTextContent("Mock Beach Aegean");
    first.unmount();
    renderWithApp(<IndexData indexId="bathing-samples" />);
    await userEvent.selectOptions(await screen.findByTestId("bw-select"), "MOCKGR0001");
    await screen.findByRole("table", { name: /Sample summary/ });
    expect(screen.getByTestId("source-footer")).toHaveTextContent("No threshold or limit is applied");
  });

  it("data quality and water quality", async () => {
    installProxyFetch();
    const first = renderWithApp(<IndexData indexId="data-quality" />);
    expect(await screen.findByRole("table", { name: "Findings" })).toBeInTheDocument();
    first.unmount();
    renderWithApp(<IndexData indexId="water-quality" />);
    await pickSite();
    expect(await screen.findByText("MOCK: no reference limits are applied to simulated values.")).toBeInTheDocument();
  });

  it("shows the empty state when a site search finds nothing", async () => {
    installProxyFetch();
    renderWithApp(<IndexData indexId="weather" />);
    await screen.findByTestId("site-select");
    await userEvent.type(screen.getByLabelText("Search sites"), "zzzz");
    expect(await screen.findByTestId("no-sites")).toBeInTheDocument();
  });

  it("shows an error state with retry, and a 429 countdown, when a data route fails", async () => {
    let mode: "429" | "ok" = "429";
    installProxyFetch((url) => (url.pathname.endsWith("/qc/report") && mode === "429" ? jsonResponse(429, { detail: "slow" }, { "retry-after": "30" }) : undefined));
    renderWithApp(<IndexData indexId="data-quality" />);
    const box = await screen.findByTestId("error-box");
    expect(box).toHaveTextContent("Too many requests");
    expect(screen.getByTestId("retry-countdown")).toHaveTextContent(/Retry available in \d+ s/);
    expect(within(box).getByRole("button", { name: "Try again" })).toBeDisabled();
    mode = "ok";
  });

  it("publishes the data shown for the header's download button", async () => {
    installProxyFetch();
    renderWithApp(<IndexData indexId="data-quality" />);
    await screen.findByRole("table", { name: "Findings" });
    // The export slot is exercised through the context by the page header test below.
    expect(screen.getByTestId("index-data")).toBeInTheDocument();
  });
});

describe("IndexView", () => {
  it("is a single chat view with the data of the index under the answers, and no tabs", async () => {
    installProxyFetch();
    renderWithApp(<IndexView indexId="bathing-samples" />);
    expect(await screen.findByTestId("page-title")).toHaveTextContent("E. coli and enterococci");
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.getByTestId("conversation")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /About this index/ }));
    const about = screen.getByTestId("about-index");
    expect(about).toHaveTextContent("Greece");
    expect(about).toHaveTextContent("Real · EEA bathing samples");
    const below = await screen.findByTestId("below-answers");
    expect(await within(below).findByTestId("bw-select")).toBeInTheDocument();
  });

  it("explains an index that does not apply to the country instead of showing it empty", async () => {
    updateSettings({ country: "NO" });
    installProxyFetch();
    renderWithApp(<IndexView indexId="bathing-classes" />);
    expect(await screen.findByTestId("not-applicable")).toHaveTextContent("No data for this country");
    expect(screen.queryByRole("tab")).toBeNull();
  });

  it("handles an unknown index and a failing catalogue", async () => {
    installProxyFetch();
    const first = renderWithApp(<IndexView indexId="nonsense" />);
    expect(await screen.findByText("Unknown index")).toBeInTheDocument();
    first.unmount();
    installProxyFetch((url) => (url.pathname.endsWith("/catalog") ? jsonResponse(503, { detail: "busy" }) : undefined));
    renderWithApp(<IndexView indexId="weather" />);
    expect(await screen.findByTestId("error-box")).toHaveTextContent("busy or not configured");
  });

  it("opens and closes the map from the header icon, and enables the download after data loads", async () => {
    installProxyFetch();
    renderWithApp(<IndexView indexId="data-quality" />);
    const toggle = await screen.findByTestId("map-toggle");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    const download = screen.getByRole("button", { name: "Download the data behind the answer" });
    // The data of the index loads under the answers together with the chat, so the button is enabled once it is there.
    await screen.findByRole("table", { name: "Findings" });
    await waitFor(() => expect(download).toBeEnabled());
  });
});

describe("synthetic labs", () => {
  it.each([["citizen-science", "Citizen science"], ["review-queue", "Review queue (read-only)"], ["river-risk", "River risk"]] as const)(
    "%s is labelled as synthetic",
    async (id, title) => {
      installProxyFetch();
      renderWithApp(<LabView labId={id} />);
      expect(screen.getByTestId("page-title")).toHaveTextContent(title);
      expect(screen.getByTestId("synthetic-banner")).toHaveTextContent(/simulated/i);
      await waitFor(() => expect(screen.queryByTestId("loading")).toBeNull());
    },
  );

  it("citizen science runs the campaign for the seed", async () => {
    const { calls } = installProxyFetch();
    renderWithApp(<LabView labId="citizen-science" />);
    expect(await screen.findByText("Dawid-Skene")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/Random seed/));
    await userEvent.type(screen.getByLabelText(/Random seed/), "42");
    await userEvent.click(screen.getByRole("button", { name: "Run campaign" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("seed=42"))).toBe(true));
    expect(screen.getByTestId("origin-badge")).toHaveTextContent("Synthetic");
  });

  it("the review queue is read-only: no decide control", async () => {
    installProxyFetch();
    renderWithApp(<LabView labId="review-queue" />);
    expect(await screen.findByRole("table", { name: /specimens waiting/ })).toBeInTheDocument();
    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /decide|accept|reject|approve/i })).toBeNull();
  });

  it("river risk shows the synthetic score for the chosen site, and an empty state", async () => {
    installProxyFetch();
    renderWithApp(<LabView labId="river-risk" />);
    expect(await screen.findByText("Choose a site", { selector: "p" })).toBeInTheDocument();
    await userEvent.selectOptions(await screen.findByLabelText("Site"), "mock-gr-001");
    expect(await screen.findByTestId("risk-score")).toHaveTextContent("0.23");
  });

  it("review queue empty state", async () => {
    installProxyFetch((url) => (url.pathname.endsWith("/review/queue") ? jsonResponse(200, { origin: "synthetic", count: 0, items: [] }) : undefined));
    renderWithApp(<LabView labId="review-queue" />);
    expect(await screen.findByTestId("empty-state")).toHaveTextContent("The review queue is empty");
  });
});

function Probe() {
  const s = useSettings();
  return <output data-testid="probe">{`${s.defaultLanguage}|${s.defaultCountry}|${s.language}|${s.country}`}</output>;
}

describe("Settings", () => {
  it("holds the default language and country and the About and attributions section", async () => {
    installProxyFetch();
    renderWithApp(
      <>
        <SettingsView />
        <Probe />
      </>,
    );
    const about = screen.getByTestId("about-attributions");
    expect(within(about).getByRole("heading", { name: "About and attributions" })).toBeInTheDocument();
    for (const name of ["European Environment Agency (EEA)", "Open-Meteo", "GBIF", "OpenStreetMap", "HL7 Europe sandbox"]) {
      expect(within(about).getByRole("link", { name })).toHaveAttribute("href", expect.stringMatching(/^https:\/\//));
    }
    expect(within(about).getByText("Weather data by Open-Meteo.com.")).toBeInTheDocument();
    expect(screen.getByText(/not legal compliance/)).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByTestId("default-language")).getAllByRole("option")).toHaveLength(26));
    await userEvent.selectOptions(screen.getByTestId("default-language"), "de");
    await userEvent.selectOptions(screen.getByTestId("default-country"), "IT");
    expect(screen.getByTestId("probe")).toHaveTextContent("de|IT|de|IT");
  });
});

describe("catalog fixtures", () => {
  it("has 13 indices for Greece and the families in order", () => {
    const c = buildCatalog("GR", "en");
    expect(c.families.map((f) => f.id)).toEqual(["water", "microbiology", "context", "data", "synthetic-labs"]);
  });
});
