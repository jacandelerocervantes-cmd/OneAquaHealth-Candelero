"use client";

import { type ReactNode } from "react";
import type { Schema } from "@/lib/api";
import { useApi } from "@/lib/client/use-api";
import { formatNumber, formatPeriod, humanise } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Async, DataTable, EmptyState, KeyValues, Notice, Pill } from "../ui";
import { FhirDownload } from "./fhir-download";
import { SourceFooter, useExport } from "./shared";

export function WaterQualityPanel({ siteId, measurementsOnly = false }: { siteId: string; measurementsOnly?: boolean }) {
  const t = useT();
  if (measurementsOnly) {
    return (
      <Notice tone="info">
        {t("The water quality index is computed only for sandbox locations. This site has measurements only: see Water parameters.")}
      </Notice>
    );
  }
  return <WaterQualityResult siteId={siteId} />;
}

function WaterQualityResult({ siteId }: { siteId: string }) {
  const t = useT();
  const state = useApi<Schema<"IndexResponse">>(`/indices/${encodeURIComponent(siteId)}`);
  useExport(`water-quality-${siteId}.json`, state.status === "ready" ? state.data : null);
  return (
    <Async state={state}>
      {(d) => (
        <div className="space-y-3">
          <KeyValues items={[[t("Status"), t(humanise(d.status))], [t("Location"), d.location_ref], [t("Reference values"), d.objective_limits_source], ...Object.entries(d.data_quality).map(([k, v]): [string, ReactNode] => [t(humanise(k)), String(v)])]} />
          <SourceFooter origin={d.origin} freshness={d.data_freshness} notices={[d.interpretation_notice]} />
        </div>
      )}
    </Async>
  );
}

export function MeasurementsPanel({ siteId, group }: { siteId: string; group?: string }) {
  const t = useT();
  const state = useApi<Schema<"SiteMeasurementsResponse">>(`/sites/${encodeURIComponent(siteId)}/measurements`, { group, resolution: "annual", limit: 200 });
  useExport(`measurements-${siteId}.json`, state.status === "ready" ? state.data : null);
  return (
    <Async state={state} isEmpty={(d) => d.records.length === 0} empty={<EmptyState title={t("No measurements")}>{t("This site has no values for this selection.")}</EmptyState>}>
      {(d) => (
        <div className="space-y-3">
          <DataTable
            caption={t("Measurements")}
            rows={d.records}
            columns={[
              { header: t("Parameter"), cell: (r) => r.parameter },
              { header: t("Period"), cell: (r) => formatPeriod(r.period_start, r.period_end) },
              { header: t("Value"), align: "right", cell: (r) => `${r.comparator ?? ""}${formatNumber(r.value)}` },
              { header: t("Unit"), cell: (r) => r.unit },
              { header: t("Statistic"), cell: (r) => r.statistic ?? t("n/a") },
              { header: t("n"), align: "right", cell: (r) => r.n ?? t("n/a") },
              { header: t("Reference check"), cell: (r) => <Pill tone={r.status === "exceeds-limit" ? "warn" : "plain"}>{t(humanise(r.status))}</Pill> },
            ]}
          />
          {d.truncated ? <Notice tone="info">{t("More records exist than are listed here.")}</Notice> : null}
          <FhirDownload siteId={siteId} group={group} />
          <SourceFooter origin={d.origin} freshness={d.data_freshness} attribution={d.attribution} notices={[d.interpretation_notice]} />
        </div>
      )}
    </Async>
  );
}

export function DataQualityPanel() {
  const t = useT();
  const state = useApi<Schema<"QcReportResponse">>("/qc/report");
  useExport("data-quality.json", state.status === "ready" ? state.data : null);
  return (
    <Async state={state}>
      {(d) => (
        <div className="space-y-3">
          <KeyValues items={[[t("Observations checked"), formatNumber(d.total_observations, 0)], [t("Excluded"), formatNumber(d.excluded_observations_total ?? 0, 0)], [t("Source"), d.source], [t("Generated"), d.generated_at_utc]]} />
          <DataTable caption={t("Findings")} rows={Object.entries(d.findings)} columns={[{ header: t("Finding"), cell: (r) => t(humanise(r[0])) }, { header: t("Count"), align: "right", cell: (r) => r[1] }]} />
          <SourceFooter origin={d.origin} freshness={d.data_freshness} />
        </div>
      )}
    </Async>
  );
}
