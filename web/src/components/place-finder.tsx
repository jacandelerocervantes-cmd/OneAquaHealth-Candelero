"use client";

import { usePathname } from "next/navigation";
import { useEffect, useId, useState, type KeyboardEvent } from "react";
import type { SitesResponse } from "@/lib/api";
import { useApp } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { useT } from "@/lib/i18n";
import { finderKinds } from "@/lib/places";
import { siteDetail } from "./place-detail";

/** At most this many suggestions are shown, in a list that never scrolls. */
const MAX_RESULTS = 5;
/** Wait for the typing to pause before asking the service (one request per pause, not per key). */
const DEBOUNCE_MS = 150;

/** The part of `text` that matches what was typed, emphasised (plain text nodes: nothing here parses HTML). */
function Highlighted({ text, query }: { text: string; query: string }) {
  const at = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <b className="font-medium text-accent">{text.slice(at, at + query.length)}</b>
      {text.slice(at + query.length)}
    </>
  );
}

/**
 * A simple site search under the country selector, like a search box with suggestions: nothing is listed until something
 * is typed, then a short list opens over the menu (arrow keys, Enter and Escape work). Sites only; bathing waters are
 * picked on the map. The pick is shared with the map and the chat.
 */
export default function PlaceFinder() {
  const app = useApp();
  const t = useT();
  const pathname = usePathname();
  const { country } = useSettings();
  const listId = useId();
  const enabled = finderKinds(pathname).length > 0;
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const typed = q.trim();

  useEffect(() => {
    const id = window.setTimeout(() => setTerm(typed), typed ? DEBOUNCE_MS : 0);
    return () => window.clearTimeout(id);
  }, [typed]);

  const sites = useApi<SitesResponse>(enabled && term ? "/sites" : null, { country, q: term || undefined, limit: MAX_RESULTS });

  if (!enabled) return null;

  const picked = app.place && app.place.kind === "site" && app.place.country === country ? app.place : null;
  const showList = open && typed !== "";
  const waiting = term !== typed || sites.status === "loading";
  const results = !waiting && sites.status === "ready" ? sites.data.sites.slice(0, MAX_RESULTS) : [];

  function pick(index: number) {
    const s = results[index];
    if (!s) return;
    app.setPlace({
      kind: "site",
      id: s.id,
      name: s.name,
      country: s.limit_country ?? country,
      latitude: s.latitude,
      longitude: s.longitude,
      detail: siteDetail(s.ui_status, t),
    });
    setQ("");
    setOpen(false);
    setActive(-1);
    app.setSidebarOpen(false);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      setActive(-1);
    } else if (e.key === "ArrowDown" && results.length > 0) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp" && results.length > 0) {
      e.preventDefault();
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1));
    } else if (e.key === "Enter" && showList && results.length > 0) {
      e.preventDefault();
      pick(active >= 0 ? active : 0);
    }
  }

  return (
    <div
      data-testid="place-finder"
      className="relative"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <label htmlFor="place-search" className="mb-1 block text-xs font-medium uppercase tracking-wide text-muted">
        {t("Site")}
      </label>
      <input
        id="place-search"
        type="search"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
        value={q}
        onChange={(e) => {
          setQ(e.target.value.slice(0, 64));
          setOpen(true);
          setActive(-1);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={t("Search by name")}
        autoComplete="off"
        className="w-full rounded-lg border border-line bg-surface px-3 py-2"
      />
      {picked ? (
        <div data-testid="picked-place" className="mt-1 flex items-center justify-between gap-2 rounded-lg bg-line/40 px-3 py-1.5 text-sm">
          <span className="min-w-0 truncate font-medium">{picked.name}</span>
          <button type="button" onClick={() => app.setPlace(null)} className="shrink-0 text-xs text-muted underline">
            {t("Clear")}
          </button>
        </div>
      ) : null}
      {showList ? (
        <div data-testid="place-suggestions" className="absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded-lg border border-line bg-surface text-sm shadow-md">
          {waiting ? (
            <p role="status" className="px-3 py-2 text-xs text-muted">{t("Loading places")}</p>
          ) : sites.status === "error" ? (
            <p role="alert" className="px-3 py-2 text-xs text-bad-ink">{t("Places could not be loaded.")}</p>
          ) : results.length === 0 ? (
            <p data-testid="no-places" className="px-3 py-2 text-xs text-muted">{t("No places match.")}</p>
          ) : (
            <ul id={listId} role="listbox" aria-label={t("Places")}>
              {results.map((s, i) => (
                <li
                  key={s.id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => pick(i)}
                  className={`flex cursor-pointer items-center gap-2 border-t border-line px-3 py-2 first:border-t-0 ${i === active ? "bg-sidebar" : ""}`}
                >
                  <span className="min-w-0 flex-1 truncate">
                    <Highlighted text={s.name} query={typed} />
                  </span>
                  {s.latitude === null ? <span className="shrink-0 text-xs text-muted">{t("no location")}</span> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
