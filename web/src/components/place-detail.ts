import { translateEnglish, type TFunction } from "@/lib/i18n-core";

/** The one-line description of a picked place (shown on the map card). Built in the language selected when it is picked. */

export function siteDetail(uiStatus: string, t: TFunction = translateEnglish): string {
  return t("Index class (screening): {status}", { status: t(uiStatusLabel(uiStatus)) });
}

export function bathingDetail(quality: string | null | undefined, season: number | string | null | undefined, t: TFunction = translateEnglish): string {
  const base = t("Latest classification: {value}", { value: quality ?? t("n/a") });
  return season ? `${base} (${season})` : base;
}

function uiStatusLabel(status: string): string {
  const label = status.charAt(0).toUpperCase() + status.slice(1);
  return label;
}
