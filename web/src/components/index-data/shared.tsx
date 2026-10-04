"use client";

import { useEffect } from "react";
import type { Schema } from "@/lib/api";
import { useApp, type PickedPlace } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useT } from "@/lib/i18n";
import { EmptyState, FreshnessBadge, OriginBadge } from "../ui";

export type Freshness = Schema<"DataFreshnessModel">;

/** The line under every data table: origin, freshness, attribution and the route's own notice. */
export function SourceFooter({ origin, freshness, attribution, notices }: { origin: string; freshness?: Freshness; attribution?: string | null; notices?: (string | null | undefined)[] }) {
  return (
    <div data-testid="source-footer" className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <OriginBadge origin={origin} />
        {freshness ? <FreshnessBadge freshness={freshness} /> : null}
      </div>
      {attribution ? <p className="text-muted">{attribution}</p> : null}
      {(notices ?? []).filter(Boolean).map((n) => (
        <p key={n} className="text-muted">{n}</p>
      ))}
    </div>
  );
}

/** Publishes what the panel shows so the header's download button can save it. */
export function useExport(filename: string, data: unknown) {
  const { setExportPayload } = useApp();
  useEffect(() => {
    setExportPayload(data ? { filename, data } : null);
    return () => setExportPayload(null);
  }, [filename, data, setExportPayload]);
}

export type Kind = PickedPlace["kind"];

export function usePlace(kind: Kind): [PickedPlace | null, (p: PickedPlace | null) => void] {
  const { place, setPlace } = useApp();
  const { country } = useSettings();
  const valid = place && place.kind === kind && place.country === country ? place : null;
  return [valid, setPlace];
}

export function PickPrompt({ kind = "site" }: { kind?: Kind }) {
  const t = useT();
  return kind === "site" ? (
    <EmptyState title={t("Choose a site")}>{t("Search for a site in the sidebar, or select one on the map.")}</EmptyState>
  ) : (
    <EmptyState title={t("Choose a bathing water")}>{t("Search for a bathing water in the sidebar, or select one on the map.")}</EmptyState>
  );
}
