"use client";

import Link from "next/link";
import { useState } from "react";
import type { CatalogIndex, CatalogResponse } from "@/lib/api";
import { chatKey } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { COUNTRY_NAMES, KIND_LABEL, originInfo } from "@/lib/constants";
import { formatDate } from "@/lib/format";
import { ChatView } from "./chat";
import IndexData from "./index-data";
import PageHeader from "./page-header";
import { Async, KeyValues, Notice, OriginBadge } from "./ui";

export function AboutIndex({ index, catalog }: { index: CatalogIndex; catalog: CatalogResponse }) {
  return (
    <KeyValues
      items={[
        ["Country", catalog.country_name ?? COUNTRY_NAMES[catalog.country] ?? catalog.country],
        ["Coverage", index.applies ? "Held by the service for this country" : (index.reason ?? "Not held for this country")],
        ["Kind", KIND_LABEL[index.origin_kind]],
        ["Sources", <span key="o" className="flex flex-wrap gap-1">{index.origins.map((o) => <OriginBadge key={o} origin={o} />)}</span>],
        ["Source names", index.origins.map((o) => originInfo(o).label).join("; ")],
        ["Data as of", `${catalog.data_freshness.status}${catalog.data_freshness.as_of ? `, ${formatDate(catalog.data_freshness.as_of)}` : ""}`],
        ["Routes", index.routes.join(", ")],
      ]}
    />
  );
}

type Tab = "ask" | "data";

export default function IndexView({ indexId }: { indexId: string }) {
  const settings = useSettings();
  const catalog = useApi<CatalogResponse>("/catalog", { country: settings.country });
  const [tab, setTab] = useState<Tab>("ask");

  return (
    <Async state={catalog}>
      {(c) => {
        const index = c.families.flatMap((f) => f.indices).find((i) => i.id === indexId);
        if (!index) {
          return (
            <>
              <PageHeader title="Unknown index" />
              <div className="p-4"><Notice tone="warn">This index does not exist. <Link href="/" className="underline">Start a new question</Link>.</Notice></div>
            </>
          );
        }
        if (!index.applies) {
          return (
            <>
              <PageHeader title={index.title} about={<AboutIndex index={index} catalog={c} />} />
              <div className="p-4" data-testid="not-applicable">
                <Notice tone="info" title="Not available for this country">{index.reason ?? "The service holds no data for it."}</Notice>
              </div>
            </>
          );
        }
        return (
          <>
            <PageHeader title={index.title} about={<AboutIndex index={index} catalog={c} />} />
            <div role="tablist" aria-label="View" className="flex gap-1 border-b border-line px-4">
              {(["ask", "data"] as const).map((t) => (
                <button
                  key={t}
                  role="tab"
                  type="button"
                  id={`tab-${t}`}
                  aria-selected={tab === t}
                  aria-controls={`panel-${t}`}
                  onClick={() => setTab(t)}
                  className={`border-b-2 px-3 py-2 text-sm ${tab === t ? "border-accent font-medium" : "border-transparent text-muted"}`}
                >
                  {t === "ask" ? "Ask" : "Data"}
                </button>
              ))}
            </div>
            {tab === "ask" ? (
              <div role="tabpanel" id="panel-ask" aria-labelledby="tab-ask" className="flex min-h-0 flex-1 flex-col">
                <ChatView chatKey={chatKey(settings.country, index.id)} country={settings.country} chatIndex={index.chat_index ?? null} indexId={index.id} />
              </div>
            ) : (
              <div role="tabpanel" id="panel-data" aria-labelledby="tab-data" className="min-h-0 flex-1 overflow-y-auto">
                <div className="mx-auto max-w-4xl px-4 py-6">
                  <IndexData indexId={index.id} />
                </div>
              </div>
            )}
          </>
        );
      }}
    </Async>
  );
}
