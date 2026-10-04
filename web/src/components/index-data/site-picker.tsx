"use client";

import { useState } from "react";
import type { SitesResponse } from "@/lib/api";
import { type PickedPlace } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { usePlace } from "./shared";

export function SitePicker({ onPicked }: { onPicked?: (p: PickedPlace | null) => void }) {
  const { country } = useSettings();
  const [place, setPlace] = usePlace("site");
  const [q, setQ] = useState("");
  const sites = useApi<SitesResponse>("/sites", { country, q: q.trim() || undefined, limit: 200 });
  const pick = (p: PickedPlace | null) => {
    setPlace(p);
    onPicked?.(p);
  };
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div>
        <label htmlFor="site-search" className="block text-xs text-muted">Search sites</label>
        <input id="site-search" value={q} onChange={(e) => setQ(e.target.value.slice(0, 64))} className="rounded-lg border border-line bg-surface px-3 py-1.5" placeholder="Name contains" />
      </div>
      <div className="min-w-[14rem] flex-1">
        <label htmlFor="site-select" className="block text-xs text-muted">Site</label>
        {sites.status === "loading" ? (
          <p className="py-1.5 text-sm text-muted" role="status">Loading sites</p>
        ) : sites.status === "error" ? (
          <div className="flex items-center gap-2 py-1 text-sm text-bad-ink" role="alert">
            Sites could not be loaded.
            <button type="button" onClick={sites.reload} className="rounded border border-line px-2 py-0.5 text-ink">Retry</button>
          </div>
        ) : sites.data.sites.length === 0 ? (
          <p className="py-1.5 text-sm text-muted" data-testid="no-sites">No sites match.</p>
        ) : (
          <select
            id="site-select"
            data-testid="site-select"
            value={place?.id ?? ""}
            onChange={(e) => {
              const s = sites.data.sites.find((x) => x.id === e.target.value);
              pick(s ? { kind: "site", id: s.id, name: s.name, country: s.limit_country ?? country, latitude: s.latitude, longitude: s.longitude, detail: `Index class (screening): ${s.ui_status}` } : null);
            }}
            className="w-full rounded-lg border border-line bg-surface px-3 py-1.5"
          >
            <option value="">Choose a site</option>
            {sites.data.sites.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
