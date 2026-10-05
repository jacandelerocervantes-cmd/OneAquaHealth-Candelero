"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { ChatResponse } from "@/lib/api";

/** A place picked on the map (or in a list) that the next question can be about. */
export interface PickedPlace {
  kind: "site" | "bathing-water";
  id: string;
  name: string;
  country: string;
  latitude: number | null;
  longitude: number | null;
  detail?: string;
  /** A Waterbase site: it has measurements but no CCME index, which exists only for sandbox locations. */
  measurementsOnly?: boolean;
}

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
  context?: string;
  language: string;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  response: ChatResponse;
}

export interface ErrorMessage {
  id: string;
  role: "error";
  status: number;
  text: string;
  /** Epoch milliseconds before which the user should not retry (rate limit). */
  retryAt: number | null;
  retryText: string | null;
}

export type ChatMessage = UserMessage | AssistantMessage | ErrorMessage;

export interface ExportPayload {
  filename: string;
  data: unknown;
}

interface AppContextValue {
  mapOpen: boolean;
  setMapOpen: (open: boolean) => void;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  place: PickedPlace | null;
  setPlace: (place: PickedPlace | null) => void;
  /** Conversations live in memory, one per country and index, and are cleared by "New question". */
  getChat: (key: string) => ChatMessage[];
  setChat: (key: string, update: (prev: ChatMessage[]) => ChatMessage[]) => void;
  clearChat: (key: string) => void;
  exportPayload: ExportPayload | null;
  setExportPayload: (payload: ExportPayload | null) => void;
}

/** One conversation per country and index (null = the general conversation). */
export function chatKey(country: string, indexId: string | null): string {
  return `${country}:${indexId ?? "general"}`;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [mapOpen, setMapOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [place, setPlace] = useState<PickedPlace | null>(null);
  const [chats, setChats] = useState<Record<string, ChatMessage[]>>({});
  const [exportPayload, setExportPayload] = useState<ExportPayload | null>(null);

  const getChat = useCallback((key: string) => chats[key] ?? EMPTY, [chats]);
  const setChat = useCallback(
    (key: string, update: (prev: ChatMessage[]) => ChatMessage[]) =>
      setChats((all) => ({ ...all, [key]: update(all[key] ?? EMPTY) })),
    [],
  );
  const clearChat = useCallback((key: string) => setChats((all) => ({ ...all, [key]: EMPTY })), []);

  const value = useMemo<AppContextValue>(
    () => ({ mapOpen, setMapOpen, sidebarOpen, setSidebarOpen, place, setPlace, getChat, setChat, clearChat, exportPayload, setExportPayload }),
    [mapOpen, sidebarOpen, place, getChat, setChat, clearChat, exportPayload],
  );
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

const EMPTY: ChatMessage[] = [];

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
