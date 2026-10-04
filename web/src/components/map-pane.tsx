"use client";

import "leaflet/dist/leaflet.css";
import type { Map as LeafletMap, LayerGroup } from "leaflet";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";
import type { Schema, SitesResponse } from "@/lib/api";
import { useApp, type PickedPlace } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { EmptyState, ErrorBox, Loading, Notice } from "./ui";

/** OpenStreetMap tiles: required attribution, no tile proxy, no prefetch. */
export const OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';

const BATHING_INDICES = new Set(["bathing-classes", "bathing-samples"]);

export function indexIdFromPath(pathname: string): string | null {
  const m = /^\/(?:i|labs)\/([^/]+)/.exec(pathname);
  return m?.[1] ?? null;
}

interface MapPlace extends PickedPlace {
  color: string;
  tag: string;
}

const STATUS_COLOR: Record<string, string> = { good: "#15803d", moderate: "#b45309", poor: "#b91c1c", unavailable: "#6b7280" };

export function sitesToPlaces(data: SitesResponse, country: string): MapPlace[] {
  return data.sites.map((s: Schema<"Site">) => ({
    kind: "site" as const,
    id: s.id,
    name: s.name,
    country: s.limit_country ?? country,
    latitude: s.latitude,
    longitude: s.longitude,
    detail: `Index class (screening): ${s.ui_status}`,
    color: STATUS_COLOR[s.ui_status] ?? "#6b7280",
    tag: s.ui_status,
  }));
}

export function bathingToPlaces(data: Schema<"BathingWatersResponse">): MapPlace[] {
  return data.bathing_waters.map((b) => ({
    kind: "bathing-water" as const,
    id: b.id,
    name: b.name,
    country: b.country,
    latitude: b.latitude ?? null,
    longitude: b.longitude ?? null,
    detail: `Latest classification: ${b.latest_quality ?? "n/a"}${b.latest_season ? ` (${b.latest_season})` : ""}`,
    color: "#0b6e8a",
    tag: b.latest_quality ?? "n/a",
  }));
}

function PlaceList({ places, selectedId, onPick }: { places: MapPlace[]; selectedId: string | null; onPick: (p: MapPlace) => void }) {
  return (
    <ul className="max-h-40 divide-y divide-line overflow-y-auto rounded-lg border border-line bg-surface text-sm" aria-label="Places">
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
            {p.latitude === null ? <span className="text-xs text-muted">no location</span> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

function LeafletCanvas({ places, selectedId, onPick, tall }: { places: MapPlace[]; selectedId: string | null; onPick: (p: MapPlace) => void; tall: boolean }) {
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
    if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 9 });
  }

  useEffect(redraw, [places, selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // The pane can be widened or made taller: Leaflet must re-measure its container, then fit the places again.
  useEffect(() => {
    const t = window.setTimeout(() => {
      mapRef.current?.invalidateSize();
      redraw();
    }, 50);
    return () => window.clearTimeout(t);
  }, [tall]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={container}
      data-testid="map-canvas"
      role="application"
      aria-label="Map of places"
      className={`w-full rounded-lg border border-line ${tall ? "h-[60vh] min-h-72" : "h-64"}`}
    />
  );
}

export default function MapPane({ expanded = false, onToggleExpanded }: { expanded?: boolean; onToggleExpanded?: () => void }) {
  const app = useApp();
  const pathname = usePathname();
  const settings = useSettings();
  const indexId = indexIdFromPath(pathname);
  const bathing = indexId ? BATHING_INDICES.has(indexId) : false;
  const sites = useApi<SitesResponse>(bathing ? null : "/sites", { country: settings.country, limit: 200 });
  const waters = useApi<Schema<"BathingWatersResponse">>(bathing ? "/bathing-waters" : null, { country: settings.country, limit: 200 });
  const state = bathing ? waters : sites;

  const places = useMemo<MapPlace[]>(() => {
    if (state.status !== "ready") return [];
    return bathing ? bathingToPlaces(state.data as Schema<"BathingWatersResponse">) : sitesToPlaces(state.data as SitesResponse, settings.country);
  }, [state, bathing, settings.country]);

  const selectedId = app.place?.id ?? null;
  const pick = (p: MapPlace) => app.setPlace({ kind: p.kind, id: p.id, name: p.name, country: p.country, latitude: p.latitude, longitude: p.longitude, detail: p.detail });

  return (
    <aside data-testid="map-pane" aria-label="Map" className="flex h-full w-full flex-col gap-3 overflow-y-auto border-l border-line bg-canvas p-3">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">Map</h2>
        <div className="flex items-center gap-2">
          {onToggleExpanded ? (
            <button
              type="button"
              data-testid="map-expand"
              onClick={onToggleExpanded}
              aria-pressed={expanded}
              className="hidden rounded-md border border-line px-2 py-1 text-sm hover:bg-sidebar md:inline-block"
            >
              {expanded ? "Shrink" : "Expand"}
            </button>
          ) : null}
          <button type="button" onClick={() => app.setMapOpen(false)} className="rounded-md border border-line px-2 py-1 text-sm hover:bg-sidebar" aria-label="Close map">
            Close
          </button>
        </div>
      </div>
      <p className="text-xs text-muted">{bathing ? "Bathing waters" : "Sites"} of the selected country. Selecting one does not start a question.</p>
      {state.status === "loading" ? <Loading /> : null}
      {state.status === "error" ? <ErrorBox error={state.error} onRetry={state.reload} /> : null}
      {state.status === "ready" && places.length === 0 ? <EmptyState title="No places to show">This country has no located places for this index.</EmptyState> : null}
      {state.status === "ready" && places.length > 0 ? (
        <>
          <LeafletCanvas places={places} selectedId={selectedId} onPick={pick} tall={expanded} />
          <PlaceList places={places} selectedId={selectedId} onPick={pick} />
        </>
      ) : null}
      {app.place ? (
        <section data-testid="place-card" className="space-y-2 rounded-lg border border-line bg-surface p-3 text-sm">
          <h3 className="font-medium">{app.place.name}</h3>
          <p className="text-xs text-muted">{app.place.kind === "site" ? "Site" : "Bathing water"} · {app.place.id}</p>
          {app.place.detail ? <p>{app.place.detail}</p> : null}
          <p className="text-xs text-muted">The place is passed to the next question as context. Remove it above the input box.</p>
          <button type="button" onClick={() => app.setPlace(null)} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-sidebar">
            Clear selection
          </button>
        </section>
      ) : null}
      <Notice tone="info">Map data © OpenStreetMap contributors. Located places only.</Notice>
    </aside>
  );
}
