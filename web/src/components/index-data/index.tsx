"use client";

import { usePlace } from "./shared";
import { SitePicker } from "./site-picker";
import { BathingClassesPanel, BathingSamplesPanel } from "./bathing-panels";
import { DischargePanel, SpeciesPanel, WeatherPanel } from "./external-panels";
import { DataQualityPanel, MeasurementsPanel, WaterQualityPanel } from "./water-panels";
import { PickPrompt } from "./shared";

export { SourceFooter } from "./shared";

const SITE_INDICES = new Set(["water-quality", "water-parameters", "solids-turbidity", "organic-matter", "weather", "river-discharge", "species-nearby"]);
const GROUP_OF: Record<string, string | undefined> = { "solids-turbidity": "solids-turbidity", "organic-matter": "organic-matter", "water-parameters": undefined };

/** The data behind one index (the "Data" tab): the route of the catalogue, rendered with its origin and notices. */
export default function IndexData({ indexId }: { indexId: string }) {
  const [place] = usePlace("site");
  const needsSite = SITE_INDICES.has(indexId);
  return (
    <div className="space-y-4" data-testid="index-data">
      {needsSite ? <SitePicker /> : null}
      {needsSite && !place ? <PickPrompt /> : null}
      {indexId === "water-quality" && place ? <WaterQualityPanel siteId={place.id} /> : null}
      {(indexId === "water-parameters" || indexId === "solids-turbidity" || indexId === "organic-matter") && place ? <MeasurementsPanel siteId={place.id} group={GROUP_OF[indexId]} /> : null}
      {indexId === "weather" && place ? <WeatherPanel key={place.id} siteId={place.id} /> : null}
      {indexId === "river-discharge" && place ? <DischargePanel key={place.id} siteId={place.id} /> : null}
      {indexId === "species-nearby" && place ? <SpeciesPanel siteId={place.id} /> : null}
      {indexId === "bathing-classes" ? <BathingClassesPanel /> : null}
      {indexId === "bathing-samples" ? <BathingSamplesPanel /> : null}
      {indexId === "data-quality" ? <DataQualityPanel /> : null}
    </div>
  );
}

