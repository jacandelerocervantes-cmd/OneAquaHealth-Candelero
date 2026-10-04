import type { ChatRequest } from "@/lib/api";
import { asCountry, err, ok, type MockResult } from "./common";
import { buildCatalog } from "./catalog";
import { mockCountries, mockLanguages } from "./data";
import { bathingList, bathingSamples } from "./routes/bathing";
import { chat } from "./routes/chat";
import { discharge, species, weather } from "./routes/external";
import { qc, reliability, reviewQueue, risk } from "./routes/labs";
import { fhir, indexFor, measurements, sites } from "./routes/sites";

export type { MockResult } from "./common";
export { chat };

export function mockRoute(method: string, path: string, params: URLSearchParams, body: unknown): MockResult {
  const seg = path.split("/").filter(Boolean).map(decodeURIComponent);
  const [a, b, c] = seg;
  if (method === "POST" && a === "chat") return chat(body as ChatRequest);
  if (a === "countries") return ok(mockCountries);
  if (a === "languages") return ok(mockLanguages);
  if (a === "catalog") {
    const country = asCountry(params.get("country"));
    return country ? ok(buildCatalog(country, params.get("language") ?? "en")) : err(422, "Unknown country; known codes: GR, IT, NO.");
  }
  if (a === "sites" && !b) return sites(params);
  if (a === "sites" && b && c === "measurements") return measurements(b, params);
  if (a === "sites" && b && c === "fhir") return fhir(b, params);
  if (a === "sites" && b && c === "weather") return weather(b, params);
  if (a === "sites" && b && c === "discharge") return discharge(b, params);
  if (a === "sites" && b && c === "species") return species(b);
  if (a === "indices" && b) return indexFor(b);
  if (a === "bathing-waters" && !b) return bathingList(params);
  if (a === "bathing-waters" && b && c === "samples") return bathingSamples(b);
  if (a === "qc") return qc();
  if (a === "reliability") return reliability(params);
  if (a === "review") return reviewQueue();
  if (a === "risk" && b) return risk(b);
  return err(404, "Not Found");
}

