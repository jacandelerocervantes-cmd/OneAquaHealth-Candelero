/** Small plain-text formatting helpers. They never produce markup. */

export function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  const abs = Math.abs(value);
  if (abs !== 0 && (abs >= 1e6 || abs < 1e-3)) return value.toExponential(2);
  return Number(value.toFixed(digits)).toString();
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "n/a";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString().slice(0, 10);
}

export function formatPeriod(start?: string | null, end?: string | null): string {
  if (!start && !end) return "n/a";
  if (start && end && start !== end) return `${start} to ${end}`;
  return start ?? end ?? "n/a";
}

/** `water-chemistry` -> `Water chemistry`. */
export function humanise(value: string): string {
  const text = value.replace(/[-_]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The calendar year before `now`, as ISO dates (default window of the external-context indices). */
export function previousYearRange(now: Date = new Date()): { from: string; to: string } {
  const y = now.getUTCFullYear() - 1;
  return { from: `${y}-01-01`, to: `${y}-12-31` };
}

/** Download text built in the browser (no server round trip). */
export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename.replace(/[^A-Za-z0-9._-]/g, "_");
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}
