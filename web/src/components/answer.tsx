"use client";

import { useState } from "react";
import type { ChatResponse } from "@/lib/api";
import { FALLBACK_DISCLAIMER, FRESHNESS_LABEL, originInfo } from "@/lib/constants";
import { formatNumber, humanise } from "@/lib/format";
import { msg, useT } from "@/lib/i18n";
import { RichText } from "./rich-text";
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
    title: msg("Answer withheld"),
    body: msg("An automatic check stopped this answer, so it is not shown. The data the assistant consulted is listed below."),
  },
  "withheld-ungrounded": {
    tone: "warn",
    title: msg("Answer withheld: not grounded"),
    body: msg("The answer contained numbers or units that could not be matched to the data it consulted, so it is not shown. The data that was consulted is listed below."),
  },
  blocked: {
    tone: "bad",
    title: msg("Answer blocked"),
    body: msg("A safety check marked this answer unsafe, so it is not shown."),
  },
  "no-answer": {
    tone: "info",
    title: msg("No answer"),
    body: msg("No answer could be produced from the data available for this question."),
  },
  "budget-exceeded": {
    tone: "info",
    title: msg("Question budget used"),
    body: msg("The question budget of this demo has been used for now. Please try again later."),
  },
};

function EvidenceBlock({ items, truncated }: { items: NonNullable<ChatResponse["evidence"]>; truncated: boolean }) {
  const t = useT();
  return (
    <section data-testid="evidence" aria-label={t("Evidence")} className="space-y-2 rounded-lg border border-line bg-surface px-3 py-3 text-sm">
      <h3 className="font-medium">{t("Evidence: data the assistant consulted")}</h3>
      {items.map((item, i) => (
        <div key={i} className="space-y-1 border-t border-line pt-2 first:border-t-0 first:pt-0">
          <p>
            <span className="font-medium">{item.scope.name ?? item.scope.id ?? humanise(item.scope.type)}</span>
            {item.parameter ? ` · ${item.parameter}` : ""}
            {item.unit ? ` · ${item.unit}` : ""}
            {item.period ? ` · ${item.period}` : ""}
          </p>
          <p className="text-xs text-muted">
            {t("Tool {name}", { name: item.tool })}
            {item.origin ? ` · ${t(originInfo(item.origin).label)}` : ""}
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
              {item.summary.first_period && item.summary.last_period
                ? t("Observed range {min} to {max} over {n} values, {first} to {last}.", {
                    min: formatNumber(item.summary.minimum), max: formatNumber(item.summary.maximum), n: item.summary.n,
                    first: item.summary.first_period, last: item.summary.last_period,
                  })
                : t("Observed range {min} to {max} over {n} values.", {
                    min: formatNumber(item.summary.minimum), max: formatNumber(item.summary.maximum), n: item.summary.n,
                  })}
              <span className="text-muted"> {t("An observed range, not a statistical interval.")}</span>
            </p>
          ) : null}
          {item.attribution ? <p className="text-xs text-muted">{item.attribution}</p> : null}
        </div>
      ))}
      {truncated ? <p className="text-xs text-muted">{t("More values were consulted than are listed here.")}</p> : null}
    </section>
  );
}

function unique(values: (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((v): v is string => typeof v === "string" && v !== ""))];
}

