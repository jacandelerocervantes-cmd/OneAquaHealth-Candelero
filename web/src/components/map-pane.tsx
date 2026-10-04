"use client";

import "leaflet/dist/leaflet.css";
import type { Map as LeafletMap, LayerGroup } from "leaflet";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";
import type { Schema, SitesResponse } from "@/lib/api";
import { useApp, type PickedPlace } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { translateEnglish, useT, type TFunction } from "@/lib/i18n";
import { indexIdFromPath, mapKinds } from "@/lib/places";
import { bathingDetail, siteDetail } from "./place-detail";
import { EmptyState, ErrorBox, Loading, Notice } from "./ui";

/** OpenStreetMap tiles: required attribution, no tile proxy, no prefetch. */
export const OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';

export { indexIdFromPath };

interface MapPlace extends PickedPlace {
  color: string;
  tag: string;
}

const STATUS_COLOR: Record<string, string> = { good: "#15803d", moderate: "#b45309", poor: "#b91c1c", unavailable: "#6b7280" };

export function sitesToPlaces(data: SitesResponse, country: string, t: TFunction = translateEnglish): MapPlace[] {
  return data.sites.map((s: Schema<"Site">) => ({
    kind: "site" as const,
    id: s.id,
    name: s.name,
    country: s.limit_country ?? country,
    latitude: s.latitude,
    longitude: s.longitude,
    detail: siteDetail(s.ui_status, t),
    color: STATUS_COLOR[s.ui_status] ?? "#6b7280",
    tag: s.ui_status,
  }));
}

export function bathingToPlaces(data: Schema<"BathingWatersResponse">, t: TFunction = translateEnglish): MapPlace[] {
  return data.bathing_waters.map((b) => ({
    kind: "bathing-water" as const,
    id: b.id,
    name: b.name,
    country: b.country,
    latitude: b.latitude ?? null,
    longitude: b.longitude ?? null,
    detail: bathingDetail(b.latest_quality, b.latest_season, t),
    color: "#0b6e8a",
    tag: b.latest_quality ?? "n/a",
  }));
}

function PlaceList({ places, selectedId, onPick }: { places: MapPlace[]; selectedId: string | null; onPick: (p: MapPlace) => void }) {
  const t = useT();
  return (
    <ul className="max-h-40 divide-y divide-line overflow-y-auto rounded-lg border border-line bg-surface text-sm" aria-label={t("Places")}>
      {places.map((p) => (
        <li key={p.id}>
          <button
            type="button"
            onClick={() => onPick(p)}
            aria-pressed={p.id === selectedId}
            className={`flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-sidebar ${p.id === selectedId ? "bg-sidebar" : ""}`}
          >
            <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: p.color }} />
            <span className="min-w-0 flex-1 truncate">{p.name}</span>
            {p.latitude === null ? <span className="text-xs text-muted">{t("no location")}</span> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

function LeafletCanvas({ places, selectedId, onPick, tall }: { places: MapPlace[]; selectedId: string | null; onPick: (p: MapPlace) => void; tall: boolean }) {
  const t = useT();
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const layerRef = useRef<LayerGroup | null>(null);
  const leafletRef = useRef<typeof import("leaflet") | null>(null);

  useEffect(() => {
    let cancelled = false;
    void import("leaflet").then((mod) => {
      const L = mod.default ?? mod;
      if (cancelled || !container.current || mapRef.current) return;
      leafletRef.current = L;
      const map = L.map(container.current, { zoomControl: true, worldCopyJump: false }).setView([48, 14], 4);
      L.tileLayer(OSM_TILES, { attribution: OSM_ATTRIBUTION, maxZoom: 18, keepBuffer: 1, updateWhenIdle: true }).addTo(map);
      layerRef.current = L.layerGroup().addTo(map);
      mapRef.current = map;
      window.setTimeout(() => map.invalidateSize(), 0);
      redraw();
    });
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
    // The map is created once; markers are redrawn by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function redraw() {
    const L = leafletRef.current;
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!L || !map || !layer) return;
    layer.clearLayers();
    const points: [number, number][] = [];
    for (const p of places) {
      if (p.latitude === null || p.longitude === null) continue;
      const selected = p.id === selectedId;
      const marker = L.circleMarker([p.latitude, p.longitude], {
        radius: selected ? 11 : 8,
        color: selected ? "#111827" : "#ffffff",
        weight: selected ? 3 : 1.5,
        fillColor: p.color,
        fillOpacity: 0.85,
      });
      // Names are data: the tooltip gets a text node, never an HTML string.
      const tip = document.createElement("span");
      tip.textContent = p.name;
      marker.bindTooltip(tip);
      marker.on("click", () => onPick(p));
      marker.addTo(layer);
      points.push([p.latitude, p.longitude]);
    }
    // A picked place is shown close up; with nothing picked the map fits every place of the screen.
    const chosen = places.find((p) => p.id === selectedId && p.latitude !== null && p.longitude !== null);
    if (chosen && chosen.latitude !== null && chosen.longitude !== null) map.setView([chosen.latitude, chosen.longitude], Math.max(map.getZoom(), 10));
    else if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 9 });
  }

  useEffect(redraw, [places, selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // The pane can be widened or made taller: Leaflet must re-measure its container, then fit the places again.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      mapRef.current?.invalidateSize();
      redraw();
    }, 50);
    return () => window.clearTimeout(timer);
  }, [tall]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={container}
      data-testid="map-canvas"
      role="application"
      aria-label={t("Map of places")}
      className={`w-full rounded-lg border border-line ${tall ? "h-[60vh] min-h-72" : "h-64"}`}
    />
  );
}

