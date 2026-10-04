"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { CatalogFamily, CatalogIndex, CatalogResponse, CountriesResponse } from "@/lib/api";
import { chatKey, useApp } from "@/lib/client/app-context";
import { updateSettings, useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { COUNTRY_NAMES, KIND_DOT, KIND_LABEL, USER_LABEL } from "@/lib/constants";
import { Async, EmptyState, Notice } from "./ui";

/** Only what the backend marks as applicable is shown; families left without an index are dropped. */
export function visibleFamilies(catalog: CatalogResponse): CatalogFamily[] {
  return catalog.families
    .map((f) => ({ ...f, indices: f.indices.filter((i) => i.applies) }))
    .filter((f) => f.indices.length > 0);
}

export function indexHref(index: Pick<CatalogIndex, "id" | "family_id">): string {
  return index.family_id === "synthetic-labs" ? `/labs/${index.id}` : `/i/${index.id}`;
}

function unbuiltStores(catalog: CatalogResponse): string[] {
  const s = catalog.stores;
  const out: string[] = [];
  if (s.sandbox !== "available") out.push("sandbox");
  if (s.waterbase.state !== "ready") out.push("EEA Waterbase");
  if (s.bathing_water.state !== "ready") out.push("EEA bathing-water classification");
  if (s.bathing_samples.state !== "ready") out.push("EEA bathing samples");
  return out;
}

export default function Sidebar() {
  const app = useApp();
  const router = useRouter();
  const pathname = usePathname();
  const settings = useSettings();
  const countries = useApi<CountriesResponse>("/countries");
  const catalog = useApi<CatalogResponse>("/catalog", { country: settings.country });
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const codes = countries.status === "ready" ? countries.data.countries.map((c) => c.code) : [settings.country];

  // A stored country the service does not know (for example after a change of backend) falls back to the first one.
  const known = countries.status === "ready" ? codes : null;
  useEffect(() => {
    if (known && known.length > 0 && !known.includes(settings.country)) updateSettings({ country: known[0] });
  }, [known, settings.country]);

  function newQuestion(indexId: string | null, href: string) {
    app.clearChat(chatKey(settings.country, indexId));
    app.setSidebarOpen(false);
    router.push(href);
  }

  return (
    <nav aria-label="Main" className="flex h-full w-72 flex-col gap-3 bg-sidebar px-3 py-3">
      <div>
        <label htmlFor="country" className="mb-1 block text-xs font-medium uppercase tracking-wide text-muted">
          Country
        </label>
        <select
          id="country"
          data-testid="country-select"
          value={settings.country}
          onChange={(e) => {
            app.setPlace(null); // a picked place belongs to the country it was picked in
            updateSettings({ country: e.target.value });
          }}
          className="w-full rounded-lg border border-line bg-surface px-3 py-2"
        >
          {codes.map((code) => (
            <option key={code} value={code}>
              {COUNTRY_NAMES[code] ?? code}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => newQuestion(null, "/")}
          className="mt-2 w-full rounded-lg px-3 py-2 text-left font-medium hover:bg-line/40"
        >
          + New question
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto" data-testid="sidebar-body">
        <Async
          state={catalog}
          isEmpty={(c) => visibleFamilies(c).length === 0}
          empty={<EmptyState title="Nothing available">No indices apply to this country.</EmptyState>}
        >
          {(c) => (
            <div className="space-y-3">
              {visibleFamilies(c).map((family) => {
                const open = !collapsed[family.id];
                const first = family.indices[0];
                const canAsk = family.id !== "synthetic-labs" && first;
                return (
                  <section key={family.id} aria-label={family.title}>
                    <div className="flex items-center justify-between">
                      <button
                        type="button"
                        aria-expanded={open}
                        onClick={() => setCollapsed((s) => ({ ...s, [family.id]: open }))}
                        className="flex items-center gap-1 px-2 py-1 text-xs font-medium uppercase tracking-wide text-muted"
                      >
                        <span aria-hidden>{open ? "▾" : "▸"}</span>
                        {family.title}
                      </button>
                      {canAsk ? (
                        <button
                          type="button"
                          aria-label={`New question in ${family.title}`}
                          onClick={() => newQuestion(first.id, indexHref(first))}
                          className="rounded px-2 text-lg leading-none text-muted hover:bg-line/40"
                        >
                          +
                        </button>
                      ) : null}
                    </div>
                    {open ? (
                      <ul className="space-y-0.5">
                        {family.indices.map((index) => {
                          const href = indexHref(index);
                          const active = pathname === href;
                          return (
                            <li key={index.id}>
                              <Link
                                href={href}
                                aria-current={active ? "page" : undefined}
                                onClick={() => app.setSidebarOpen(false)}
                                className={`flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-line/40 ${active ? "bg-line/60 font-medium" : ""}`}
                              >
                                <span
                                  role="img"
                                  aria-label={KIND_LABEL[index.origin_kind]}
                                  title={KIND_LABEL[index.origin_kind]}
                                  className={`h-2.5 w-2.5 shrink-0 rounded-full ${KIND_DOT[index.origin_kind]}`}
                                />
                                <span className="truncate">{index.title}</span>
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    ) : null}
                  </section>
                );
              })}
              {unbuiltStores(c).length ? (
                <Notice tone="info">Not loaded in this service: {unbuiltStores(c).join(", ")}.</Notice>
              ) : null}
              <ul className="flex flex-wrap gap-x-3 gap-y-1 px-2 text-xs text-muted" aria-label="Origin legend">
                {(Object.keys(KIND_LABEL) as (keyof typeof KIND_LABEL)[]).map((k) => (
                  <li key={k} className="flex items-center gap-1">
                    <span aria-hidden className={`h-2 w-2 rounded-full ${KIND_DOT[k]}`} />
                    {KIND_LABEL[k]}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Async>
      </div>

      <div className="flex items-center justify-between border-t border-line pt-3">
        <span className="flex items-center gap-2 text-sm">
          <span aria-hidden className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-sm font-medium text-accent-ink">
            J
          </span>
          {USER_LABEL}
        </span>
        <Link
          href="/settings"
          aria-label="Settings"
          onClick={() => app.setSidebarOpen(false)}
          className={`rounded-lg px-2 py-1 text-sm hover:bg-line/40 ${pathname === "/settings" ? "bg-line/60" : ""}`}
        >
          Settings
        </Link>
      </div>
    </nav>
  );
}
