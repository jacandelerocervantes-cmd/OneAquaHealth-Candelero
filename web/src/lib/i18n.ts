"use client";

import { useCallback, useEffect, useState } from "react";
import { useSettings } from "@/lib/client/settings-store";
import { resolveLocale, translate, type Dict, type TFunction } from "@/lib/i18n-core";

/**
 * Interface language hook. Dictionaries live in `src/lib/locales/<code>.json`, are loaded on demand and are
 * machine-drafted (docs/web_app_i18n.md). The 26 codes are the ones of the backend (`GET /languages`).
 */
export { countryName, interpolate, msg, resolveLocale, intlTag, translate, translateEnglish } from "@/lib/i18n-core";
export type { Dict, Params, TFunction } from "@/lib/i18n-core";

const LOADERS: Record<string, () => Promise<{ default: Dict }>> = {
  bg: () => import("./locales/bg.json"),
  cs: () => import("./locales/cs.json"),
  da: () => import("./locales/da.json"),
  de: () => import("./locales/de.json"),
  el: () => import("./locales/el.json"),
  "es-ES": () => import("./locales/es-ES.json"),
  "es-MX": () => import("./locales/es-MX.json"),
  et: () => import("./locales/et.json"),
  fi: () => import("./locales/fi.json"),
  fr: () => import("./locales/fr.json"),
  ga: () => import("./locales/ga.json"),
  hr: () => import("./locales/hr.json"),
  hu: () => import("./locales/hu.json"),
  it: () => import("./locales/it.json"),
  lt: () => import("./locales/lt.json"),
  lv: () => import("./locales/lv.json"),
  mt: () => import("./locales/mt.json"),
  nb: () => import("./locales/nb.json"),
  nl: () => import("./locales/nl.json"),
  pl: () => import("./locales/pl.json"),
  pt: () => import("./locales/pt.json"),
  ro: () => import("./locales/ro.json"),
  sk: () => import("./locales/sk.json"),
  sl: () => import("./locales/sl.json"),
  sv: () => import("./locales/sv.json"),
};

const cache = new Map<string, Dict>();
const pending = new Map<string, Promise<void>>();

function load(locale: string): Promise<void> {
  if (locale === "en" || cache.has(locale)) return Promise.resolve();
  let promise = pending.get(locale);
  if (!promise) {
    const loader = LOADERS[locale];
    promise = (loader ? loader() : Promise.reject(new Error("no dictionary")))
      .then((mod) => {
        cache.set(locale, mod.default);
      })
      .catch(() => {
        // The interface stays in English for this language; nothing else depends on the dictionary.
        cache.set(locale, {});
      });
    pending.set(locale, promise);
  }
  return promise;
}

/** `t(key, params)` in the language selected in the settings; re-renders when the dictionary has loaded. */
export function useT(): TFunction {
  const { language } = useSettings();
  const locale = resolveLocale(language);
  const [, setLoaded] = useState(0);
  useEffect(() => {
    let alive = true;
    void load(locale).then(() => {
      if (alive) setLoaded((n) => n + 1);
    });
    return () => {
      alive = false;
    };
  }, [locale]);
  const dict = cache.get(locale);
  return useCallback((key, params) => translate(dict, key, params), [dict]);
}
