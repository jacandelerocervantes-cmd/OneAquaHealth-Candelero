import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WaterQualityPanel } from "@/components/index-data/water-panels";

afterEach(() => vi.unstubAllGlobals());

describe("WaterQualityPanel", () => {
  it("explains a measurements-only site without asking the backend for an index that does not exist", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<WaterQualityPanel siteId="EL0009000400220100N500" measurementsOnly />);
    expect(screen.getByRole("note").textContent).toContain("computed only for sandbox locations");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
