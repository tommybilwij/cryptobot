import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders 'Not enough data' for empty values", () => {
    const { getByText } = render(<Sparkline values={[]} />);
    expect(getByText("Not enough data")).toBeInTheDocument();
  });

  it("renders an SVG polyline for valid data", () => {
    const { container } = render(<Sparkline values={[1, 2, 3, 4, 5]} />);
    const polyline = container.querySelector("polyline");
    expect(polyline).toBeTruthy();
    expect(polyline?.getAttribute("points")).toBeTruthy();
  });
});
