import { COUNTRY_CODES, type CountryCode } from "./data";

export interface MockResult {
  status: number;
  body: unknown;
  headers?: Record<string, string>;
}

export const ok = (body: unknown): MockResult => ({ status: 200, body });
export const err = (status: number, detail: string, headers?: Record<string, string>): MockResult => ({
  status,
  body: { detail },
  headers,
});

export function asCountry(value: string | null): CountryCode | null {
  const upper = (value ?? "").toUpperCase();
  const code = upper === "EL" ? "GR" : upper;
  return (COUNTRY_CODES as readonly string[]).includes(code) ? (code as CountryCode) : null;
}

export const NO_SITE = (id: string) => err(404, `Unknown site: ${id}`);