export default function MapPane({ expanded = false, onToggleExpanded }: { expanded?: boolean; onToggleExpanded?: () => void }) {
  const app = useApp();
  const t = useT();
  const pathname = usePathname();
  const settings = useSettings();
  // The home page ("New question") shows everything the country holds; an index shows its own places only.
  const kinds = mapKinds(pathname);
  const wantSites = kinds.includes("site");
  const wantWaters = kinds.includes("bathing-water");
  const sites = useApi<SitesResponse>(wantSites ? "/sites" : null, { country: settings.country, limit: 200 });
  const waters = useApi<Schema<"BathingWatersResponse">>(wantWaters ? "/bathing-waters" : null, { country: settings.country, limit: 200 });
  const wanted = [wantSites ? sites : null, wantWaters ? waters : null].filter((s) => s !== null);
  const failed = wanted.find((s) => s.status === "error");
  const state: { status: "loading" | "ready" | "error"; error?: unknown; reload: () => void } = failed
    ? { status: "error", error: failed.status === "error" ? failed.error : undefined, reload: () => wanted.forEach((s) => s.reload()) }
    : wanted.some((s) => s.status === "loading")
      ? { status: "loading", reload: () => undefined }
      : { status: "ready", reload: () => undefined };
  const bathing = wantWaters && !wantSites;

  const places = useMemo<MapPlace[]>(() => {
    const out: MapPlace[] = [];
    if (wantSites && sites.status === "ready") out.push(...sitesToPlaces(sites.data, settings.country, t));
    if (wantWaters && waters.status === "ready") out.push(...bathingToPlaces(waters.data, t));
    return out;
  }, [sites, waters, wantSites, wantWaters, settings.country, t]);

  const selectedId = app.place?.id ?? null;
  const pick = (p: MapPlace) => app.setPlace({ kind: p.kind, id: p.id, name: p.name, country: p.country, latitude: p.latitude, longitude: p.longitude, detail: p.detail });

  return (
    <aside data-testid="map-pane" aria-label={t("Map")} className="flex h-full w-full flex-col gap-3 overflow-y-auto border-l border-line bg-canvas p-3">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t("Map")}</h2>
        <div className="flex items-center gap-2">
          {onToggleExpanded ? (
            <button
              type="button"
              data-testid="map-expand"
              onClick={onToggleExpanded}
              aria-pressed={expanded}
              className="hidden rounded-md border border-line px-2 py-1 text-sm hover:bg-sidebar md:inline-block"
            >
              {expanded ? t("Shrink") : t("Expand")}
            </button>
          ) : null}
          <button type="button" onClick={() => app.setMapOpen(false)} className="rounded-md border border-line px-2 py-1 text-sm hover:bg-sidebar" aria-label={t("Close map")}>
            {t("Close")}
          </button>
        </div>
      </div>
      <p className="text-xs text-muted">
        {wantSites && wantWaters
          ? t("Sites and bathing waters of the selected country. Selecting one does not start a question.")
          : bathing
            ? t("Bathing waters of the selected country. Selecting one does not start a question.")
            : t("Sites of the selected country. Selecting one does not start a question.")}
      </p>
      {state.status === "loading" ? <Loading /> : null}
      {state.status === "error" ? <ErrorBox error={state.error} onRetry={state.reload} /> : null}
      {/* Both kinds on one map: bathing waters are blue, sites carry their index class colour. */}
      {state.status === "ready" && places.length === 0 ? <EmptyState title={t("No places to show")}>{t("This country has no located places for this index.")}</EmptyState> : null}
      {state.status === "ready" && places.length > 0 ? (
        <>
          <LeafletCanvas places={places} selectedId={selectedId} onPick={pick} tall={expanded} />
          <PlaceList places={places} selectedId={selectedId} onPick={pick} />
        </>
      ) : null}
      {app.place ? (
        <section data-testid="place-card" className="space-y-2 rounded-lg border border-line bg-surface p-3 text-sm">
          <h3 className="font-medium">{app.place.name}</h3>
          <p className="text-xs text-muted">{app.place.kind === "site" ? t("Site") : t("Bathing water")} · {app.place.id}</p>
          {app.place.detail ? <p>{app.place.detail}</p> : null}
          <p className="text-xs text-muted">{t("The place is passed to the next question as context. Remove it above the input box.")}</p>
          <button type="button" onClick={() => app.setPlace(null)} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-sidebar">
            {t("Clear selection")}
          </button>
        </section>
      ) : null}
      <Notice tone="info">{t("Map data © OpenStreetMap contributors. Located places only.")}</Notice>
    </aside>
  );
}
