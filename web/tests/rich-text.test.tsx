import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RichText } from "@/components/rich-text";

describe("RichText", () => {
  it("shows bold and bullets and no asterisks", () => {
    render(<RichText testId="t" text={"For Italy, the data can show:\n- **Classification:** the latest class.\n- **Sample results:** E. coli."} />);
    const root = screen.getByTestId("t");
    expect(root.textContent).not.toContain("*");
    expect(root.querySelectorAll("li")).toHaveLength(2);
    expect(root.querySelector("strong")?.textContent).toBe("Classification:");
  });

  it("never turns text into markup", () => {
    render(<RichText testId="t" text={"<b>x</b> [a](b) **unfinished"} />);
    const root = screen.getByTestId("t");
    expect(root.querySelector("b")).toBeNull();
    expect(root.querySelector("a")).toBeNull();
    expect(root.textContent).toContain("<b>x</b>");
  });
});
