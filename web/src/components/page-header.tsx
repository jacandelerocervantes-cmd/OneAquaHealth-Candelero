"use client";

import { useState, type ReactNode } from "react";
import { useApp } from "@/lib/client/app-context";
import { downloadJson } from "@/lib/format";

function MapIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Z" />
      <path d="M9 4v14M15 6v14" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v12m0 0-4-4m4 4 4-4M5 21h14" />
    </svg>
  );
}

/**
 * Header of the conversation: title, an optional "About" chevron panel, the download button
 * (data behind the answer or the table shown) and the map icon that opens the right-hand pane.
 */
export default function PageHeader({ title, about }: { title: string; about?: ReactNode }) {
  const app = useApp();
  const [aboutOpen, setAboutOpen] = useState(false);
  return (
    <header className="border-b border-line bg-canvas">
      <div className="flex items-center gap-2 px-4 py-2">
        <button type="button" aria-label="Open menu" onClick={() => app.setSidebarOpen(true)} className="rounded-lg p-2 hover:bg-sidebar md:hidden">
          <span aria-hidden>☰</span>
        </button>
        <h1 className="min-w-0 flex-1 truncate text-lg font-semibold" data-testid="page-title">{title}</h1>
        {about ? (
          <button
            type="button"
            aria-expanded={aboutOpen}
            aria-controls="about-index"
            onClick={() => setAboutOpen((v) => !v)}
            className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm hover:bg-sidebar"
          >
            <span className="max-sm:sr-only">About this index</span>
            <span aria-hidden>{aboutOpen ? "▴" : "▾"}</span>
          </button>
        ) : null}
        <button
          type="button"
          aria-label="Download the data behind the answer"
          title="Download the data behind the answer"
          disabled={!app.exportPayload}
          onClick={() => app.exportPayload && downloadJson(app.exportPayload.filename, app.exportPayload.data)}
          className="rounded-lg p-2 hover:bg-sidebar disabled:opacity-40"
        >
          <DownloadIcon />
        </button>
        <button
          type="button"
          aria-label={app.mapOpen ? "Close map" : "Open map"}
          aria-pressed={app.mapOpen}
          data-testid="map-toggle"
          onClick={() => app.setMapOpen(!app.mapOpen)}
          className={`rounded-lg p-2 hover:bg-sidebar ${app.mapOpen ? "bg-sidebar" : ""}`}
        >
          <MapIcon />
        </button>
      </div>
      {about && aboutOpen ? (
        <div id="about-index" data-testid="about-index" className="border-t border-line px-4 py-3 text-sm">
          {about}
        </div>
      ) : null}
    </header>
  );
}
