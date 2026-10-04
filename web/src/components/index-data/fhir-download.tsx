"use client";

import { useState } from "react";
import { apiGet, describeError } from "@/lib/client/api";
import { fhirFilename } from "@/lib/fhir";
import { downloadJson } from "@/lib/format";
import { useT } from "@/lib/i18n";

/**
 * "Download as FHIR": the same selection as the table, from `GET /sites/{id}/fhir` (a FHIR R4 Bundle built by the backend),
 * saved as a file. The one-line explanation is for readers who do not know the standard.
 */
export function FhirDownload({ siteId, group }: { siteId: string; group?: string }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setFailure(null);
    try {
      const bundle = await apiGet<unknown>(`/sites/${encodeURIComponent(siteId)}/fhir`, { group, resolution: "annual", limit: 200 });
      downloadJson(fhirFilename(siteId), bundle);
    } catch (error) {
      setFailure(describeError(error, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="fhir-download" className="space-y-1">
      <button
        type="button"
        onClick={() => void download()}
        disabled={busy}
        className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-sidebar disabled:opacity-60"
      >
        {t("Download as FHIR")}
      </button>
      <p className="text-xs text-muted">{t("FHIR is the international standard health systems use to exchange data. This file can be loaded by any FHIR system.")}</p>
      {failure ? (
        <p role="alert" className="text-xs text-bad-ink">
          {failure}
        </p>
      ) : null}
    </div>
  );
}
