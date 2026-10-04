"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { Schema } from "@/lib/api";
import { ApiError, deadlineFrom, describeError } from "@/lib/client/api";
import { KIND_DOT, originInfo } from "@/lib/constants";
import { formatDate } from "@/lib/format";

/** Every text below is a React text node: nothing here parses HTML or markdown. */

export function OriginBadge({ origin }: { origin: string }) {
  const info = originInfo(origin);
  const tone =
    info.kind === "synthetic"
      ? "bg-mock-bg text-mock-ink"
      : info.kind === "external"
        ? "bg-warn-bg text-warn-ink"
        : "bg-ok-bg text-ok-ink";
  return (
    <span title={info.hint} data-testid="origin-badge" data-origin={origin} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${tone}`}>
      <span aria-hidden className={`h-2 w-2 rounded-full ${KIND_DOT[info.kind]}`} />
      {info.label}
    </span>
  );
}

const FRESHNESS_LABEL: Record<Schema<"DataFreshnessModel">["status"], string> = {
  live: "Live",
  snapshot: "Snapshot",
  "snapshot-stale": "Stale snapshot",
  unknown: "Freshness unknown",
};

export function FreshnessBadge({ freshness }: { freshness: Schema<"DataFreshnessModel"> }) {
  const stale = freshness.status === "snapshot-stale" || freshness.status === "unknown";
  return (
    <span data-testid="freshness-badge" className={`inline-flex rounded-full px-2.5 py-0.5 text-xs ${stale ? "bg-warn-bg text-warn-ink" : "bg-sidebar text-muted"}`}>
      {FRESHNESS_LABEL[freshness.status]}
      {freshness.as_of ? ` · as of ${formatDate(freshness.as_of)}` : ""}
    </span>
  );
}

export function Pill({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "ok" | "warn" | "bad" }) {
  const cls = { plain: "bg-sidebar text-muted", ok: "bg-ok-bg text-ok-ink", warn: "bg-warn-bg text-warn-ink", bad: "bg-bad-bg text-bad-ink" }[tone];
  return <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs ${cls}`}>{children}</span>;
}

export function Notice({ children, tone = "warn", title }: { children: ReactNode; tone?: "warn" | "bad" | "info"; title?: string }) {
  const cls = { warn: "bg-warn-bg text-warn-ink", bad: "bg-bad-bg text-bad-ink", info: "bg-sidebar text-ink" }[tone];
  return (
    <div role={tone === "bad" ? "alert" : "note"} className={`rounded-lg px-3 py-2 text-sm ${cls}`}>
      {title ? <p className="font-medium">{title}</p> : null}
      <div>{children}</div>
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" data-testid="loading" className="space-y-2 py-2">
      <span className="sr-only">{label}</span>
      <div className="h-3 w-2/3 animate-pulse rounded bg-line" />
      <div className="h-3 w-1/2 animate-pulse rounded bg-line" />
      <div className="h-3 w-3/4 animate-pulse rounded bg-line" />
    </div>
  );
}

/** Seconds left until `retryAt`, ticking once per second; 0 when there is nothing to wait for. */
export function useCountdown(retryAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (retryAt === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [retryAt]);
  if (retryAt === null) return 0;
  return Math.max(0, Math.ceil((retryAt - now) / 1000));
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const retryAfter = error instanceof ApiError && error.status === 429 ? error.retryAfter : null;
  const [retryAt] = useState(() => (retryAfter ? deadlineFrom(retryAfter) : null));
  const left = useCountdown(retryAt);
  const waiting = left > 0;
  const message = describeError(error);
  return (
    <div role="alert" data-testid="error-box" className="rounded-lg bg-bad-ink/0 px-3 py-3 text-sm ring-1 ring-bad-ink/30">
      <p className="font-medium text-bad-ink">{message}</p>
      {waiting ? <p data-testid="retry-countdown" className="mt-1 text-muted">Retry available in {left} s.</p> : null}
      {onRetry ? (
        <button type="button" onClick={onRetry} disabled={waiting} className="mt-2 rounded-md border border-line px-3 py-1 text-sm hover:bg-sidebar disabled:opacity-50">
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div data-testid="empty-state" className="rounded-lg border border-dashed border-line px-4 py-8 text-center">
      <p className="font-medium">{title}</p>
      {children ? <div className="mt-1 text-sm text-muted">{children}</div> : null}
    </div>
  );
}

/** Renders loading, error (including 429 with a countdown) and ready states of a `useApi` result. */
export function Async<T>({
  state,
  children,
  isEmpty,
  empty,
}: {
  state: { status: "loading" } | { status: "error"; error: unknown; reload?: () => void } | { status: "ready"; data: T };
  children: (data: T) => ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
}) {
  if (state.status === "loading") return <Loading />;
  if (state.status === "error") return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (isEmpty?.(state.data)) return <>{empty ?? <EmptyState title="Nothing to show" />}</>;
  return <>{children(state.data)}</>;
}

export function Disclosure({
  title,
  children,
  defaultOpen = false,
  testId,
  verified = false,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  testId?: string;
  /** Amber marker used for the "Sources and method" block: the answer carries its evidence. */
  verified?: boolean;
}) {
  return (
    <details open={defaultOpen} data-testid={testId} className={`group rounded-lg border bg-surface ${verified ? "border-verified-line" : "border-line"}`}>
      <summary className={`cursor-pointer select-none px-3 py-2 text-sm font-medium ${verified ? "rounded-t-lg bg-verified-bg text-verified-ink" : ""}`}>{title}</summary>
      <div className="space-y-2 border-t border-line px-3 py-3 text-sm">{children}</div>
    </details>
  );
}

export interface Column<R> {
  header: string;
  cell: (row: R) => ReactNode;
  align?: "right";
}

export function DataTable<R>({ columns, rows, caption }: { columns: Column<R>[]; rows: R[]; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-sidebar text-xs uppercase tracking-wide text-muted">
          <tr>
            {columns.map((c) => (
              <th key={c.header} scope="col" className={`px-3 py-2 font-medium ${c.align === "right" ? "text-right" : ""}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-line">
              {columns.map((c) => (
                <td key={c.header} className={`px-3 py-2 align-top ${c.align === "right" ? "text-right tabular-nums" : ""}`}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function KeyValues({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
