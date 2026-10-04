import type { Schema } from "@/lib/api";
import { COUNTRY_NAMES, HAS_BATHING, MOCK_AS_OF, MOCK_NOTICE, freshness, stores, type CountryCode } from "./data";

type Index = Schema<"CatalogIndex">;
type FamilyId = Schema<"CatalogFamily">["id"];

interface Def {
  id: Index["id"];
  family: FamilyId;
  familyTitle: string;
  title: string;
  kind: Index["origin_kind"];
  origins: string[];
  routes: string[];
  chat: Index["chat_index"];
  applies: (c: CountryCode) => boolean;
  reason?: { code: NonNullable<Index["reason_code"]>; text: string };
}

const noBathing = { code: "no-data-for-country" as const, text: "No data for this country in the service." };
const always = () => true;

const DEFS: Def[] = [
  { id: "water-quality", family: "water", familyTitle: "Water", title: "Water quality", kind: "real", origins: ["real-sandbox"], routes: ["/sites", "/indices/{location_id}"], chat: "water-quality", applies: always },
  { id: "water-parameters", family: "water", familyTitle: "Water", title: "Water parameters", kind: "real", origins: ["real-sandbox", "real-eea-waterbase"], routes: ["/sites", "/sites/{location_id}/measurements"], chat: "water-parameters", applies: always },
  { id: "solids-turbidity", family: "water", familyTitle: "Water", title: "Solids and turbidity", kind: "real", origins: ["real-eea-waterbase"], routes: ["/sites/{location_id}/measurements"], chat: "water-parameters", applies: always },
  // Mock rule: Norway has no organic-matter determinand, so the sidebar hides this index there.
  { id: "organic-matter", family: "water", familyTitle: "Water", title: "Organic matter", kind: "real", origins: ["real-eea-waterbase"], routes: ["/sites/{location_id}/measurements"], chat: "water-parameters", applies: (c) => c !== "NO", reason: { code: "no-data-for-country", text: "No organic-matter determinand for this country in the service." } },
  { id: "bathing-classes", family: "microbiology", familyTitle: "Microbiology", title: "Bathing classes", kind: "real", origins: ["real-eea-bathing-water"], routes: ["/bathing-waters", "/bathing-waters/{bw_id}"], chat: "microbiology", applies: (c) => HAS_BATHING[c], reason: noBathing },
  { id: "bathing-samples", family: "microbiology", familyTitle: "Microbiology", title: "E. coli and enterococci", kind: "real", origins: ["real-eea-bathing-samples"], routes: ["/bathing-waters/{bw_id}/samples"], chat: "microbiology", applies: (c) => HAS_BATHING[c], reason: noBathing },
  { id: "weather", family: "context", familyTitle: "Context", title: "Weather", kind: "external", origins: ["external-open-meteo"], routes: ["/sites/{site_id}/weather"], chat: null, applies: always },
  { id: "river-discharge", family: "context", familyTitle: "Context", title: "River discharge", kind: "external", origins: ["external-open-meteo"], routes: ["/sites/{site_id}/discharge"], chat: null, applies: always },
  { id: "species-nearby", family: "context", familyTitle: "Context", title: "Species nearby", kind: "external", origins: ["external-gbif"], routes: ["/sites/{site_id}/species"], chat: null, applies: always },
  { id: "data-quality", family: "data", familyTitle: "Data", title: "Data quality", kind: "real", origins: ["real-sandbox"], routes: ["/qc/report"], chat: "data-quality", applies: always },
  { id: "citizen-science", family: "synthetic-labs", familyTitle: "Synthetic labs", title: "Citizen science", kind: "synthetic", origins: ["synthetic"], routes: ["/reliability/campaign"], chat: null, applies: always },
  { id: "review-queue", family: "synthetic-labs", familyTitle: "Synthetic labs", title: "Review queue (read-only)", kind: "synthetic", origins: ["synthetic"], routes: ["/review/queue"], chat: null, applies: always },
  { id: "river-risk", family: "synthetic-labs", familyTitle: "Synthetic labs", title: "River risk", kind: "synthetic", origins: ["synthetic"], routes: ["/risk/{site_id}"], chat: null, applies: always },
];

const FAMILY_ORDER: FamilyId[] = ["water", "microbiology", "context", "data", "synthetic-labs"];

export function buildCatalog(country: CountryCode, language: string): Schema<"CatalogResponse"> {
  const families = FAMILY_ORDER.map((id) => {
    const defs = DEFS.filter((d) => d.family === id);
    return {
      id,
      title: defs[0]?.familyTitle ?? id,
      indices: defs.map<Index>((d) => {
        const applies = d.applies(country);
        return {
          id: d.id,
          family_id: d.family,
          family_title: d.familyTitle,
          title: d.title,
          origin_kind: d.kind,
          origins: d.origins,
          applies,
          ...(applies ? {} : { reason_code: d.reason?.code ?? "no-data-for-country", reason: d.reason?.text ?? "No data." }),
          routes: d.routes,
          chat_index: d.chat,
        };
      }),
    };
  });
  return {
    origin: "synthetic",
    data_freshness: { ...freshness, as_of: MOCK_AS_OF },
    interpretation_notice: MOCK_NOTICE,
    language,
    country,
    country_name: COUNTRY_NAMES[country],
    families,
    applicable_count: families.flatMap((f) => f.indices).filter((i) => i.applies).length,
    stores: {
      sandbox: "available",
      waterbase: stores.waterbase,
      bathing_water: stores.bathing_water,
      bathing_samples: stores.bathing_samples,
      external: { enabled: true, weather: true, discharge: true, species: true },
    },
  };
}
