"use client";

import { useState } from "react";
import type { Schema } from "@/lib/api";
import { useApi } from "@/lib/client/use-api";
import { formatNumber, previousYearRange } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Async, DataTable, EmptyState, Notice, Pill } from "../ui";
import { SourceFooter, useExport } from "./shared";

export function DateRange({ from, to, onFrom, onTo }: { from: string; to: string; onFrom: (v: string) => void; onTo: (v: string) => void }) {
  const t = useT();
  return (
    <div className="flex flex-wrap gap-3">
      <div>
        <label htmlFor="date-from" className="block text-xs text-muted">{t("From")}</label>
        <input id="date-from" type="date" value={from} onChange={(e) => onFrom(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-1.5" />
      </div>
      <div>
        <label htmlFor="date-to" className="block text-xs text-muted">{t("To")}</label>
        <input id="date-to" type="date" value={to} onChange={(e) => onTo(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-1.5" />
      </div>
    </div>
  );
}

/** `credit` is the provider's attribution wording and stays as written. */
export function ExternalNotes({ d, credit }: { d: { status: string; reason?: string | null; attribution: string; attribution_url?: string | null; data_note: string; licence: string; origin: string }; credit: string }) {
  const t = useT();
  return (
    <>
      {d.status !== "ok" ? (
        <Notice tone="warn" title={d.status === "no-data" ? t("No data for this period") : t("External provider unavailable")}>
          {d.reason ? t("Reason: {reason}.", { reason: d.reason }) : t("Try another period or later.")}
        </Notice>
      ) : null}
      <p className="text-sm">
        {d.attribution_url ? (
          <a href={d.attribution_url} target="_blank" rel="noopener noreferrer" className="text-accent underline">{credit}</a>
        ) : null}
        <span className="text-muted"> {t("Values are modelled and aggregated to months.")}</span>
      </p>
      <SourceFooter origin={d.origin} attribution={d.attribution} notices={[d.data_note, t("Licence: {name}", { name: d.licence })]} />
    </>
  );
}

export function WeatherPanel({ siteId }: { siteId: string }) {
  const t = useT();
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
                caption={t("Monthly weather (modelled)")}
                rows={d.months}
                columns={[
                  { header: t("Month"), cell: (r) => r.month },
                  { header: t("Precipitation (mm)"), align: "right", cell: (r) => formatNumber(r.precipitation_sum_mm, 1) },
                  { header: t("Mean temperature (°C)"), align: "right", cell: (r) => formatNumber(r.temperature_mean_c, 1) },
                  { header: t("Days with data"), align: "right", cell: (r) => `${r.precipitation_n_days}/${r.days_in_window}` },
                ]}
              />
            ) : (
              <EmptyState title={t("No months to show")} />
            )}
            <ExternalNotes d={d} credit="Weather data by Open-Meteo.com" />
          </div>
        )}
      </Async>
    </div>
  );
}

export function DischargePanel({ siteId }: { siteId: string }) {
  const t = useT();
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
                caption={t("Monthly river discharge (modelled)")}
                rows={d.months}
                columns={[
                  { header: t("Month"), cell: (r) => r.month },
                  { header: t("Mean discharge (m³/s)"), align: "right", cell: (r) => formatNumber(r.river_discharge_mean_m3s, 1) },
                  { header: t("Days with data"), align: "right", cell: (r) => `${r.n_days}/${r.days_in_window}` },
                ]}
              />
            ) : (
              <EmptyState title={t("No months to show")} />
            )}
            <ExternalNotes d={d} credit="River discharge data via Open-Meteo.com (GloFAS)" />
          </div>
        )}
      </Async>
    </div>
  );
}

export function SpeciesPanel({ siteId }: { siteId: string }) {
  const t = useT();
  const state = useApi<Schema<"SpeciesResponse">>(`/sites/${encodeURIComponent(siteId)}/species`, { limit: 50 });
  useExport(`species-${siteId}.json`, state.status === "ready" ? state.data : null);
  return (
    <Async state={state}>
      {(d) => (
        <div className="space-y-3">
          {d.status !== "ok" ? <Notice tone="warn" title={t("No records")}>{d.reason ? t("Reason: {reason}.", { reason: d.reason }) : t("No occurrence records were returned.")}</Notice> : null}
          {d.records.length ? (
            <DataTable
              caption={t("Species occurrence records")}
              rows={d.records}
              columns={[
                { header: t("Species"), cell: (r) => r.scientific_name },
                { header: t("Group"), cell: (r) => r.group ?? t("n/a") },
                { header: t("Year"), align: "right", cell: (r) => r.year ?? t("n/a") },
                { header: t("Distance (km)"), align: "right", cell: (r) => formatNumber(r.distance_km, 1) },
                { header: t("Licence"), cell: (r) => <span>{r.licence}{r.non_commercial_only ? <Pill tone="warn">{t("non-commercial")}</Pill> : null}</span> },
                { header: t("Dataset"), cell: (r) => r.dataset_name ?? t("n/a") },
                { header: t("Citation"), cell: (r) => r.citation ?? t("n/a") },
              ]}
            />
          ) : (
            <EmptyState title={t("No records")} />
          )}
          <SourceFooter origin={d.origin} attribution={d.attribution} notices={[d.data_note, t("Licence: {name}", { name: d.licence })]} />
        </div>
      )}
    </Async>
  );
}
