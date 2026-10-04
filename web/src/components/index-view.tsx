"use client";

import Link from "next/link";
import type { CatalogIndex, CatalogResponse } from "@/lib/api";
import { chatKey } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { COUNTRY_NAMES, FRESHNESS_LABEL, KIND_LABEL, originInfo } from "@/lib/constants";
import { formatDate } from "@/lib/format";
import { countryName, useT } from "@/lib/i18n";
import { ChatView } from "./chat";
import IndexData from "./index-data";
import PageHeader from "./page-header";
import { Async, KeyValues, Notice, OriginBadge } from "./ui";

export function AboutIndex({ index, catalog }: { index: CatalogIndex; catalog: CatalogResponse }) {
  const t = useT();
  const { language } = useSettings();
  return (
    <KeyValues
      items={[
        [t("Country"), catalog.country_name ?? countryName(catalog.country, language, COUNTRY_NAMES)],
        [t("Coverage"), index.applies ? t("Held by the service for this country") : (index.reason ?? t("Not held for this country"))],
        [t("Kind"), t(KIND_LABEL[index.origin_kind])],
        [t("Sources"), <span key="o" className="flex flex-wrap gap-1">{index.origins.map((o) => <OriginBadge key={o} origin={o} />)}</span>],
        [t("Source names"), index.origins.map((o) => t(originInfo(o).label)).join("; ")],
        [t("Data as of"), `${t(FRESHNESS_LABEL[catalog.data_freshness.status] ?? catalog.data_freshness.status)}${catalog.data_freshness.as_of ? `, ${formatDate(catalog.data_freshness.as_of)}` : ""}`],
        [t("Routes"), index.routes.join(", ")],
      ]}
    />
  );
}

export default function IndexView({ indexId }: { indexId: string }) {
  const settings = useSettings();
  const t = useT();
  const catalog = useApi<CatalogResponse>("/catalog", { country: settings.country, language: settings.language });

  return (
    <Async state={catalog}>
      {(c) => {
        const index = c.families.flatMap((f) => f.indices).find((i) => i.id === indexId);
        if (!index) {
          return (
            <>
              <PageHeader title={t("Unknown index")} />
              <div className="p-4"><Notice tone="warn">{t("This index does not exist.")} <Link href="/" className="underline">{t("Start a new question")}</Link>.</Notice></div>
            </>
          );
        }
        const title = t(index.title);
        if (!index.applies) {
          return (
            <>
              <PageHeader title={title} about={<AboutIndex index={index} catalog={c} />} />
              <div className="p-4" data-testid="not-applicable">
                <Notice tone="info" title={t("Not available for this country")}>{index.reason ?? t("The service holds no data for it.")}</Notice>
              </div>
            </>
          );
        }
        return (
          <>
            <PageHeader title={title} about={<AboutIndex index={index} catalog={c} />} />
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
