"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, type ReactNode } from "react";
import { AppProvider, useApp } from "@/lib/client/app-context";
import { FIXED_NOTICE } from "@/lib/constants";
import Sidebar from "./sidebar";
import { Loading } from "./ui";

// Leaflet touches `window`: it is loaded only in the browser and only when the pane is opened.
const MapPane = dynamic(() => import("./map-pane"), { ssr: false, loading: () => <div className="p-3"><Loading label="Loading map" /></div> });

type Mode = "mock" | "real" | null;

function useDataMode(): Mode {
  const [mode, setMode] = useState<Mode>(null);
  useEffect(() => {
    let alive = true;
    fetch("/api/status", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { mode?: string } | null) => {
        if (alive && body && (body.mode === "mock" || body.mode === "real")) setMode(body.mode);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  return mode;
}

function Shell({ children }: { children: ReactNode }) {
  const app = useApp();
  const mode = useDataMode();
  const { sidebarOpen, mapOpen, setSidebarOpen, setMapOpen } = app;
  const [mapWide, setMapWide] = useState(false);

  // Escape closes the mobile menu first, then the map pane.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (sidebarOpen) setSidebarOpen(false);
      else if (mapOpen) setMapOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [sidebarOpen, mapOpen, setSidebarOpen, setMapOpen]);
  return (
    <div className="flex h-dvh overflow-hidden">
      <div className="hidden shrink-0 md:block">
        <Sidebar />
      </div>
      {app.sidebarOpen ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="h-full shadow-xl">
            <Sidebar />
          </div>
          <button type="button" aria-label="Close menu" onClick={() => app.setSidebarOpen(false)} className="flex-1 bg-black/40" />
        </div>
      ) : null}

      <main className="flex min-w-0 flex-1 flex-col">
        {mode === "mock" ? (
          <div role="status" data-testid="mock-banner" className="bg-mock-bg px-4 py-1 text-center text-xs font-medium text-mock-ink">
            Mock data mode: every value is simulated for the interface demo and is not real monitoring data.
          </div>
        ) : null}
        {children}
        <p data-testid="fixed-notice" className="border-t border-line bg-canvas px-4 py-1.5 text-center text-xs text-muted">
          {FIXED_NOTICE}
        </p>
      </main>

      {app.mapOpen ? (
        <div className={`fixed inset-0 z-30 md:static md:inset-auto md:z-auto md:shrink-0 ${mapWide ? "md:w-[min(56rem,60vw)]" : "md:w-[26rem]"}`}>
          <MapPane expanded={mapWide} onToggleExpanded={() => setMapWide((w) => !w)} />
        </div>
      ) : null}
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <AppProvider>
      <Shell>{children}</Shell>
    </AppProvider>
  );
}
