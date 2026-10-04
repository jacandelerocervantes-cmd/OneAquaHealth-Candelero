import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import esMX from "@/lib/locales/es-MX.json";
import keys from "@/lib/locales/_keys.json";
import { DEFAULT_SETTINGS, getSettings, updateSettings } from "@/lib/client/settings-store";
import { formatNumber } from "@/lib/format";
import { countryName, interpolate, intlTag, resolveLocale, translate, useT } from "@/lib/i18n";
import { COUNTRY_NAMES } from "@/lib/constants";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  window.localStorage.clear();
  updateSettings({ language: "en", defaultLanguage: "en" });
});
afterEach(() => vi.unstubAllGlobals());

function Probe({ text }: { text: string }) {
  const t = useT();
  return <p data-testid="probe">{t(text, { n: 3 })}</p>;
}

describe("the default language", () => {
  it("is English for a visitor who has chosen nothing", () => {
    window.localStorage.clear();
    expect(DEFAULT_SETTINGS.language).toBe("en");
    expect(DEFAULT_SETTINGS.defaultLanguage).toBe("en");
    expect(getSettings().language).toBe("en");
  });

  it("shows the interface in English when nothing is stored", () => {
    window.localStorage.clear();
    render(<Probe text="Wait {n} s" />);
    expect(screen.getByTestId("probe")).toHaveTextContent("Wait 3 s");
  });
});

describe("language resolution and formatting", () => {
  it("maps language codes to dictionaries", () => {
    expect(resolveLocale("es-MX")).toBe("es-MX");
    expect(resolveLocale("es-AR")).toBe("es-MX");
    expect(resolveLocale("es")).toBe("es-MX");
    expect(resolveLocale("pt-BR")).toBe("pt");
    expect(resolveLocale("no")).toBe("nb");
    expect(resolveLocale("en")).toBe("en");
    expect(resolveLocale("xx")).toBe("en");
    expect(intlTag("nb")).toBe("nb-NO");
  });

  it("fills placeholders and falls back to the English key when a text has no translation", () => {
    expect(interpolate("Wait {n} s", { n: 4 })).toBe("Wait 4 s");
    expect(interpolate("Wait {n} s")).toBe("Wait {n} s");
    expect(translate({ Hello: "Hola" }, "Hello")).toBe("Hola");
    expect(translate({}, "Hello {name}", { name: "Ana" })).toBe("Hello Ana");
    expect(translate(undefined, "Only English")).toBe("Only English");
  });

  it("writes numbers with the decimal mark of the selected language", () => {
    expect(formatNumber(0.06)).toBe("0.06");
    updateSettings({ language: "es-ES" });
    expect(formatNumber(0.06)).toBe("0,06");
    updateSettings({ language: "de" });
    expect(formatNumber(12.5, 1)).toBe("12,5");
    expect(formatNumber(1234567.8)).toMatch(/e\+6$/);
    expect(formatNumber(null)).toBe("n/a");
  });

  it("names countries in the selected language and falls back to the English table", () => {
    expect(countryName("GR", "en", COUNTRY_NAMES)).toBe("Greece");
    expect(countryName("GR", "es-MX", COUNTRY_NAMES)).toBe("Grecia");
    expect(countryName("ZZ", "en", COUNTRY_NAMES)).toBe("ZZ");
  });
});

describe("the interface follows the selected language", () => {
  it("shows English for English and the dictionary text once a language is selected", async () => {
    const key = "Wait {n} s";
    render(<Probe text={key} />);
    expect(screen.getByTestId("probe")).toHaveTextContent("Wait 3 s");
    updateSettings({ language: "es-MX" });
    const expected = (esMX as Record<string, string>)[key]?.replace("{n}", "3") ?? "";
    expect(expected).not.toBe("");
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent(expected));
    expect(expected).not.toBe("Wait 3 s");
  });

  it("keeps a readable English text when the text is unknown to the dictionary", async () => {
    updateSettings({ language: "es-MX" });
    render(<Probe text="A text that is not in any dictionary {n}" />);
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("A text that is not in any dictionary 3"));
  });
});

describe("the extracted keys", () => {
  it("are unique, non-empty and free of markup", () => {
    expect(new Set(keys).size).toBe(keys.length);
    for (const k of keys) {
      expect(k.trim()).not.toBe("");
      expect(k).not.toMatch(/<[a-zA-Z/!]/);
    }
  });
});
