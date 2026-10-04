"use client";

import { useSyncExternalStore } from "react";
import { DEFAULT_COUNTRY, DEFAULT_LANGUAGE } from "@/lib/constants";

/** Per-viewer conveniences kept in the browser. Nothing secret, nothing the server needs. */
export interface Settings {
  defaultCountry: string;
  defaultLanguage: string;
  /** The country and language currently selected (they start from the defaults). */
  country: string;
  language: string;
}

const STORAGE_KEY = "oah.settings.v1";

export const DEFAULT_SETTINGS: Settings = {
  defaultCountry: DEFAULT_COUNTRY,
  defaultLanguage: DEFAULT_LANGUAGE,
  country: DEFAULT_COUNTRY,
  language: DEFAULT_LANGUAGE,
};

const COUNTRY = /^[A-Z]{2}$/;
const LANGUAGE = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$/;

/** Accept only well-formed values from storage; anything else falls back to the defaults. */
export function sanitiseSettings(raw: unknown): Settings {
  if (typeof raw !== "object" || raw === null) return DEFAULT_SETTINGS;
  const o = raw as Record<string, unknown>;
  const country = (v: unknown, fallback: string) => (typeof v === "string" && COUNTRY.test(v) ? v : fallback);
  const language = (v: unknown, fallback: string) => (typeof v === "string" && LANGUAGE.test(v) ? v : fallback);
  const defaultCountry = country(o.defaultCountry, DEFAULT_SETTINGS.defaultCountry);
  const defaultLanguage = language(o.defaultLanguage, DEFAULT_SETTINGS.defaultLanguage);
  return {
    defaultCountry,
    defaultLanguage,
    country: country(o.country, defaultCountry),
    language: language(o.language, defaultLanguage),
  };
}

let cachedRaw: string | null = null;
let cachedValue: Settings = DEFAULT_SETTINGS;
const listeners = new Set<() => void>();

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function getSnapshot(): Settings {
  const raw = readRaw();
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedValue = raw ? sanitiseSettings(JSON.parse(raw)) : DEFAULT_SETTINGS;
    } catch {
      cachedValue = DEFAULT_SETTINGS;
    }
  }
  return cachedValue;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export function updateSettings(patch: Partial<Settings>): void {
  const next = sanitiseSettings({ ...getSnapshot(), ...patch });
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage may be unavailable (private window): keep the value in memory for this page.
    cachedRaw = null;
    cachedValue = next;
  }
  listeners.forEach((l) => l());
}

export function useSettings(): Settings {
  return useSyncExternalStore(subscribe, getSnapshot, () => DEFAULT_SETTINGS);
}
