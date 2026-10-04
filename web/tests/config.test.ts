import { describe, expect, it } from "vitest";
import { normaliseBackendUrl, publicStatus, readConfig } from "@/lib/server/config";

describe("server configuration", () => {
  it("defaults to mock mode", () => {
    expect(readConfig({}).mode).toBe("mock");
    expect(readConfig({ OAH_DATA_MODE: "nonsense" }).mode).toBe("mock");
    expect(readConfig({ OAH_DATA_MODE: " REAL " }).mode).toBe("real");
  });

  it("accepts only a plain http(s) origin as backend URL", () => {
    expect(normaliseBackendUrl("https://backend.example/")).toBe("https://backend.example");
    expect(normaliseBackendUrl("http://localhost:8000")).toBe("http://localhost:8000");
    expect(normaliseBackendUrl("https://user:pw@backend.example")).toBeNull();
    expect(normaliseBackendUrl("https://backend.example/?a=1")).toBeNull();
    expect(normaliseBackendUrl("ftp://backend.example")).toBeNull();
    expect(normaliseBackendUrl("not a url")).toBeNull();
    expect(normaliseBackendUrl(undefined)).toBeNull();
  });

  it("never exposes the URL or the key in the public status", () => {
    const status = publicStatus(readConfig({ OAH_DATA_MODE: "real", OAH_BACKEND_URL: "https://b.example", OAH_API_KEY: "k".repeat(40) }));
    expect(status).toEqual({ mode: "real", configured: true });
    expect(JSON.stringify(status)).not.toContain("b.example");
    expect(publicStatus(readConfig({ OAH_DATA_MODE: "real" })).configured).toBe(false);
  });
});
