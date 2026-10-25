import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { useHeaderNavFit } from "../hooks/useHeaderNavFit";
import type { HeaderNavAlignment } from "../stores/settingsStore";

// Natural widths of the Chinese converter header; the title keeps its width
// while collapsed, so the mock never changes it.
const WIDTHS: Record<string, number> = { logo: 32, title: 152, primary: 614, tools: 177 };
const PADDING = 16;
let headerWidth = 1400;

function Harness({ alignment }: { alignment: HeaderNavAlignment }) {
  const header = useRef<HTMLElement>(null);
  const contentWidthProbe = useRef<HTMLSpanElement>(null);
  const brandLogo = useRef<HTMLImageElement>(null);
  const brandTitle = useRef<HTMLHeadingElement>(null);
  const primaryTabs = useRef<HTMLElement>(null);
  const tools = useRef<HTMLDivElement>(null);
  const fit = useHeaderNavFit(alignment, {
    header,
    contentWidthProbe,
    brandLogo,
    brandTitle,
    primaryTabs,
    tools,
  });

  return (
    <header
      ref={header}
      data-measure="header"
      style={{ paddingLeft: `${PADDING}px`, paddingRight: `${PADDING}px`, columnGap: "24px" }}
    >
      <span ref={contentWidthProbe} data-measure="probe" />
      <img ref={brandLogo} data-measure="logo" alt="" />
      <h1 ref={brandTitle} data-measure="title" />
      <nav ref={primaryTabs} data-measure="primary">
        <div />
      </nav>
      <div ref={tools} data-measure="tools" />
      <output data-testid="fit">
        {[
          fit.singleRow ? "one-row" : "two-rows",
          fit.showBrandTitle ? "title" : "logo",
          fit.primaryTabsInsetPx,
        ].join(":")}
      </output>
    </header>
  );
}

function measuredRole(element: Element): string | undefined {
  return element instanceof HTMLElement ? element.dataset.measure : undefined;
}

/** Header width whose content box is exactly `contentWidth`. */
function headerFor(contentWidth: number): number {
  return contentWidth + 2 * PADDING;
}

describe("useHeaderNavFit", () => {
  const resizeCallbacks: ResizeObserverCallback[] = [];
  const observedRoles: (string | undefined)[] = [];

  function resizeHeader(width: number) {
    headerWidth = width;
    act(() => {
      for (const callback of resizeCallbacks) {
        callback([], {} as ResizeObserver);
      }
    });
  }

  beforeEach(() => {
    headerWidth = 1400;
    resizeCallbacks.length = 0;
    observedRoles.length = 0;
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockImplementation(
      function (this: Element) {
        return measuredRole(this) === "primary" ? WIDTHS.primary : 0;
      },
    );
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(
      function (this: Element) {
        const role = measuredRole(this);
        const width = role === "probe" ? headerWidth - 2 * PADDING : (WIDTHS[role ?? ""] ?? 0);
        return { width, height: 0, x: 0, y: 0, top: 0, left: 0, right: width, bottom: 0, toJSON: () => ({}) };
      },
    );
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: ResizeObserverCallback) {
          resizeCallbacks.push(callback);
        }
        observe(element: Element) {
          observedRoles.push(measuredRole(element));
        }
        unobserve() {}
        disconnect() {}
      },
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps the brand title and one row when there is room", () => {
    render(<Harness alignment="center" />);

    expect(screen.getByTestId("fit")).toHaveTextContent("one-row:title:16");
  });

  it("starts left-aligned tabs after the full brand and the column gap", () => {
    render(<Harness alignment="left" />);

    expect(screen.getByTestId("fit")).toHaveTextContent("one-row:title:224");
  });

  it("hides the title before moving centered tabs to a second row", () => {
    headerWidth = headerFor(614 + 2 * (184 + 24) - 1);
    render(<Harness alignment="center" />);
    expect(screen.getByTestId("fit")).toHaveTextContent("one-row:logo:16");

    resizeHeader(headerFor(32 + 614 + 177 + 2 * 24 - 1));
    expect(screen.getByTestId("fit")).toHaveTextContent("two-rows:title:16");
  });

  it("starts left-aligned tabs after the logo once the title is hidden", () => {
    headerWidth = headerFor(184 + 614 + 177 + 2 * 24 - 1);
    render(<Harness alignment="left" />);

    expect(screen.getByTestId("fit")).toHaveTextContent("one-row:logo:72");
  });

  it("watches the content probe instead of the header, whose height changes when the tabs wrap", () => {
    render(<Harness alignment="center" />);

    expect(observedRoles).toContain("probe");
    expect(observedRoles).not.toContain("header");
  });

  it("re-measures on resize without flipping while the size stays the same", () => {
    render(<Harness alignment="left" />);
    expect(screen.getByTestId("fit")).toHaveTextContent("one-row:title:224");

    resizeHeader(headerFor(900));
    expect(screen.getByTestId("fit")).toHaveTextContent("one-row:logo:72");

    resizeHeader(headerFor(900));
    expect(screen.getByTestId("fit")).toHaveTextContent("one-row:logo:72");

    resizeHeader(headerFor(800));
    expect(screen.getByTestId("fit")).toHaveTextContent("two-rows:title:16");
  });
});
