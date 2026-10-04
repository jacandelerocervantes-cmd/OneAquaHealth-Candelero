import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import AppShell from "@/components/app-shell";
import PageHeader from "@/components/page-header";
import { installProxyFetch } from "./helpers";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

describe("AppShell", () => {
  it("shows the mock banner and the fixed notice on every screen", async () => {
    installProxyFetch((url) => (url.pathname === "/api/status" ? new Response(JSON.stringify({ mode: "mock", configured: true })) : undefined));
    render(<AppShell><PageHeader title="Anything" /></AppShell>);
    expect(await screen.findByTestId("mock-banner")).toHaveTextContent(/simulated/);
    expect(screen.getByTestId("fixed-notice")).toHaveTextContent(/not legal compliance/);
  });

  it("closes the mobile menu with Escape", async () => {
    installProxyFetch();
    render(<AppShell><PageHeader title="Anything" /></AppShell>);
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("button", { name: "Close menu" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "Close menu" })).toBeNull();
  });
});
