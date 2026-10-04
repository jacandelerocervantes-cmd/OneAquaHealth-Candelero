/**
 * The only backend routes the web app may reach. Everything else answers 404 before any
 * backend call. Path segments are validated, and only the listed query parameters are
 * forwarded (anything else is dropped), so the proxy cannot be used to reach other routes,
 * to add parameters, or to reach write routes (review decisions, FHIR export).
 */

export type Method = "GET" | "POST";

interface Rule {
  method: Method;
  /** Template with `{}` for one validated path segment. */
  template: string;
  /** Allowed query parameters and a pattern for each value. */
  query: Record<string, RegExp>;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const INT = /^\d{1,7}$/;
const COUNTRY = /^[A-Za-z]{2}$/;
const LANG = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$/;
const SOURCE = /^(real-sandbox|real-eea-waterbase)$/;
const FREE = /^[^\u0000-\u001f]{1,64}$/u;

const SEGMENT = /^[A-Za-z0-9._:~-]{1,96}$/;

export const RULES: readonly Rule[] = [
  { method: "GET", template: "/countries", query: {} },
  { method: "GET", template: "/languages", query: {} },
  { method: "GET", template: "/catalog", query: { country: COUNTRY, language: LANG } },
  {
    method: "GET",
    template: "/sites",
    query: { country: COUNTRY, q: FREE, source: SOURCE, limit: INT, offset: INT },
  },
  {
    method: "GET",
    template: "/sites/{}/measurements",
    query: {
      parameter: FREE,
      date_from: ISO_DATE,
      date_to: ISO_DATE,
      limit: INT,
      group: /^(water-chemistry|solids-turbidity|organic-matter)$/,
      resolution: /^(annual|monthly)$/,
    },
  },
  { method: "GET", template: "/sites/{}/weather", query: { date_from: ISO_DATE, date_to: ISO_DATE, language: LANG } },
  { method: "GET", template: "/sites/{}/discharge", query: { date_from: ISO_DATE, date_to: ISO_DATE, language: LANG } },
  {
    method: "GET",
    template: "/sites/{}/species",
    query: { group: FREE, date_from: ISO_DATE, date_to: ISO_DATE, limit: INT, language: LANG },
  },
  { method: "GET", template: "/indices/{}", query: {} },
  {
    method: "GET",
    template: "/bathing-waters",
    query: { country: COUNTRY, q: FREE, type: FREE, quality: FREE, limit: INT, offset: INT },
  },
  {
    method: "GET",
    template: "/bathing-waters/{}/samples",
    query: { date_from: ISO_DATE, date_to: ISO_DATE, season: INT, limit: INT, order: /^(asc|desc)$/, language: LANG },
  },
  { method: "GET", template: "/qc/report", query: {} },
  {
    method: "GET",
    template: "/reliability/campaign",
    query: { seed: INT, observer_count: INT, specimens_per_site: INT, annotators_per_specimen: INT },
  },
  { method: "GET", template: "/review/queue", query: {} },
  { method: "GET", template: "/risk/{}", query: {} },
  { method: "POST", template: "/chat", query: {} },
];

export interface Match {
  rule: Rule;
  /** The backend path with the validated segments, never containing anything unvalidated. */
  path: string;
  /** The filtered query string (possibly empty), already encoded. */
  search: string;
}

function matchTemplate(template: string, segments: string[]): string[] | null {
  const parts = template.split("/").filter(Boolean);
  if (parts.length !== segments.length) return null;
  const out: string[] = [];
  for (let i = 0; i < parts.length; i += 1) {
    const part = parts[i]!;
    const seg = segments[i]!;
    if (part === "{}") {
      if (!SEGMENT.test(seg) || seg === "." || seg === "..") return null;
      out.push(encodeURIComponent(seg));
    } else if (part === seg) {
      out.push(part);
    } else {
      return null;
    }
  }
  return out;
}

/** Resolve a request to an allowed backend call, or null (answer 404, no backend call). */
export function matchRoute(method: string, segments: string[], params: URLSearchParams): Match | null {
  for (const rule of RULES) {
    if (rule.method !== method) continue;
    const out = matchTemplate(rule.template, segments);
    if (!out) continue;
    const kept = new URLSearchParams();
    for (const [name, value] of params) {
      const pattern = rule.query[name];
      if (pattern?.test(value)) kept.append(name, value);
    }
    const search = kept.toString();
    return { rule, path: "/" + out.join("/"), search: search ? `?${search}` : "" };
  }
  return null;
}
