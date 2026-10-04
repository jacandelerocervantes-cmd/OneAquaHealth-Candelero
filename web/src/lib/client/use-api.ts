"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, type Query } from "./api";

export type ApiState<T> = { status: "loading" } | { status: "error"; error: unknown } | { status: "ready"; data: T };

interface Slot<T> {
  key: string;
  result: { ok: true; data: T } | { ok: false; error: unknown };
}

/**
 * GET a same-origin proxy route; a null path means "nothing to load yet" and stays at loading.
 * Loading is derived (the stored result belongs to another key), so no state is set
 * synchronously inside the effect.
 */
export function useApi<T>(path: string | null, query?: Query): ApiState<T> & { reload: () => void } {
  const [slot, setSlot] = useState<Slot<T> | null>(null);
  const [tick, setTick] = useState(0);
  const queryKey = JSON.stringify(query ?? {});
  const key = path ? `${path}?${queryKey}#${tick}` : "";

  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    apiGet<T>(path, JSON.parse(queryKey) as Query, controller.signal)
      .then((data) => setSlot({ key, result: { ok: true, data } }))
      .catch((error: unknown) => {
        if ((error as { name?: string }).name === "AbortError") return;
        setSlot({ key, result: { ok: false, error } });
      });
    return () => controller.abort();
  }, [path, queryKey, key]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  if (!path || !slot || slot.key !== key) return { status: "loading", reload };
  return slot.result.ok
    ? { status: "ready", data: slot.result.data, reload }
    : { status: "error", error: slot.result.error, reload };
}
