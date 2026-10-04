"use client";

import Link from "next/link";
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

export default function IndexView({ indexId }: { indexId: string }) {
  const settings = useSettings();
  const catalog = useApi<CatalogResponse>("/catalog", { country: settings.country });

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
            <ChatView
              chatKey={chatKey(settings.country, index.id)}
              country={settings.country}
              chatIndex={index.chat_index ?? null}
              indexId={index.id}
              below={<IndexData indexId={index.id} />}
            />
          </>
        );
      }}
    </Async>
  );
}
