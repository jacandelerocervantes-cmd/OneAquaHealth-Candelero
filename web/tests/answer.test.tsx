import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ChatRequest, ChatResponse } from "@/lib/api";
import { AnswerCard, answerState, visibleAnswer } from "@/components/answer";
import { chat } from "@/lib/server/mock/handlers";

const make = (req: Partial<ChatRequest> & { message: string }): ChatResponse => chat({ language: "en", ...req }).body as ChatResponse;

describe("answer states", () => {
  it("shows an answered response with origin, grounded, freshness, sources and the disclaimer", () => {
    const r = make({ message: "hello" });
    render(<AnswerCard response={r} />);
    const card = screen.getByTestId("answer-card");
    expect(card).toHaveAttribute("data-state", "answered");
    expect(screen.getByTestId("answer-text")).toHaveTextContent("Mean total phosphorus");
    expect(screen.getByTestId("origin-badge")).toHaveTextContent("Synthetic");
    expect(screen.getByText("Grounded")).toBeInTheDocument();
    expect(screen.getByTestId("freshness-badge")).toHaveTextContent("Snapshot");
    expect(screen.getByTestId("disclaimer")).toHaveTextContent(r.disclaimer);
    expect(screen.queryByTestId("evidence")).toBeNull();
  });

  it("puts the Sources and method block inside the answer, filled from the response metadata", async () => {
    const r = make({ message: "hello" });
    render(<AnswerCard response={r} />);
    const block = within(screen.getByTestId("answer-card")).getByTestId("sources-and-method");
    await userEvent.click(within(block).getByText("Sources and method"));
    expect(within(block).getByText("Data source and licence")).toBeInTheDocument();
    expect(within(block).getByText("Method")).toBeInTheDocument();
    expect(within(block).getByText("Limits")).toBeInTheDocument();
    expect(within(block).getByText("Coverage and flags")).toBeInTheDocument();
    expect(block).toHaveTextContent("get_site_measurements");
    expect(block).toHaveTextContent("not a compliance assessment");
  });

  it("withholds the text, shows the notice and the evidence block", () => {
    const r = make({ message: "[mock:withheld]" });
    expect(r.answer).toBeNull();
    render(<AnswerCard response={r} />);
    expect(screen.getByTestId("answer-card")).toHaveAttribute("data-state", "withheld");
    expect(screen.getByText("Answer withheld")).toBeInTheDocument();
    expect(screen.queryByTestId("answer-text")).toBeNull();
    const evidence = screen.getByTestId("evidence");
    expect(evidence).toHaveTextContent("Mock River Alpha");
    expect(evidence).toHaveTextContent("Total phosphorus");
    expect(screen.getByText("Not grounded")).toBeInTheDocument();
    expect(screen.getByTestId("disclaimer")).toBeInTheDocument();
  });

  it("never renders text of a withheld response even if the server sent some", () => {
    const r = { ...make({ message: "[mock:withheld]" }), answer: "LEAKED WITHHELD TEXT" } satisfies ChatResponse;
    render(<AnswerCard response={r} />);
    expect(screen.queryByText(/LEAKED WITHHELD TEXT/)).toBeNull();
    expect(visibleAnswer(r)).toBeNull();
  });

  it("shows the ungrounded numbers of a withheld-ungrounded response", () => {
    const r = make({ message: "[mock:ungrounded]" });
    render(<AnswerCard response={r} />);
    expect(screen.getByTestId("answer-card")).toHaveAttribute("data-state", "withheld-ungrounded");
    expect(screen.getByText("Answer withheld: not grounded")).toBeInTheDocument();
    expect(screen.getByText(/Numbers not found in the data: 0\.9/)).toBeInTheDocument();
    expect(screen.getByTestId("evidence")).toBeInTheDocument();
  });

  it("never renders an answer marked unsafe, whatever its status", () => {
    const r = make({ message: "[mock:unsafe]" });
    expect(r.answer).toContain("MUST NEVER BE RENDERED");
    expect(answerState(r)).toBe("blocked");
    render(<AnswerCard response={r} />);
    expect(screen.queryByText(/MUST NEVER BE RENDERED/)).toBeNull();
    expect(screen.getByText("Answer blocked")).toBeInTheDocument();
  });

  it("renders no-answer and budget-exceeded notices", () => {
    const none = make({ message: "[mock:no-answer]" });
    const { unmount } = render(<AnswerCard response={none} />);
    expect(screen.getByText("No answer")).toBeInTheDocument();
    unmount();
    render(<AnswerCard response={{ ...none, status: "budget-exceeded" }} />);
    expect(screen.getByText("Question budget used")).toBeInTheDocument();
  });

  it("shows the English original next to a translation, and can hide it", async () => {
    const r = make({ message: "hola", language: "es-MX" });
    render(<AnswerCard response={r} languageLabel="Español (México)" />);
    expect(screen.getByTestId("answer-text")).toHaveTextContent("fósforo total");
    expect(screen.getByTestId("answer-original")).toHaveTextContent("Mean total phosphorus");
    expect(screen.getByText("English original")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Hide English original"));
    expect(screen.queryByTestId("answer-original")).toBeNull();
  });

  it("explains a rejected translation instead of hiding it", () => {
    const r = { ...make({ message: "hola", language: "es-MX" }), translated: false, answer_en: null, translation_status: "rejected" as const, translation_reasons: ["contains-url"] };
    render(<AnswerCard response={r} />);
    expect(screen.getByText(/did not pass the checks/)).toBeInTheDocument();
  });

  it("renders every text as plain text: markup in an answer or a name is never parsed", () => {
    const r = { ...make({ message: "hello" }), answer: '<img src=x onerror="alert(1)"><script>alert(2)</script> **bold** [l](https://evil.example)' };
    const { container } = render(<AnswerCard response={r} />);
    expect(screen.getByTestId("answer-text").textContent).toContain("<script>alert(2)</script>");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("strong")).toBeNull();
    expect(container.querySelector('a[href="https://evil.example"]')).toBeNull();
  });
});
