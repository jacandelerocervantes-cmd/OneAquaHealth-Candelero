import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildHistory, ChatView, contextPrefix } from "@/components/chat";
import type { ChatMessage } from "@/lib/client/app-context";
import { updateSettings } from "@/lib/client/settings-store";
import { chat } from "@/lib/server/mock/handlers";
import { installProxyFetch, jsonResponse, renderWithApp } from "./helpers";

function view(chatIndex: "microbiology" | null = null) {
  return renderWithApp(<ChatView chatKey="GR:test" country="GR" chatIndex={chatIndex} indexId={chatIndex} />);
}

beforeEach(() => {
  window.localStorage.clear();
  updateSettings({ language: "en", defaultLanguage: "en" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const send = async (text: string) => {
  await userEvent.click(screen.getByLabelText("Your question"));
  await userEvent.paste(text);
  await userEvent.click(screen.getByRole("button", { name: /Send|Wait/ }));
};

describe("ChatView", () => {
  it("shows the empty state with suggestions that fill the input", async () => {
    installProxyFetch();
    view();
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /water-quality|phosphorus/i })[0]!);
    expect((screen.getByLabelText("Your question") as HTMLTextAreaElement).value).toMatch(/\w/);
  });

  it("has no language selector in the question box (the language is chosen in the sidebar)", async () => {
    installProxyFetch();
    view();
    expect(screen.queryByTestId("language-select")).toBeNull();
    expect(screen.getByLabelText("Your question")).toBeInTheDocument();
  });

  it("sends a question, shows a loading state, then the answer card; the request has no key and the right fields", async () => {
    const { calls } = installProxyFetch();
    view("microbiology");
    await send("How is the phosphorus?");
    expect(await screen.findByTestId("answer-card")).toBeInTheDocument();
    expect(screen.getByTestId("user-message")).toHaveTextContent("How is the phosphorus?");
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect(post.url).toBe("/api/oah/chat");
    expect(JSON.parse(post.init!.body as string)).toMatchObject({ message: "How is the phosphorus?", country: "GR", language: "en", index: "microbiology" });
    expect(JSON.stringify(post.init)).not.toMatch(/api-key/i);
  });

  it("shows the pending state while the request is open", async () => {
    let release: (r: Response) => void = () => undefined;
    installProxyFetch((url) => (url.pathname.endsWith("/chat") ? ({ then: (f: (r: Response) => unknown) => new Promise((res) => (release = (r) => res(f(r)))) } as unknown as Response) : undefined));
    view();
    await send("hello");
    expect(await screen.findByTestId("chat-pending")).toBeInTheDocument();
    await act(async () => release(jsonResponse(200, chat({ message: "x" }).body)));
    expect(await screen.findByTestId("answer-card")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-pending")).toBeNull();
  });

  it("handles 429: reads Retry-After, shows a countdown, disables sending and re-enables it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    installProxyFetch();
    view();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByLabelText("Your question"));
    await user.paste("hello [mock:429]");
    await user.click(screen.getByRole("button", { name: "Send" }));
    const alert = await screen.findByTestId("chat-error");
    expect(alert).toHaveTextContent("Too many requests");
    expect(alert).toHaveTextContent("20 s");
    expect(screen.getByTestId("retry-countdown")).toHaveTextContent(/You can send again in \d+ s/);
    await user.type(screen.getByLabelText("Your question"), "again");
    expect(screen.getByRole("button", { name: /Wait \d+ s/ })).toBeDisabled();
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeDisabled();
    await act(async () => {
      vi.advanceTimersByTime(21_000);
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    expect(screen.getByTestId("retry-countdown")).toHaveTextContent("You can send again now");
  });

  it("shows an error state for a server failure and retries without repeating the question", async () => {
    let fail = true;
    installProxyFetch((url) => (url.pathname.endsWith("/chat") && fail ? jsonResponse(502, { detail: "x" }) : undefined));
    view();
    await send("is it ok");
    expect(await screen.findByTestId("chat-error")).toHaveTextContent("The data service is unavailable");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("answer-card")).toBeInTheDocument();
    expect(screen.getAllByTestId("user-message")).toHaveLength(1);
    expect(screen.queryByTestId("chat-error")).toBeNull();
  });

  it("shows a network failure as an error", async () => {
    installProxyFetch(() => {
      throw new TypeError("failed to fetch");
    });
    view();
    await send("hello");
    expect(await screen.findByTestId("chat-error")).toBeInTheDocument();
  });

  it("renders withheld and withheld-ungrounded answers with the evidence block", async () => {
    installProxyFetch();
    view();
    await send("[mock:withheld]");
    expect(await screen.findByTestId("evidence")).toBeInTheDocument();
    expect(screen.queryByTestId("answer-text")).toBeNull();
  });

  it("does not send an empty question", async () => {
    const { fn } = installProxyFetch();
    view();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await waitFor(() => expect(fn).toHaveBeenCalled()); // languages only
    expect(fn.mock.calls.every(([u]) => !String(u).endsWith("/chat"))).toBe(true);
  });

  it("caps the question at the 500 characters the contract allows", async () => {
    installProxyFetch();
    view();
    const box = screen.getByLabelText("Your question") as HTMLTextAreaElement;
    expect(box.maxLength).toBe(500);
  });
});

describe("history and context helpers", () => {
  const user = (text: string): ChatMessage => ({ id: text, role: "user", text, language: "en" });
  const answer = (text: string, status: "answered" | "withheld" = "answered", unsafe = false): ChatMessage => ({
    id: text,
    role: "assistant",
    response: { ...(chat({ message: "x" }).body as never as import("@/lib/api").ChatResponse), status, answer: text, answer_en: null, unsafe },
  });

  it("keeps at most 6 turns, only answered and safe assistant turns, texts cut at 500", () => {
    const messages = [user("1"), answer("a1"), user("2"), answer("hidden", "withheld"), user("3"), answer("unsafe!", "answered", true), user("4"), answer("a4"), user("5"), answer("a5")];
    const history = buildHistory(messages);
    expect(history).toHaveLength(6);
    expect(history.map((t) => t.text)).toEqual(["2", "3", "4", "a4", "5", "a5"]);
    expect(history.some((t) => t.text === "hidden" || t.text === "unsafe!")).toBe(false);
    expect(buildHistory([user("z".repeat(900))])[0]!.text).toHaveLength(500);
  });

  it("prefixes the picked place", () => {
    expect(contextPrefix(null)).toBe("");
    expect(contextPrefix({ name: "Po", id: "IT1" })).toBe("About Po (IT1): ");
  });
});
