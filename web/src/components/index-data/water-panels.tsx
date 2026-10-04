"use client";

import { type ReactNode } from "react";
import type { Schema } from "@/lib/api";
import { useApi } from "@/lib/client/use-api";
import { formatNumber, formatPeriod, humanise } from "@/lib/format";
import { Async, DataTable, EmptyState, KeyValues, Notice, Pill } from "../ui";
import { SourceFooter, useExport } from "./shared";

export function WaterQualityPanel({ siteId }: { siteId: string }) {
  const state = useApi<Schema<"IndexResponse">>(`/indices/${encodeURIComponent(siteId)}`);
  useExport(`water-quality-${siteId}.json`, state.status === "ready" ? state.data : null);
  return (
    <Async state={state}>
      {(d) => (
        <div className="space-y-3">
          <KeyValues items={[["Status", d.status], ["Location", d.location_ref], ["Reference values", d.objective_limits_source], ...Object.entries(d.data_quality).map(([k, v]): [string, ReactNode] => [humanise(k), String(v)])]} />
          <SourceFooter origin={d.origin} freshness={d.data_freshness} notices={[d.interpretation_notice]} />
        </div>
      )}
    </Async>
  );
}

export function MeasurementsPanel({ siteId, group }: { siteId: string; group?: string }) {
  const state = useApi<Schema<"SiteMeasurementsResponse">>(`/sites/${encodeURIComponent(siteId)}/measurements`, { group, resolution: "annual", limit: 200 });
  useExport(`measurements-${siteId}.json`, state.status === "ready" ? state.data : null);
  return (
    <Async state={state} isEmpty={(d) => d.records.length === 0} empty={<EmptyState title="No measurements">This site has no values for this selection.</EmptyState>}>
      {(d) => (
        <div className="space-y-3">
          <DataTable
            caption="Measurements"
            rows={d.records}
            columns={[
              { header: "Parameter", cell: (r) => r.parameter },
              { header: "Period", cell: (r) => formatPeriod(r.period_start, r.period_end) },
              { header: "Value", align: "right", cell: (r) => `${r.comparator ?? ""}${formatNumber(r.value)}` },
              { header: "Unit", cell: (r) => r.unit },
              { header: "Statistic", cell: (r) => r.statistic ?? "n/a" },
              { header: "n", align: "right", cell: (r) => r.n ?? "n/a" },
              { header: "Reference check", cell: (r) => <Pill tone={r.status === "exceeds-limit" ? "warn" : "plain"}>{humanise(r.status)}</Pill> },
            ]}
          />
          {d.truncated ? <Notice tone="info">More records exist than are listed here.</Notice> : null}
          <SourceFooter origin={d.origin} freshness={d.data_freshness} attribution={d.attribution} notices={[d.interpretation_notice]} />
        </div>
      )}
    </Async>
  );
}

export function DataQualityPanel() {
  const state = useApi<Schema<"QcReportResponse">>("/qc/report");
  useExport("data-quality.json", state.status === "ready" ? state.data : null);
  return (
    <Async state={state}>
      {(d) => (
        <div className="space-y-3">
          <KeyValues items={[["Observations checked", formatNumber(d.total_observations, 0)], ["Excluded", formatNumber(d.excluded_observations_total ?? 0, 0)], ["Source", d.source], ["Generated", d.generated_at_utc]]} />
          <DataTable caption="Findings" rows={Object.entries(d.findings)} columns={[{ header: "Finding", cell: (r) => humanise(r[0]) }, { header: "Count", align: "right", cell: (r) => r[1] }]} />
          <SourceFooter origin={d.origin} freshness={d.data_freshness} />
        </div>
      )}
    </Async>
  );
}
