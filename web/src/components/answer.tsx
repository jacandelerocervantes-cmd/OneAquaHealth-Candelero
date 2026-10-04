"use client";

import { useState } from "react";
import type { ChatResponse } from "@/lib/api";
import { FALLBACK_DISCLAIMER, originInfo } from "@/lib/constants";
import { formatNumber, humanise } from "@/lib/format";
import { Disclosure, FreshnessBadge, KeyValues, Notice, OriginBadge, Pill } from "./ui";

export type AnswerState = "answered" | "withheld" | "withheld-ungrounded" | "no-answer" | "budget-exceeded" | "blocked";

/**
 * What the interface may show. An answer marked `unsafe` is never rendered, whatever its status;
 * a withheld answer is never rendered even when the server sent text with it.
 */
export function answerState(response: ChatResponse): AnswerState {
  if (response.unsafe) return "blocked";
  return response.status;
}

/** The text that may be shown, or null. Only an answered, non-unsafe response has any. */
export function visibleAnswer(response: ChatResponse): string | null {
  return answerState(response) === "answered" && typeof response.answer === "string" && response.answer.trim() ? response.answer : null;
}

const STATE_NOTICE: Record<Exclude<AnswerState, "answered">, { tone: "warn" | "bad" | "info"; title: string; body: string }> = {
  withheld: {
    tone: "warn",
    title: "Answer withheld",
    body: "An automatic check stopped this answer, so it is not shown. The data the assistant consulted is listed below.",
  },
  "withheld-ungrounded": {
    tone: "warn",
    title: "Answer withheld: not grounded",
    body: "The answer contained numbers or units that could not be matched to the data it consulted, so it is not shown. The data that was consulted is listed below.",
  },
  blocked: {
    tone: "bad",
    title: "Answer blocked",
    body: "A safety check marked this answer unsafe, so it is not shown.",
  },
  "no-answer": {
    tone: "info",
    title: "No answer",
    body: "No answer could be produced from the data available for this question.",
  },
  "budget-exceeded": {
    tone: "info",
    title: "Question budget used",
    body: "The question budget of this demo has been used for now. Please try again later.",
  },
};

