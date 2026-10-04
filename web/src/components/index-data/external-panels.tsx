"use client";

import { useState } from "react";
import type { Schema } from "@/lib/api";
import { useApi } from "@/lib/client/use-api";
import { formatNumber, previousYearRange } from "@/lib/format";
import { Async, DataTable, EmptyState, Notice, Pill } from "../ui";
import { SourceFooter, useExport } from "./shared";

export function DateRange({ from, to, onFrom, onTo }: { from: string; to: string; onFrom: (v: string) => void; onTo: (v: string) => void }) {
  return (
    <div className="flex flex-wrap gap-3">
      <div>
        <label htmlFor="date-from" className="block text-xs text-muted">From</label>
        <input id="date-from" type="date" value={from} onChange={(e) => onFrom(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-1.5" />
      </div>
      <div>
        <label htmlFor="date-to" className="block text-xs text-muted">To</label>
        <input id="date-to" type="date" value={to} onChange={(e) => onTo(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-1.5" />
      </div>
    </div>
  );
}

export function ExternalNotes({ d, credit }: { d: { status: string; reason?: string | null; attribution: string; attribution_url?: string | null; data_note: string; licence: string; origin: string }; credit: string }) {
  return (
    <>
      {d.status !== "ok" ? (
        <Notice tone="warn" title={d.status === "no-data" ? "No data for this period" : "External provider unavailable"}>
          {d.reason ? `Reason: ${d.reason}.` : "Try another period or later."}
        </Notice>
      ) : null}
      <p className="text-sm">
        {d.attribution_url ? (
          <a href={d.attribution_url} target="_blank" rel="noopener noreferrer" className="text-accent underline">{credit}</a>
        ) : null}
        <span className="text-muted"> Values are modelled and aggregated to months.</span>
      </p>
      <SourceFooter origin={d.origin} attribution={d.attribution} notices={[d.data_note, `Licence: ${d.licence}`]} />
    </>
  );
}

export function WeatherPanel({ siteId }: { siteId: string }) {
  const range = previousYearRange();
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);
  const state = useApi<Schema<"WeatherResponse">>(`/sites/${encodeURIComponent(siteId)}/weather`, { date_from: from, date_to: to });
  useExport(`weather-${siteId}.json`, state.status === "ready" ? state.data : null);
  return (
    <div className="space-y-3">
      <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
      <Async state={state}>
        {(d) => (
          <div className="space-y-3">
            {d.months.length ? (
              <DataTable
                caption="Monthly weather (modelled)"
                rows={d.months}
                columns={[
                  { header: "Month", cell: (r) => r.month },
                  { header: "Precipitation (mm)", align: "right", cell: (r) => formatNumber(r.precipitation_sum_mm, 1) },
                  { header: "Mean temperature (°C)", align: "right", cell: (r) => formatNumber(r.temperature_mean_c, 1) },
                  { header: "Days with data", align: "right", cell: (r) => `${r.precipitation_n_days}/${r.days_in_window}` },
                ]}
              />
            ) : (
              <EmptyState title="No months to show" />
            )}
            <ExternalNotes d={d} credit="Weather data by Open-Meteo.com" />
          </div>
        )}
      </Async>
    </div>
  );
}

export function DischargePanel({ siteId }: { siteId: string }) {
  const range = previousYearRange();
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);
  const state = useApi<Schema<"DischargeResponse">>(`/sites/${encodeURIComponent(siteId)}/discharge`, { date_from: from, date_to: to });
  useExport(`discharge-${siteId}.json`, state.status === "ready" ? state.data : null);
  return (
    <div className="space-y-3">
      <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
      <Async state={state}>
        {(d) => (
          <div className="space-y-3">
            {d.months.length ? (
              <DataTable
                caption="Monthly river discharge (modelled)"
                rows={d.months}
                columns={[
                  { header: "Month", cell: (r) => r.month },
                  { header: "Mean discharge (m³/s)", align: "right", cell: (r) => formatNumber(r.river_discharge_mean_m3s, 1) },
                  { header: "Days with data", align: "right", cell: (r) => `${r.n_days}/${r.days_in_window}` },
                ]}
              />
            ) : (
              <EmptyState title="No months to show" />
            )}
            <ExternalNotes d={d} credit="River discharge data via Open-Meteo.com (GloFAS)" />
          </div>
        )}
      </Async>
    </div>
  );
}

export function SpeciesPanel({ siteId }: { siteId: string }) {
  const state = useApi<Schema<"SpeciesResponse">>(`/sites/${encodeURIComponent(siteId)}/species`, { limit: 50 });
  useExport(`species-${siteId}.json`, state.status === "ready" ? state.data : null);
  return (
    <Async state={state}>
      {(d) => (
        <div className="space-y-3">
          {d.status !== "ok" ? <Notice tone="warn" title="No records">{d.reason ? `Reason: ${d.reason}.` : "No occurrence records were returned."}</Notice> : null}
          {d.records.length ? (
            <DataTable
              caption="Species occurrence records"
              rows={d.records}
              columns={[
                { header: "Species", cell: (r) => r.scientific_name },
                { header: "Group", cell: (r) => r.group ?? "n/a" },
                { header: "Year", align: "right", cell: (r) => r.year ?? "n/a" },
                { header: "Distance (km)", align: "right", cell: (r) => formatNumber(r.distance_km, 1) },
                { header: "Licence", cell: (r) => <span>{r.licence}{r.non_commercial_only ? <Pill tone="warn">non-commercial</Pill> : null}</span> },
                { header: "Dataset", cell: (r) => r.dataset_name ?? "n/a" },
                { header: "Citation", cell: (r) => r.citation ?? "n/a" },
              ]}
            />
          ) : (
            <EmptyState title="No records" />
          )}
          <SourceFooter origin={d.origin} attribution={d.attribution} notices={[d.data_note, `Licence: ${d.licence}`]} />
        </div>
      )}
    </Async>
  );
}
