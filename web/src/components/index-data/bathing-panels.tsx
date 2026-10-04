"use client";

import type { Schema } from "@/lib/api";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { formatNumber } from "@/lib/format";
import { Async, DataTable, EmptyState, Notice } from "../ui";
import { SourceFooter, useExport, usePlace, PickPrompt } from "./shared";

export function BathingClassesPanel() {
  const { country } = useSettings();
  const state = useApi<Schema<"BathingWatersResponse">>("/bathing-waters", { country, limit: 200 });
  useExport(`bathing-classes-${country}.json`, state.status === "ready" ? state.data : null);
  return (
    <Async state={state} isEmpty={(d) => d.bathing_waters.length === 0} empty={<EmptyState title="No bathing waters">None are held for this country.</EmptyState>}>
      {(d) => (
        <div className="space-y-3">
          <DataTable
            caption="Bathing waters"
            rows={d.bathing_waters}
            columns={[
              { header: "Name", cell: (r) => r.name },
              { header: "Latest classification", cell: (r) => r.latest_quality ?? "n/a" },
              { header: "Latest season", align: "right", cell: (r) => r.latest_season },
              { header: "Seasons", align: "right", cell: (r) => r.n_seasons },
              { header: "Location", cell: (r) => (r.location_status === "located" ? "located" : "no location") },
            ]}
          />
          {d.truncated ? <Notice tone="info">More bathing waters exist than are listed here.</Notice> : null}
          <SourceFooter origin={d.origin} freshness={d.data_freshness} attribution={d.attribution} notices={[d.notice]} />
        </div>
      )}
    </Async>
  );
}

export function BathingSamplesPanel() {
  const { country } = useSettings();
  const [place, setPlace] = usePlace("bathing-water");
  const waters = useApi<Schema<"BathingWatersResponse">>("/bathing-waters", { country, limit: 200 });
  const samples = useApi<Schema<"BathingSamplesResponse">>(place ? `/bathing-waters/${encodeURIComponent(place.id)}/samples` : null, { limit: 20 });
  useExport(`bathing-samples-${place?.id ?? "none"}.json`, samples.status === "ready" ? samples.data : null);
  return (
    <div className="space-y-4">
      <Async state={waters} isEmpty={(d) => d.bathing_waters.length === 0} empty={<EmptyState title="No bathing waters">None are held for this country.</EmptyState>}>
        {(d) => (
          <div>
            <label htmlFor="bw-select" className="block text-xs text-muted">Bathing water</label>
            <select
              id="bw-select"
              data-testid="bw-select"
              value={place?.id ?? ""}
              onChange={(e) => {
                const b = d.bathing_waters.find((x) => x.id === e.target.value);
                setPlace(b ? { kind: "bathing-water", id: b.id, name: b.name, country: b.country, latitude: b.latitude ?? null, longitude: b.longitude ?? null, detail: `Latest classification: ${b.latest_quality ?? "n/a"}` } : null);
              }}
              className="w-full max-w-md rounded-lg border border-line bg-surface px-3 py-1.5"
            >
              <option value="">Choose a bathing water</option>
              {d.bathing_waters.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </div>
        )}
      </Async>
      {!place ? (
        <PickPrompt />
      ) : (
        <Async state={samples}>
          {(d) => {
            const rows: { label: string; s: Schema<"IndicatorSummary"> }[] = [];
            if (d.summary.escherichia_coli) rows.push({ label: "E. coli", s: d.summary.escherichia_coli });
            if (d.summary.intestinal_enterococci) rows.push({ label: "Intestinal enterococci", s: d.summary.intestinal_enterococci });
            return (
              <div className="space-y-3">
                {rows.length === 0 ? (
                  <EmptyState title="No samples">No samples are held for this bathing water.</EmptyState>
                ) : (
                  <DataTable
                    caption={`Sample summary (${d.unit})`}
                    rows={rows}
                    columns={[
                      { header: "Indicator", cell: (r) => r.label },
                      { header: "Samples in range", align: "right", cell: (r) => r.s.n_samples_in_range },
                      { header: "Min", align: "right", cell: (r) => formatNumber(r.s.min) },
                      { header: "Median", align: "right", cell: (r) => formatNumber(r.s.median) },
                      { header: "Mean", align: "right", cell: (r) => formatNumber(r.s.mean) },
                      { header: "Max", align: "right", cell: (r) => formatNumber(r.s.max) },
                    ]}
                  />
                )}
                <SourceFooter origin={d.origin} freshness={d.data_freshness} attribution={d.attribution} notices={[d.unit_statement, d.no_threshold_notice, d.flagged_values_note, d.notice]} />
              </div>
            );
          }}
        </Async>
      )}
    </div>
  );
}
