"use client";

import { chatKey } from "@/lib/client/app-context";
import { useSettings } from "@/lib/client/settings-store";
import { useT } from "@/lib/i18n";
import { ChatView } from "./chat";
import PageHeader from "./page-header";

/** The home screen: a new question about the selected country, not tied to one index. */
export default function GeneralChat() {
  const { country } = useSettings();
  const t = useT();
  return (
    <>
      <PageHeader title={t("New question")} />
      <ChatView chatKey={chatKey(country, null)} country={country} chatIndex={null} indexId={null} />
    </>
  );
}
