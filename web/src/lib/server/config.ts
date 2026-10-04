/**
 * Server-only configuration. None of these variables is ever sent to the browser
 * (they carry no public-variable prefix); the access key is read here and nowhere else.
 */

export type DataMode = "mock" | "real";

export interface ServerConfig {
  mode: DataMode;
  backendUrl: string | null;
  apiKey: string | null;
}

/**
 * OAH_DATA_MODE=mock serves schema-conformant simulated data (the default, so a fresh
 * checkout never calls a backend by accident); OAH_DATA_MODE=real forwards the allow-listed
 * routes to OAH_BACKEND_URL with the key OAH_API_KEY.
 */
export function readConfig(env: Record<string, string | undefined> = process.env): ServerConfig {
  const requested = (env.OAH_DATA_MODE ?? "mock").trim().toLowerCase();
  const mode: DataMode = requested === "real" ? "real" : "mock";
  const backendUrl = normaliseBackendUrl(env.OAH_BACKEND_URL);
  const apiKey = env.OAH_API_KEY?.trim() ? env.OAH_API_KEY.trim() : null;
  return { mode, backendUrl, apiKey };
}

/** Accept only an http(s) origin without credentials, query or fragment; strip trailing slashes. */
export function normaliseBackendUrl(value: string | undefined): string | null {
  if (!value?.trim()) return null;
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  if (url.username || url.password || url.search || url.hash) return null;
  return url.origin + url.pathname.replace(/\/+$/, "");
}

/** What a client may learn about the server mode: never the URL or the key. */
export function publicStatus(config: ServerConfig): { mode: DataMode; configured: boolean } {
  return { mode: config.mode, configured: config.mode === "mock" || Boolean(config.backendUrl && config.apiKey) };
}