/** "Sources and method": filled only from the metadata the routes returned, never written by the model. */
export function SourcesAndMethod({ response }: { response: ChatResponse }) {
  const t = useT();
  const own = t(originInfo(response.origin).label);
  const sources = unique(response.citations.map((c) => (c.source ? t(originInfo(c.source).label) : null))).filter((s) => s !== own);
  const attributions = unique((response.evidence ?? []).map((e) => e.attribution));
  const limits = unique(response.citations.map((c) => c.limit_basis));
  const notices = Object.entries(response.notices);
  const flags = [
    ...response.input_notes.map((n) => t("Input: {value}", { value: n })),
    ...response.output_flags.map((f) => t("Check: {value}", { value: f })),
    ...response.unit_mismatches.map((u) => t("Unit mismatch: {value}", { value: u })),
    ...response.ungrounded_numbers.map((n) => t("Ungrounded number: {value}", { value: n })),
  ];
  return (
    <Disclosure title={t("Sources and method")} testId="sources-and-method" verified>
      <section aria-label={t("Data source and licence")}>
        <h3 className="mb-1 font-medium">{t("Data source and licence")}</h3>
        <ul className="list-disc space-y-0.5 pl-5">
          <li>{own}</li>
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
      <section aria-label={t("Method")}>
        <h3 className="mb-1 font-medium">{t("Method")}</h3>
        <p className="text-muted">
          {t("The answer is written from the tool results listed here. Numbers and units are checked against them before an answer is shown.")}
        </p>
        {response.steps.length ? (
          <ol className="mt-1 list-decimal space-y-0.5 pl-5">
            {response.steps.map((s) => (
              <li key={s.step}>
                {humanise(s.tool)}: {s.summary}
                {s.ok ? "" : ` ${t("(failed)")}`}
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-1 text-muted">{t("No tool was consulted.")}</p>
        )}
      </section>
      <section aria-label={t("Limits")}>
        <h3 className="mb-1 font-medium">{t("Limits")}</h3>
        {limits.length ? (
          <ul className="list-disc space-y-0.5 pl-5">
            {limits.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">{t("No reference value was applied to this answer.")}</p>
        )}
        <p className="mt-1 text-muted">{t("Reference values are screening aids. This is not a compliance assessment.")}</p>
      </section>
      <section aria-label={t("Coverage flags")}>
        <h3 className="mb-1 font-medium">{t("Coverage and flags")}</h3>
        <KeyValues
          items={[
            [t("Data freshness"), `${t(FRESHNESS_LABEL[response.data_freshness.status] ?? response.data_freshness.status)}${response.data_freshness.as_of ? `, ${t("as of {date}", { date: response.data_freshness.as_of.slice(0, 10) })}` : ""}`],
            [t("Served from cache"), response.cached ? t("yes") : t("no")],
            [t("Language"), `${response.language}${response.translated ? ` ${t("(translation: {status})", { status: response.translation_status })}` : ""}`],
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
          <p className="mt-1 text-muted">{t("Translation checks: {list}", { list: response.translation_reasons.join(", ") })}</p>
        ) : null}
      </section>
    </Disclosure>
  );
}

export function AnswerCard({ response, languageLabel }: { response: ChatResponse; languageLabel?: string }) {
  const t = useT();
  const state = answerState(response);
  const text = visibleAnswer(response);
  const [showOriginal, setShowOriginal] = useState(true);
  const showEnglish = response.translated && typeof response.answer_en === "string" && response.answer_en.trim() && state === "answered";
  const translationFailed = response.translation_status === "rejected" || response.translation_status === "failed";
  const evidence = state === "withheld" || state === "withheld-ungrounded" ? response.evidence : null;

  return (
    <article data-testid="answer-card" data-state={state} className="space-y-3 rounded-xl border border-line bg-surface px-4 py-4">
      <h2 className="sr-only">{t("Answer")}</h2>
      <header className="flex flex-wrap items-center gap-2">
        <OriginBadge origin={response.origin} />
        <Pill tone={response.grounded ? "ok" : "warn"}>{response.grounded ? t("Grounded") : t("Not grounded")}</Pill>
        <FreshnessBadge freshness={response.data_freshness} />
        <Pill>{languageLabel ?? response.language}</Pill>
        {response.cached ? <Pill>{t("Cached")}</Pill> : null}
      </header>

      {state !== "answered" ? (
        <Notice tone={STATE_NOTICE[state].tone} title={t(STATE_NOTICE[state].title)}>
          {t(STATE_NOTICE[state].body)}
          {state === "withheld-ungrounded" && response.ungrounded_numbers.length ? (
            <span> {t("Numbers not found in the data: {list}.", { list: response.ungrounded_numbers.join(", ") })}</span>
          ) : null}
        </Notice>
      ) : null}

      {state === "answered" && !text ? <Notice tone="info">{t("The answer is empty.")}</Notice> : null}

      {text ? (
        <div className="space-y-2">
          {translationFailed ? (
            <Notice tone="info">{t("The translation did not pass the checks, so the answer is shown in English.")}</Notice>
          ) : null}
          {showEnglish ? (
            <>
              <button type="button" onClick={() => setShowOriginal((v) => !v)} className="text-xs text-accent underline">
                {showOriginal ? t("Hide English original") : t("Show English original")}
              </button>
              <div className={`grid gap-3 ${showOriginal ? "md:grid-cols-2" : ""}`}>
                <div>
                  <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{t("Translation ({code})", { code: response.language })}</h3>
                  <RichText testId="answer-text" text={text} />
                </div>
                {showOriginal ? (
                  <div className="rounded-lg bg-sidebar px-3 py-2">
                    <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{t("English original")}</h3>
                    <RichText testId="answer-original" text={response.answer_en ?? ""} />
                  </div>
                ) : null}
              </div>
            </>
          ) : (
            <RichText testId="answer-text" text={text} />
          )}
        </div>
      ) : null}

      {evidence && evidence.length ? <EvidenceBlock items={evidence} truncated={Boolean(response.evidence_truncated)} /> : null}

      <SourcesAndMethod response={response} />

      <footer data-testid="disclaimer" className="border-t border-line pt-2 text-xs text-muted">
        {response.disclaimer || t(FALLBACK_DISCLAIMER)}
      </footer>
    </article>
  );
}
