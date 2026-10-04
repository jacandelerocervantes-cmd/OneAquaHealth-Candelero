import { statusResponse } from "@/lib/server/proxy";

export const dynamic = "force-dynamic";

/** Tells the client whether the app runs on mock or real data. Never exposes the URL or the key. */
export function GET(): Response {
  return statusResponse();
}
