"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import type { Schema, SitesResponse } from "@/lib/api";
import { useApp, type PickedPlace } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { msg, useT } from "@/lib/i18n";
import { finderKinds, type PlaceKind } from "@/lib/places";
import { bathingDetail, siteDetail } from "./place-detail";

const KIND_NAME: Record<PlaceKind, string> = { site: msg("Site"), "bathing-water": msg("Bathing water") };

/** Search and pick a place from the sidebar, under the country selector. The pick is shared with the map and the chat. */
export default function PlaceFinder() {
  const app = useApp();
  const t = useT();
  const pathname = usePathname();
  const { country } = useSettings();
  const kinds = finderKinds(pathname);
  const [q, setQ] = useState("");
  const query = q.trim() || undefined;

  const sites = useApi<SitesResponse>(kinds.includes("site") ? "/sites" : null, { country, q: query, limit: 30 });
  const waters = useApi<Schema<"BathingWatersResponse">>(kinds.includes("bathing-water") ? "/bathing-waters" : null, { country, q: query, limit: 30 });

  if (kinds.length === 0) return null;

  const only = kinds[0];
  const label = kinds.length === 1 && only ? t(KIND_NAME[only]) : t("Place");
  const picked = app.place && app.place.country === country && kinds.includes(app.place.kind) ? app.place : null;
  const wanted = [kinds.includes("site") ? sites : null, kinds.includes("bathing-water") ? waters : null].filter((s) => s !== null);
  const loading = wanted.some((s) => s.status === "loading");
  const failed = wanted.find((s) => s.status === "error");

  const places: PickedPlace[] = [];
  if (kinds.includes("site") && sites.status === "ready") {
    for (const s of sites.data.sites) {
      places.push({ kind: "site", id: s.id, name: s.name, country: s.limit_country ?? country, latitude: s.latitude, longitude: s.longitude, detail: siteDetail(s.ui_status, t) });
    }
  }
  if (kinds.includes("bathing-water") && waters.status === "ready") {
    for (const b of waters.data.bathing_waters) {
      places.push({ kind: "bathing-water", id: b.id, name: b.name, country: b.country, latitude: b.latitude ?? null, longitude: b.longitude ?? null, detail: bathingDetail(b.latest_quality, b.latest_season, t) });
    }
  }
  const showList = !picked || query !== undefined;

  return (
    <div data-testid="place-finder">
      <label htmlFor="place-search" className="mb-1 block text-xs font-medium uppercase tracking-wide text-muted">
        {label}
      </label>
      <input
        id="place-search"
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value.slice(0, 64))}
        placeholder={t("Search by name")}
        autoComplete="off"
        className="w-full rounded-lg border border-line bg-surface px-3 py-2"
      />
      {picked ? (
        <div data-testid="picked-place" className="mt-1 flex items-center justify-between gap-2 rounded-lg bg-line/40 px-3 py-1.5 text-sm">
          <span className="min-w-0 truncate font-medium">{picked.name}</span>
          <button type="button" onClick={() => app.setPlace(null)} className="shrink-0 text-xs text-muted underline">
            {t("Clear")}
          </button>
        </div>
      ) : null}
      {showList ? (
        <div className="mt-1">
          {loading ? (
            <p role="status" className="px-1 text-xs text-muted">{t("Loading places")}</p>
          ) : failed ? (
            <p role="alert" className="px-1 text-xs text-bad-ink">{t("Places could not be loaded.")}</p>
          ) : places.length === 0 ? (
            <p data-testid="no-places" className="px-1 text-xs text-muted">{t("No places match.")}</p>
          ) : (
            <ul aria-label={t("Places")} className="max-h-40 divide-y divide-line overflow-y-auto rounded-lg border border-line bg-surface text-sm">
              {places.map((p) => (
                <li key={`${p.kind}:${p.id}`}>
                  <button
                    type="button"
                    aria-pressed={picked?.id === p.id}
                    onClick={() => {
                      app.setPlace(p);
                      setQ("");
                      app.setSidebarOpen(false);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-line/40"
                  >
                    <span className="min-w-0 flex-1 truncate">{p.name}</span>
                    {kinds.length > 1 ? <span className="shrink-0 text-xs text-muted">{t(KIND_NAME[p.kind])}</span> : null}
                    {p.latitude === null ? <span className="shrink-0 text-xs text-muted">{t("no location")}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
