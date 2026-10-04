"use client";

import { useT } from "@/lib/i18n";

/** Last-resort boundary: plain wording, no error details (they may name server internals). */
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useT();
  return (
    <div role="alert" className="mx-auto max-w-md space-y-3 p-8 text-center">
      <h1 className="text-lg font-semibold">{t("Something went wrong")}</h1>
      <p className="text-sm text-muted">{t("The page could not be shown. Your questions are kept until you reload.")}</p>
      <button type="button" onClick={reset} className="rounded-lg border border-line px-4 py-2 hover:bg-sidebar">
        {t("Try again")}
      </button>
    </div>
  );
}
