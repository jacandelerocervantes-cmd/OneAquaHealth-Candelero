"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ChatIndex, ChatRequest, LanguagesResponse } from "@/lib/api";
import { ApiError, apiChat, deadlineFrom, describeError } from "@/lib/client/api";
import { useApp, type ChatMessage, type ErrorMessage } from "@/lib/client/app-context";
import { updateSettings, useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { MAX_HISTORY_TURNS, MAX_MESSAGE_LENGTH, SUGGESTIONS } from "@/lib/constants";
import { AnswerCard } from "./answer";
import { EmptyState, Loading, useCountdown } from "./ui";

let counter = 0;
const nextId = () => `m${(counter += 1)}`;

/** Build the history the backend accepts: at most 6 plain-text turns, each at most 500 characters. */
export function buildHistory(messages: ChatMessage[]): NonNullable<ChatRequest["history"]> {
  const turns: NonNullable<ChatRequest["history"]> = [];
  for (const m of messages) {
    if (m.role === "user") turns.push({ role: "user", text: m.text.slice(0, MAX_MESSAGE_LENGTH) });
    else if (m.role === "assistant" && m.response.status === "answered" && !m.response.unsafe) {
      const text = (m.response.answer_en ?? m.response.answer ?? "").trim();
      if (text) turns.push({ role: "assistant", text: text.slice(0, MAX_MESSAGE_LENGTH) });
    }
  }
  return turns.slice(-MAX_HISTORY_TURNS);
}

/** The prefix that carries a picked place into the next question (the contract has no site field). */
export function contextPrefix(place: { name: string; id: string } | null): string {
  return place ? `About ${place.name} (${place.id}): ` : "";
}

interface Props {
  chatKey: string;
  country: string;
  chatIndex: ChatIndex | null;
  indexId: string | null;
}

export function ChatView({ chatKey, country, chatIndex, indexId }: Props) {
  const app = useApp();
  const settings = useSettings();
  const languages = useApi<LanguagesResponse>("/languages");
  const messages = app.getChat(chatKey);
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);

  const lastError = [...messages].reverse().find((m): m is ErrorMessage => m.role === "error");
  const waitLeft = useCountdown(lastError?.retryAt ?? null);
  const blocked = waitLeft > 0;

  const prefix = contextPrefix(app.place);
  const maxLength = Math.max(1, MAX_MESSAGE_LENGTH - prefix.length);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, pending]);
  useEffect(() => () => abort.current?.abort(), []);

  // The download button saves the data behind the latest answer (never the answer text itself).
  const { setExportPayload } = app;
  const latest = [...messages].reverse().find((m) => m.role === "assistant");
  const latestResponse = latest && latest.role === "assistant" ? latest.response : null;
  useEffect(() => {
    setExportPayload(
      latestResponse
        ? {
            filename: "answer-data.json",
            data: {
              origin: latestResponse.origin,
              data_freshness: latestResponse.data_freshness,
              citations: latestResponse.citations,
              evidence: latestResponse.evidence ?? null,
              steps: latestResponse.steps,
              disclaimer: latestResponse.disclaimer,
            },
          }
        : null,
    );
    return () => setExportPayload(null);
  }, [latestResponse, setExportPayload]);

  async function submit(raw: string, fromRetry = false) {
    const question = raw.trim();
    if (!question || pending || blocked) return;
    const full = (fromRetry ? "" : prefix) + question;
    const prior = messages.filter((m) => m.role !== "error");
    // On a retry the question is already the last user message: keep it out of the history.
    const history = buildHistory(fromRetry && prior.at(-1)?.role === "user" ? prior.slice(0, -1) : prior);
    const userMessage: ChatMessage = {
      id: nextId(),
      role: "user",
      text: question,
      context: !fromRetry && app.place ? `${app.place.name} (${app.place.id})` : undefined,
      language: settings.language,
    };
    if (!fromRetry) app.setChat(chatKey, (prev) => [...prev, userMessage]);
    setText("");
    setPending(true);
    const controller = new AbortController();
    abort.current = controller;
    try {
      const body: ChatRequest = { message: full.slice(0, MAX_MESSAGE_LENGTH), country, language: settings.language, history };
      if (chatIndex) body.index = chatIndex;
      const response = await apiChat(body, controller.signal);
      app.setChat(chatKey, (prev) => [...prev.filter((m) => m.role !== "error"), { id: nextId(), role: "assistant", response }]);
    } catch (error) {
      if ((error as { name?: string }).name === "AbortError") return;
      const retryAfter = error instanceof ApiError && error.status === 429 ? error.retryAfter : null;
      const failure: ErrorMessage = {
        id: nextId(),
        role: "error",
        status: error instanceof ApiError ? error.status : 0,
        text: describeError(error),
        retryAt: retryAfter ? deadlineFrom(retryAfter) : null,
        retryText: full,
      };
      app.setChat(chatKey, (prev) => [...prev.filter((m) => m.role !== "error"), failure]);
    } finally {
      setPending(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(text);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit(text);
    }
  }

  const languageList = languages.status === "ready" ? languages.data.languages : [];
  const languageLabel = (code: string) => languageList.find((l) => l.code === code)?.endonym ?? code;
  const suggestions = SUGGESTIONS[indexId ?? "default"] ?? SUGGESTIONS.default ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6" data-testid="conversation">
          {messages.length === 0 && !pending ? (
            <EmptyState title="Ask a question about the water data">
              <p>Answers are written from the data the service returns, with their sources.</p>
              <ul className="mt-3 flex flex-col items-center gap-2">
                {suggestions.map((s) => (
                  <li key={s}>
                    <button type="button" onClick={() => setText(s)} className="rounded-full border border-line px-3 py-1 text-sm hover:bg-sidebar">
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </EmptyState>
          ) : null}

          {messages.map((m) => {
            if (m.role === "user") {
              return (
                <div key={m.id} data-testid="user-message" className="ml-auto max-w-[85%] rounded-2xl bg-sidebar px-4 py-2">
                  {m.context ? <p className="text-xs text-muted">Context: {m.context}</p> : null}
                  <p className="whitespace-pre-wrap break-words">{m.text}</p>
                </div>
              );
            }
            if (m.role === "assistant") {
              return <AnswerCard key={m.id} response={m.response} languageLabel={languageLabel(m.response.language)} />;
            }
            return (
              <div key={m.id} role="alert" data-testid="chat-error" className="rounded-lg px-3 py-3 text-sm ring-1 ring-bad-ink/30">
                <p className="font-medium text-bad-ink">{m.text}</p>
                {m.status === 429 ? (
                  <p data-testid="retry-countdown" className="mt-1 text-muted">
                    {waitLeft > 0 ? `You can send again in ${waitLeft} s.` : "You can send again now."}
                  </p>
                ) : null}
                {m.retryText ? (
                  <button
                    type="button"
                    disabled={pending || (m.status === 429 && waitLeft > 0)}
                    onClick={() => void submit(m.retryText ?? "", true)}
                    className="mt-2 rounded-md border border-line px-3 py-1 hover:bg-sidebar disabled:opacity-50"
                  >
                    Try again
                  </button>
                ) : null}
              </div>
            );
          })}

          {pending ? (
            <div data-testid="chat-pending" className="rounded-xl border border-line bg-surface px-4 py-3">
              <Loading label="Waiting for the answer" />
            </div>
          ) : null}
          <div ref={bottom} />
        </div>
      </div>

      <form onSubmit={onSubmit} className="border-t border-line bg-canvas px-4 py-3">
        <div className="mx-auto max-w-3xl space-y-2">
          {app.place ? (
            <div data-testid="context-chip" className="flex items-center gap-2 text-xs">
              <span className="rounded-full bg-sidebar px-2.5 py-1">Context: {app.place.name}</span>
              <button type="button" onClick={() => app.setPlace(null)} className="text-muted underline">
                Remove
              </button>
            </div>
          ) : null}
          <div className="rounded-2xl border border-line bg-surface p-2">
            <label htmlFor="question" className="sr-only">
              Your question
            </label>
            <textarea
              id="question"
              value={text}
              onChange={(e) => setText(e.target.value.slice(0, maxLength))}
              onKeyDown={onKeyDown}
              rows={2}
              maxLength={maxLength}
              placeholder="Ask about the data for the selected country"
              className="w-full resize-none bg-transparent px-2 py-1 outline-none"
            />
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <label htmlFor="language" className="sr-only">
                  Answer language
                </label>
                <select
                  id="language"
                  data-testid="language-select"
                  value={settings.language}
                  onChange={(e) => updateSettings({ language: e.target.value })}
                  className="max-w-[12rem] rounded-full border border-line bg-surface px-3 py-1 text-sm"
                >
                  {languageList.length === 0 ? <option value={settings.language}>{settings.language}</option> : null}
                  {languageList.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.endonym}
                    </option>
                  ))}
                </select>
                <span className="text-xs text-muted">{text.length}/{maxLength}</span>
              </div>
              <button
                type="submit"
                disabled={pending || blocked || !text.trim()}
                className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-ink disabled:opacity-50"
              >
                {blocked ? `Wait ${waitLeft} s` : "Send"}
              </button>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
