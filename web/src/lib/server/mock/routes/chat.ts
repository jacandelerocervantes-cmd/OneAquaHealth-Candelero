import { MOCK_DISCLAIMER, MOCK_NOTICE, freshness } from "../data";
import { type MockResult, ok, err } from "../common";
import type { ChatRequest, ChatResponse } from "@/lib/api";

const ES: Record<string, string> = {
  "es-MX": "El fósforo total medio en Mock River Alpha fue de 0.06 mg/L en 2024 (12 valores mensuales). Valores de demostración simulados.",
  "es-ES": "El fósforo total medio en Mock River Alpha fue de 0.06 mg/L en 2024 (12 valores mensuales). Valores de demostración simulados.",
};

const EN_ANSWER =
  "Mean total phosphorus at Mock River Alpha was 0.06 mg/L in 2024 (12 monthly values). These are simulated demo values, not measurements.";

const baseChat = (req: ChatRequest): ChatResponse => ({
  status: "answered",
  answer: EN_ANSWER,
  answer_en: null,
  cached: false,
  citations: [
    { tool: "get_site_measurements", site_id: "mock-gr-001", parameter: "Total phosphorus", value: 0.06, unit: "mg/L", period_start: "2024-01-01", period_end: "2024-12-31", source: "mock", limit_basis: null },
  ],
  country: req.country ?? null,
  data_freshness: freshness,
  disclaimer: MOCK_DISCLAIMER,
  evidence: null,
  evidence_truncated: false,
  grounded: true,
  index: req.index ?? null,
  input_notes: [],
  language: req.language ?? "en",
  model: "mock",
  notices: { mock: MOCK_NOTICE },
  origin: "synthetic",
  output_flags: [],
  steps: [{ step: 1, tool: "get_site_measurements", arguments: { site_id: "mock-gr-001", parameter: "Total phosphorus" }, ok: true, summary: "12 monthly values for 2024 (mock)." }],
  translated: false,
  translation_checks: null,
  translation_reasons: [],
  translation_status: "not-needed",
  ungrounded_numbers: [],
  unit_mismatches: [],
  unsafe: false,
  usage: { input_tokens: 0, output_tokens: 0, model_calls: 0, max_steps: 6 },
});

/**
 * Scripted chat for the demo. Markers in the message pick a scenario so every interface state
 * can be seen offline: [mock:429] [mock:error] [mock:withheld] [mock:ungrounded] [mock:unsafe] [mock:no-answer].
 */
export function chat(req: ChatRequest): MockResult {
  const message = req.message ?? "";
  if (message.includes("[mock:429]")) return err(429, "Too many requests. Try again later.", { "Retry-After": "20" });
  if (message.includes("[mock:error]")) return err(502, "The model service is unavailable (mock).");
  const res = baseChat(req);
  const lang = req.language ?? "en";
  if (message.includes("[mock:withheld]") || message.includes("[mock:ungrounded]")) {
    const ungrounded = message.includes("[mock:ungrounded]");
    return ok({
      ...res,
      status: ungrounded ? "withheld-ungrounded" : "withheld",
      answer: null,
      grounded: false,
      ungrounded_numbers: ungrounded ? ["0.9"] : [],
      output_flags: ungrounded ? [] : ["leaks-instructions"],
      evidence: [
        {
          tool: "get_site_measurements",
          scope: { type: "site", id: "mock-gr-001", name: "Mock River Alpha" },
          parameter: "Total phosphorus",
          unit: "mg/L",
          period: "2021-2024",
          origin: "synthetic",
          data_kind: "mock",
          attribution: "Mock data.",
          values: [0.06, 0.063, 0.066, 0.069].map((value, i) => ({ value, period: String(2021 + i), statistic: "mean", n: 12 })),
        },
      ],
    } satisfies ChatResponse);
  }
  if (message.includes("[mock:unsafe]")) return ok({ ...res, unsafe: true, answer: "UNSAFE MOCK TEXT THAT MUST NEVER BE RENDERED", output_flags: ["unsafe"] } satisfies ChatResponse);
  if (message.includes("[mock:no-answer]")) return ok({ ...res, status: "no-answer", answer: null, grounded: false, citations: [], steps: [] } satisfies ChatResponse);
  if (lang !== "en") {
    return ok({
      ...res,
      answer: ES[lang] ?? `(mock translation into ${lang}) ${EN_ANSWER}`,
      answer_en: EN_ANSWER,
      translated: true,
      translation_status: "ok",
      translation_checks: "neutral-and-denylist",
    } satisfies ChatResponse);
  }
  return ok(res);
}

