/** Credits and licence notes shown in Settings > About and attributions. Plain text and links only. */

export interface Attribution {
  name: string;
  credit: string;
  note: string;
  href: string;
}

export const ATTRIBUTIONS: readonly Attribution[] = [
  {
    name: "European Environment Agency (EEA)",
    credit: "Waterbase 2026, Bathing Water Directive status and bathing-water monitoring results (Discodata).",
    note: "EEA data are published under CC BY 4.0 (EEA legal notice). The attribution string returned with each response is shown next to the data.",
    href: "https://www.eea.europa.eu/",
  },
  {
    name: "Open-Meteo",
    credit: "Weather data by Open-Meteo.com.",
    note: "Modelled ERA5 reanalysis and GloFAS river discharge aggregated to months; not measurements at the site. Non-commercial use only. The exact GloFAS credit wording is still to be confirmed.",
    href: "https://open-meteo.com/",
  },
  {
    name: "GBIF",
    credit: "Species occurrence records from the Global Biodiversity Information Facility.",
    note: "Each record shows its licence, dataset and citation as returned; non-commercial records are marked. Opportunistic records, not monitoring.",
    href: "https://www.gbif.org/",
  },
  {
    name: "OpenStreetMap",
    credit: "Map data © OpenStreetMap contributors.",
    note: "Map tiles are loaded from OpenStreetMap by your browser while the map pane is open. Data under the Open Database Licence.",
    href: "https://www.openstreetmap.org/copyright",
  },
  {
    name: "HL7 Europe sandbox",
    credit: "Public OneAquaHealth sandbox and implementation guide of HL7 Europe, used for the IEEE OneAquaHealth Global Hackathon 2026.",
    note: "Sandbox observations are shown as real sandbox data; reference values are screening aids, not legal limits.",
    href: "https://github.com/hl7-eu/oah",
  },
];

export const ABOUT_TEXT =
  "OneAquaHealth shows water-quality data with their origin and method next to every answer. Real, externally modelled and synthetic data are always labelled and never mixed silently. Results are screening against reference values, not compliance, and the app makes no health or safety statement.";
