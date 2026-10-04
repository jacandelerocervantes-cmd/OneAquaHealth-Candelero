"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n";

export default function NotFound() {
  const t = useT();
  return (
    <div className="mx-auto max-w-md space-y-3 p-8 text-center">
      <h1 className="text-lg font-semibold">{t("Page not found")}</h1>
      <p className="text-sm text-muted">{t("There is nothing at this address.")}</p>
      <Link href="/" className="inline-block rounded-lg border border-line px-4 py-2 hover:bg-sidebar">
        {t("Start a new question")}
      </Link>
    </div>
  );
}
