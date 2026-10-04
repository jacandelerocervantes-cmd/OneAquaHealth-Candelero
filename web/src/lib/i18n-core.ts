/**
 * Pure helpers of the interface language (no React, importable from server and client code).
 * The key of every text is the English text itself: `t("Search by name")`. A language without that key (or English)
 * shows the key, so a missing translation is readable English and never blank.
 */
export type Dict = Record<string, string>;
export type Params = Record<string, string | number>;
export type TFunction = (key: string, params?: Params) => string;

/** The dictionary codes that exist (one file per language in `src/lib/locales`); "en" needs none. */
export const TRANSLATED_LANGUAGES = [
  "bg", "cs", "da", "de", "el", "es-ES", "es-MX", "et", "fi", "fr", "ga", "hr", "hu", "it",
  "lt", "lv", "mt", "nb", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
] as const;

/** Marks a text for extraction without translating it where it is declared; translate it at render time with `t()`. */
export function msg(text: string): string {
  return text;
}

/** The dictionary code that serves a language code ("en" and anything unknown serve English). */
export function resolveLocale(language: string): string {
  if ((TRANSLATED_LANGUAGES as readonly string[]).includes(language)) return language;
  const base = language.split("-")[0]?.toLowerCase() ?? "";
  if (base === "es") return "es-MX";
  if (base === "no" || base === "nn") return "nb";
  if ((TRANSLATED_LANGUAGES as readonly string[]).includes(base)) return base;
  return "en";
}

/** The BCP 47 tag used for number and region-name formatting. */
export function intlTag(language: string): string {
  const locale = resolveLocale(language);
  return locale === "nb" ? "nb-NO" : locale;
}

/** The short label of a language in a narrow selector: its code in capitals (EN, IT, FR, ES-MX). */
export function languageShortLabel(code: string): string {
  return code.toUpperCase();
}

export function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => (name in params ? String(params[name]) : whole));
}

export function translate(dict: Dict | undefined, key: string, params?: Params): string {
  return interpolate(dict?.[key] ?? key, params);
}

/** `t` for English: used where no hook is available (tests, error boundaries outside the provider). */
export const translateEnglish: TFunction = (key, params) => interpolate(key, params);

/** Country name in the selected language (the browser's region names), falling back to the English table. */
export function countryName(code: string, language: string, fallback: Record<string, string>): string {
  if (code === "ZZ") return fallback[code] ?? code; // the "unknown region" code has a name in Intl; show the code instead
  try {
    const name = new Intl.DisplayNames([intlTag(language)], { type: "region" }).of(code);
    if (name && name !== code) return name;
  } catch {
    // an unknown region code or an engine without region names: use the table
  }
  return fallback[code] ?? code;
}
