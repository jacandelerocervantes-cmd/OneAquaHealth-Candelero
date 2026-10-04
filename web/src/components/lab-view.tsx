"use client";

import { useEffect, useState } from "react";
import type { Schema } from "@/lib/api";
import { useApp } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { formatNumber, humanise } from "@/lib/format";
import { SourceFooter } from "./index-data";
import { LAB_TITLES, type LabId } from "@/lib/labs";
import PageHeader from "./page-header";
import { Async, DataTable, EmptyState, KeyValues, Notice, Pill } from "./ui";

const SYNTHETIC_BANNER =
  "Synthetic lab: every value on this page is simulated. It is not real data and not real-world performance.";

function useLabExport(filename: string, data: unknown) {
  const { setExportPayload } = useApp();
  useEffect(() => {
    setExportPayload(data ? { filename, data } : null);
    return () => setExportPayload(null);
  }, [filename, data, setExportPayload]);
}

function CitizenScience() {
  const [seed, setSeed] = useState(7);
  const [draft, setDraft] = useState("7");
  const state = useApi<Schema<"ReliabilityCampaignResponse">>("/reliability/campaign", { seed });
  useLabExport(`citizen-science-seed-${seed}.json`, state.status === "ready" ? state.data : null);
  return (
    <div className="space-y-4">
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSeed(Math.min(2_000_000_000, Math.max(0, Math.trunc(Number(draft) || 0))));
        }}
      >
        <div>
          <label htmlFor="seed" className="block text-xs text-muted">Random seed (0 to 2000000000)</label>
          <input id="seed" type="number" min={0} max={2000000000} value={draft} onChange={(e) => setDraft(e.target.value)} className="w-40 rounded-lg border border-line bg-surface px-3 py-1.5" />
        </div>
        <button type="submit" className="rounded-lg border border-line px-3 py-1.5 hover:bg-sidebar">Run campaign</button>
      </form>
      <Async state={state}>
        {(d) => (
          <div className="space-y-3">
            <p>Recommended aggregation method for this simulated campaign: <strong>{d.recommended_method}</strong>.</p>
            <DataTable
              caption="Aggregation methods compared on simulated annotations"
              rows={[
                { method: "Majority vote", accuracy: d.majority_vote_accuracy, f1: d.majority_vote_macro_f1, loss: null },
                { method: "Dawid-Skene", accuracy: d.dawid_skene_accuracy, f1: d.dawid_skene_macro_f1, loss: d.dawid_skene_log_loss },
              ]}
              columns={[
                { header: "Method", cell: (r) => r.method },
                { header: "Accuracy", align: "right", cell: (r) => formatNumber(r.accuracy, 3) },
                { header: "Macro F1", align: "right", cell: (r) => formatNumber(r.f1, 3) },
                { header: "Log loss", align: "right", cell: (r) => formatNumber(r.loss, 3) },
              ]}
            />
            <KeyValues items={[["Seed", d.seed], ...Object.entries(d.parameters).map(([k, v]): [string, string] => [humanise(k), String(v)])]} />
            <SourceFooter origin={d.origin} />
          </div>
        )}
      </Async>
    </div>
  );
}

function ReviewQueue() {
  const state = useApi<Schema<"ReviewQueueResponse">>("/review/queue");
  useLabExport("review-queue.json", state.status === "ready" ? state.data : null);
  return (
    <Async state={state} isEmpty={(d) => d.items.length === 0} empty={<EmptyState title="The review queue is empty">No simulated specimens are waiting.</EmptyState>}>
      {(d) => (
        <div className="space-y-3">
          <Notice tone="info">Read-only: decisions cannot be recorded from this app.</Notice>
          <DataTable
            caption="Simulated specimens waiting for review"
            rows={d.items}
            columns={[
              { header: "Specimen", cell: (r) => r.specimen_id },
              { header: "Status", cell: (r) => r.status },
              { header: "Tag", cell: (r) => <Pill tone="plain">{r.tag}</Pill> },
              { header: "Prediction set", cell: (r) => r.prediction_set.join(", ") },
              { header: "Probabilities", cell: (r) => Object.entries(r.probabilities).map(([k, v]) => `${k} ${formatNumber(v, 2)}`).join(" · ") },
            ]}
          />
          <SourceFooter origin={d.origin} />
        </div>
      )}
    </Async>
  );
}

function RiverRisk() {
  const { country } = useSettings();
  const sites = useApi<Schema<"SitesResponse">>("/sites", { country, limit: 200 });
  const [siteId, setSiteId] = useState("");
  const risk = useApi<Schema<"RiskResponse">>(siteId ? `/risk/${encodeURIComponent(siteId)}` : null);
  useLabExport(`river-risk-${siteId || "none"}.json`, risk.status === "ready" && siteId ? risk.data : null);
  return (
    <div className="space-y-4">
      <Async state={sites} isEmpty={(d) => d.sites.length === 0} empty={<EmptyState title="No sites">None are listed for this country.</EmptyState>}>
        {(d) => (
          <div>
            <label htmlFor="risk-site" className="block text-xs text-muted">Site</label>
            <select id="risk-site" value={siteId} onChange={(e) => setSiteId(e.target.value)} className="w-full max-w-md rounded-lg border border-line bg-surface px-3 py-1.5">
              <option value="">Choose a site</option>
              {d.sites.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
        )}
      </Async>
      {!siteId ? (
        <EmptyState title="Choose a site">The synthetic score is shown for the site you pick.</EmptyState>
      ) : (
        <Async state={risk}>
          {(d) => (
            <div className="space-y-3">
              <p className="text-3xl font-semibold tabular-nums" data-testid="risk-score">{formatNumber(d.risk, 2)}</p>
              <p className="text-muted">{d.note}</p>
              <SourceFooter origin={d.origin} />
            </div>
          )}
        </Async>
      )}
    </div>
  );
}

export default function LabView({ labId }: { labId: LabId }) {
  return (
    <>
      <PageHeader title={LAB_TITLES[labId]} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-4 px-4 py-6" data-testid="lab">
          <div role="note" data-testid="synthetic-banner" className="rounded-lg bg-mock-bg px-3 py-2 text-sm font-medium text-mock-ink">
            {SYNTHETIC_BANNER}
          </div>
          {labId === "citizen-science" ? <CitizenScience /> : null}
          {labId === "review-queue" ? <ReviewQueue /> : null}
          {labId === "river-risk" ? <RiverRisk /> : null}
        </div>
      </div>
    </>
  );
}
