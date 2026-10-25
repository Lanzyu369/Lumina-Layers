import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import CloudLibraryPreview from "../CloudLibraryPreview";

afterEach(() => { vi.restoreAllMocks(); });

describe("cloud library detail focus", () => {
  it.each([
    [1280, true], [640, false],
  ])("opens details at %i px with preventScroll=%s", (width, preventScroll) => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(width);
    const focus = vi.spyOn(HTMLButtonElement.prototype, "focus");
    render(<CloudLibraryPreview
      resetKey="all" toolbar={null}
      items={[{ key: "lut", name: "Selected LUT", subtitle: "Brand", state: "Installed",
        detail: <p>Details</p> }]}
    />);
    fireEvent.click(screen.getByRole("button", { name: /Selected LUT/ }));
    expect(screen.getByText("Details")).toBeInTheDocument();
    expect(focus).toHaveBeenLastCalledWith({ preventScroll });
  });
});
