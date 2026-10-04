"use client";

import type { Schema } from "@/lib/api";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Async, DataTable, EmptyState, Notice } from "../ui";
import { SourceFooter, useExport, usePlace, PickPrompt } from "./shared";

export function BathingClassesPanel() {
  const { country } = useSettings();
  const t = useT();
  const state = useApi<Schema<"BathingWatersResponse">>("/bathing-waters", { country, limit: 200 });
  useExport(`bathing-classes-${country}.json`, state.status === "ready" ? state.data : null);
  return (
    <Async state={state} isEmpty={(d) => d.bathing_waters.length === 0} empty={<EmptyState title={t("No bathing waters")}>{t("None are held for this country.")}</EmptyState>}>
      {(d) => (
        <div className="space-y-3">
          <DataTable
            caption={t("Bathing waters")}
            rows={d.bathing_waters}
            columns={[
              { header: t("Name"), cell: (r) => r.name },
              { header: t("Latest classification"), cell: (r) => r.latest_quality ?? t("n/a") },
              { header: t("Latest season"), align: "right", cell: (r) => r.latest_season },
              { header: t("Seasons"), align: "right", cell: (r) => r.n_seasons },
              { header: t("Location"), cell: (r) => (r.location_status === "located" ? t("located") : t("no location")) },
            ]}
          />
          {d.truncated ? <Notice tone="info">{t("More bathing waters exist than are listed here.")}</Notice> : null}
          <SourceFooter origin={d.origin} freshness={d.data_freshness} attribution={d.attribution} notices={[d.notice]} />
        </div>
      )}
    </Async>
  );
}

export function BathingSamplesPanel() {
  const t = useT();
  const [place] = usePlace("bathing-water");
  const samples = useApi<Schema<"BathingSamplesResponse">>(place ? `/bathing-waters/${encodeURIComponent(place.id)}/samples` : null, { limit: 20 });
  useExport(`bathing-samples-${place?.id ?? "none"}.json`, samples.status === "ready" ? samples.data : null);
  return (
    <div className="space-y-4">
      {!place ? (
        <PickPrompt kind="bathing-water" />
      ) : (
        <Async state={samples}>
          {(d) => {
            const rows: { label: string; s: Schema<"IndicatorSummary"> }[] = [];
            if (d.summary.escherichia_coli) rows.push({ label: t("E. coli"), s: d.summary.escherichia_coli });
            if (d.summary.intestinal_enterococci) rows.push({ label: t("Intestinal enterococci"), s: d.summary.intestinal_enterococci });
            return (
              <div className="space-y-3">
                {rows.length === 0 ? (
                  <EmptyState title={t("No samples")}>{t("No samples are held for this bathing water.")}</EmptyState>
                ) : (
                  <DataTable
                    caption={t("Sample summary ({unit})", { unit: d.unit })}
                    rows={rows}
                    columns={[
                      { header: t("Indicator"), cell: (r) => r.label },
                      { header: t("Samples in range"), align: "right", cell: (r) => r.s.n_samples_in_range },
                      { header: t("Min"), align: "right", cell: (r) => formatNumber(r.s.min) },
                      { header: t("Median"), align: "right", cell: (r) => formatNumber(r.s.median) },
                      { header: t("Mean"), align: "right", cell: (r) => formatNumber(r.s.mean) },
                      { header: t("Max"), align: "right", cell: (r) => formatNumber(r.s.max) },
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