function EvidenceBlock({ items, truncated }: { items: NonNullable<ChatResponse["evidence"]>; truncated: boolean }) {
  return (
    <section data-testid="evidence" aria-label="Evidence" className="space-y-2 rounded-lg border border-line bg-surface px-3 py-3 text-sm">
      <h3 className="font-medium">Evidence: data the assistant consulted</h3>
      {items.map((item, i) => (
        <div key={i} className="space-y-1 border-t border-line pt-2 first:border-t-0 first:pt-0">
          <p>
            <span className="font-medium">{item.scope.name ?? item.scope.id ?? humanise(item.scope.type)}</span>
            {item.parameter ? ` · ${item.parameter}` : ""}
            {item.unit ? ` · ${item.unit}` : ""}
            {item.period ? ` · ${item.period}` : ""}
          </p>
          <p className="text-xs text-muted">
            Tool {item.tool}
            {item.origin ? ` · ${originInfo(item.origin).label}` : ""}
            {item.data_kind ? ` · ${item.data_kind}` : ""}
          </p>
          {item.values ? (
            <ul className="flex flex-wrap gap-2">
              {item.values.map((v, j) => (
                <li key={j} className="rounded bg-sidebar px-2 py-0.5 tabular-nums">
                  {v.period ? `${v.period}: ` : ""}
                  {v.comparator ?? ""}
                  {formatNumber(v.value)}
                  {v.n != null ? ` (n=${v.n})` : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {item.summary ? (
            <p className="tabular-nums">
              Observed range {formatNumber(item.summary.minimum)} to {formatNumber(item.summary.maximum)} over {item.summary.n} values
              {item.summary.first_period && item.summary.last_period ? `, ${item.summary.first_period} to ${item.summary.last_period}` : ""}.
              <span className="text-muted"> An observed range, not a statistical interval.</span>
            </p>
          ) : null}
          {item.attribution ? <p className="text-xs text-muted">{item.attribution}</p> : null}
        </div>
      ))}
      {truncated ? <p className="text-xs text-muted">More values were consulted than are listed here.</p> : null}
    </section>
  );
}

function unique(values: (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((v): v is string => typeof v === "string" && v !== ""))];
}

/** "Sources and method": filled only from the metadata the routes returned, never written by the model. */
export function SourcesAndMethod({ response }: { response: ChatResponse }) {
  const sources = unique(response.citations.map((c) => c.source));
  const attributions = unique((response.evidence ?? []).map((e) => e.attribution));
  const limits = unique(response.citations.map((c) => c.limit_basis));
  const notices = Object.entries(response.notices);
  const flags = [
    ...response.input_notes.map((n) => `Input: ${n}`),
    ...response.output_flags.map((f) => `Check: ${f}`),
    ...response.unit_mismatches.map((u) => `Unit mismatch: ${u}`),
    ...response.ungrounded_numbers.map((n) => `Ungrounded number: ${n}`),
  ];
  return (
    <Disclosure title="Sources and method" testId="sources-and-method" verified>
      <section aria-label="Data source and licence">
        <h3 className="mb-1 font-medium">Data source and licence</h3>
        <ul className="list-disc space-y-0.5 pl-5">
          <li>{originInfo(response.origin).label}</li>
          {sources.map((s) => (
            <li key={s}>{s}</li>
          ))}
          {attributions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
        {notices.length ? (
          <ul className="mt-1 space-y-0.5 text-muted">
            {notices.map(([k, v]) => (
              <li key={k}>{v}</li>
            ))}
          </ul>
        ) : null}
      </section>
      <section aria-label="Method">
        <h3 className="mb-1 font-medium">Method</h3>
        <p className="text-muted">
          The answer is written from the tool results listed here. Numbers and units are checked against them before an answer is shown.
        </p>
        {response.steps.length ? (
          <ol className="mt-1 list-decimal space-y-0.5 pl-5">
            {response.steps.map((s) => (
              <li key={s.step}>
                {s.tool}: {s.summary}
                {s.ok ? "" : " (failed)"}
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-1 text-muted">No tool was consulted.</p>
        )}
      </section>
      <section aria-label="Limits">
        <h3 className="mb-1 font-medium">Limits</h3>
        {limits.length ? (
          <ul className="list-disc space-y-0.5 pl-5">
            {limits.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">No reference value was applied to this answer.</p>
        )}
        <p className="mt-1 text-muted">Reference values are screening aids. This is not a compliance assessment.</p>
      </section>
      <section aria-label="Coverage flags">
        <h3 className="mb-1 font-medium">Coverage and flags</h3>
        <KeyValues
          items={[
            ["Data freshness", `${response.data_freshness.status}${response.data_freshness.as_of ? `, as of ${response.data_freshness.as_of}` : ""}`],
            ["Served from cache", response.cached ? "yes" : "no"],
            ["Language", `${response.language}${response.translated ? ` (translation: ${response.translation_status})` : ""}`],
          ]}
        />
        {flags.length ? (
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {flags.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        ) : null}
        {response.translation_reasons.length ? (
          <p className="mt-1 text-muted">Translation checks: {response.translation_reasons.join(", ")}</p>
        ) : null}
      </section>
    </Disclosure>
  );
}

export function AnswerCard({ response, languageLabel }: { response: ChatResponse; languageLabel?: string }) {
  const state = answerState(response);
  const text = visibleAnswer(response);
  const [showOriginal, setShowOriginal] = useState(true);
  const showEnglish = response.translated && typeof response.answer_en === "string" && response.answer_en.trim() && state === "answered";
  const translationFailed = response.translation_status === "rejected" || response.translation_status === "failed";
  const evidence = state === "withheld" || state === "withheld-ungrounded" ? response.evidence : null;

  return (
    <article data-testid="answer-card" data-state={state} className="space-y-3 rounded-xl border border-line bg-surface px-4 py-4">
      <h2 className="sr-only">Answer</h2>
      <header className="flex flex-wrap items-center gap-2">
        <OriginBadge origin={response.origin} />
        <Pill tone={response.grounded ? "ok" : "warn"}>{response.grounded ? "Grounded" : "Not grounded"}</Pill>
        <FreshnessBadge freshness={response.data_freshness} />
        <Pill>{languageLabel ?? response.language}</Pill>
        {response.cached ? <Pill>Cached</Pill> : null}
      </header>

      {state !== "answered" ? (
        <Notice tone={STATE_NOTICE[state].tone} title={STATE_NOTICE[state].title}>
          {STATE_NOTICE[state].body}
          {state === "withheld-ungrounded" && response.ungrounded_numbers.length ? (
            <span> Numbers not found in the data: {response.ungrounded_numbers.join(", ")}.</span>
          ) : null}
        </Notice>
      ) : null}

      {state === "answered" && !text ? <Notice tone="info">The answer is empty.</Notice> : null}

      {text ? (
        <div className="space-y-2">
          {translationFailed ? (
            <Notice tone="info">The translation did not pass the checks, so the answer is shown in English.</Notice>
          ) : null}
          {showEnglish ? (
            <>
              <button type="button" onClick={() => setShowOriginal((v) => !v)} className="text-xs text-accent underline">
                {showOriginal ? "Hide English original" : "Show English original"}
              </button>
              <div className={`grid gap-3 ${showOriginal ? "md:grid-cols-2" : ""}`}>
                <div>
                  <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Translation ({response.language})</h3>
                  <p data-testid="answer-text" className="whitespace-pre-wrap break-words leading-relaxed">{text}</p>
                </div>
                {showOriginal ? (
                  <div className="rounded-lg bg-sidebar px-3 py-2">
                    <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">English original</h3>
                    <p data-testid="answer-original" className="whitespace-pre-wrap break-words leading-relaxed">{response.answer_en}</p>
                  </div>
                ) : null}
              </div>
            </>
          ) : (
            <p data-testid="answer-text" className="whitespace-pre-wrap break-words leading-relaxed">{text}</p>
          )}
        </div>
      ) : null}

      {evidence && evidence.length ? <EvidenceBlock items={evidence} truncated={Boolean(response.evidence_truncated)} /> : null}

      <SourcesAndMethod response={response} />

      <footer data-testid="disclaimer" className="border-t border-line pt-2 text-xs text-muted">
        {response.disclaimer || FALLBACK_DISCLAIMER}
      </footer>
    </article>
  );
}
