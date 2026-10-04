// No X-API-Key is sent: a shared secret in a browser bundle is not a secret once it reaches the
// client. This only works against a backend started with OAH_INSECURE_NO_AUTH=1 (local/demo only);
// see "UI authentication is undecided" in docs/architecture.md before pointing this at anything else.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}) as { detail?: string });
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

export type UiStatus = "good" | "moderate" | "poor" | "unavailable";

export interface Site {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  status: "evaluated" | "skipped";
  ccme_wqi: number | null;
  ccme_class: string | null;
  ui_status: UiStatus;
  confidence?: string;
  reason?: string;
}

export interface SitesResponse {
  origin: string;
  sites: Site[];
}

export function getSites(): Promise<SitesResponse> {
  return request<SitesResponse>("/sites");
}
