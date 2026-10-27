/**
 * Unit tests for WikiTooltip component.
 *
 * Validates specific interaction scenarios, edge cases, and accessibility
 * attributes that complement the property-based tests.
 *
 * Requirements covered: 1.1, 1.2, 3.5, 6.2, 6.3
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Capture onOpenChange + useHover args for controlling tooltip state in tests
// ---------------------------------------------------------------------------
let capturedOnOpenChange: ((open: boolean) => void) | null = null;
let capturedHoverOpts: Record<string, unknown> = {};

vi.mock("@floating-ui/react", () => {
  const setRef = vi.fn();
  const fakeContext = {};

  return {
    useFloating: (opts: Record<string, unknown>) => {
      capturedOnOpenChange =
        (opts.onOpenChange as (v: boolean) => void) ?? null;
      return {
        refs: { setReference: setRef, setFloating: setRef },
        floatingStyles: {},
        context: fakeContext,
      };
    },
    useHover: (_ctx: unknown, opts: Record<string, unknown>) => {
      capturedHoverOpts = opts ?? {};
      return {};
    },
    useFocus: () => ({
      referenceProps: {
        onFocus: () => capturedOnOpenChange?.(true),
      },
    }),
    useClick: (_ctx: unknown, opts: { enabled?: boolean }) =>
      opts.enabled
        ? {
            referenceProps: {
              onClick: () => capturedOnOpenChange?.(true),
            },
          }
        : {},
    useDismiss: () => ({}),
    useRole: () => ({}),
    useInteractions: (hooks: Array<Record<string, unknown>>) => ({
      getReferenceProps: () =>
        Object.assign({}, ...hooks.map((hook) => hook.referenceProps ?? {})),
      getFloatingProps: () => ({ role: "tooltip" }),
    }),
    offset: () => null,
    flip: () => null,
    shift: () => null,
    autoUpdate: () => () => {},
    FloatingPortal: ({ children }: { children: ReactNode }) => children,
    FloatingFocusManager: ({
      children,
      modal,
      initialFocus,
    }: {
      children: ReactNode;
      modal?: boolean;
      initialFocus?: number;
    }) => (
      <div
        data-testid="focus-manager"
        data-modal={String(modal)}
        data-initial-focus={String(initialFocus)}
      >
        {children}
      </div>
    ),
  };
});

// Mock framer-motion to render immediately without animation
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: ReactNode }) => children,
  motion: {
    div: ({
      children,
      initial,
      animate,
      exit,
      transition,
      ...rest
    }: Record<string, unknown> & { children?: ReactNode }) => {
      void initial;
      void animate;
      void exit;
      void transition;
      const { ref, style, className, ...htmlProps } = rest as Record<
        string,
        unknown
      >;
      return (
        <div
          ref={ref as React.Ref<HTMLDivElement>}
          style={style as React.CSSProperties}
          className={className as string}
          data-testid="tooltip-bubble"
          {...(htmlProps as React.HTMLAttributes<HTMLDivElement>)}
        >
          {children}
        </div>
      );
    },
  },
}));

import WikiTooltip from "../components/ui/WikiTooltip";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Render WikiTooltip and optionally force it open via onOpenChange(true). */
async function renderAndOpen(
  props: {
    title: string;
    description: string;
    wikiUrl?: string;
    wikiPath?: `/docs/${string}/`;
    openOnClick?: boolean;
    delay?: number;
  },
  open = true
) {
  let result: ReturnType<typeof render>;
  await act(async () => {
    result = render(
      <WikiTooltip {...props}>
        <button>Trigger</button>
      </WikiTooltip>
    );
  });

  if (open && capturedOnOpenChange) {
    await act(async () => {
      capturedOnOpenChange!(true);
    });
  }

  return result!;
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------
beforeEach(() => {
  capturedOnOpenChange = null;
  capturedHoverOpts = {};
});

afterEach(() => {
  cleanup();
  delete (window as Window & { electronAPI?: unknown }).electronAPI;
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WikiTooltip unit tests", () => {
  /**
   * Requirement 1.1: WHEN user hovers on Trigger_Element for > 600ms,
   * tooltip SHALL appear.
   *
   * We verify that useHover receives the correct default delay config (600ms)
   * and that calling onOpenChange(true) makes the tooltip visible.
   */
  it("shows tooltip after 600ms hover delay (default config)", async () => {
    const { container } = await renderAndOpen({
      title: "Test Title",
      description: "Test Description",
    });

    // Verify useHover received the default 600ms open delay
    const hoverDelay = capturedHoverOpts.delay as {
      open: number;
      close: number;
    };
    expect(hoverDelay).toBeDefined();
    expect(hoverDelay.open).toBe(600);

    // Tooltip bubble should be visible after onOpenChange(true)
    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();
    expect(bubble!.textContent).toContain("Test Title");
    expect(bubble!.textContent).toContain("Test Description");
  });

  /**
   * Requirement 1.2: WHEN user leaves Trigger_Element within 600ms,
   * tooltip SHALL remain hidden.
   *
   * We verify that without calling onOpenChange(true), the tooltip stays hidden.
   */
  it("does not show tooltip when onOpenChange is not triggered", async () => {
    const { container } = await renderAndOpen(
      {
        title: "Hidden Title",
        description: "Hidden Description",
      },
      false // do NOT force open
    );

    // Tooltip bubble should NOT be in the DOM
    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).toBeNull();

    // Content should not appear anywhere
    expect(container.textContent).not.toContain("Hidden Title");
  });

  /**
   * Requirement 3.5: WHEN wikiUrl is not provided,
   * tooltip SHALL NOT render the wiki link button.
   */
  it("does not render wiki link when wikiUrl is not provided", async () => {
    const { container } = await renderAndOpen({
      title: "No Link",
      description: "No wiki URL here",
    });

    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();

    // No <a> element should exist inside the bubble
    const link = bubble!.querySelector("a");
    expect(link).toBeNull();
  });

  it("does not let non-link tooltip bubbles intercept neighboring controls", async () => {
    const { container } = await renderAndOpen({
      title: "Passive",
      description: "This tooltip only explains a control",
    });

    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();
    const positioningDiv = bubble!.parentElement;
    expect(positioningDiv).not.toBeNull();
    expect(positioningDiv).toHaveClass("pointer-events-none");
  });

  /**
   * Requirement 6.2: Tooltip_Bubble SHALL have role="tooltip".
   *
   * Our mock's getFloatingProps returns { role: "tooltip" }, which gets
   * spread onto the motion.div. Verify the attribute is present.
   */
  it("has role='tooltip' accessibility attribute on the bubble", async () => {
    const { container } = await renderAndOpen({
      title: "Accessible",
      description: "With role",
    });

    // role="tooltip" is on the outer positioning div (from getFloatingProps),
    // which is the parent of the motion.div (data-testid="tooltip-bubble")
    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();
    const positioningDiv = bubble!.parentElement;
    expect(positioningDiv).not.toBeNull();
    expect(positioningDiv!.getAttribute("role")).toBe("tooltip");
  });

  /**
   * Requirement 6.3: Wiki link SHALL be keyboard-focusable via Tab.
   *
   * An <a> element with href is natively focusable. We verify the link
   * exists and can receive focus.
   */
  it("wiki link is keyboard-focusable when wikiUrl is provided", async () => {
    const { container } = await renderAndOpen(
      {
        title: "Keyboard Test",
        description: "Focus the link",
        wikiUrl: "https://example.com/wiki",
      },
      false,
    );

    fireEvent.focus(screen.getByRole("button", { name: "Trigger" }));

    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();
    expect(screen.getByTestId("focus-manager")).toHaveAttribute(
      "data-modal",
      "false",
    );
    expect(screen.getByTestId("focus-manager")).toHaveAttribute(
      "data-initial-focus",
      "-1",
    );

    const link = bubble!.querySelector("a");
    expect(link).not.toBeNull();
    expect(link!.getAttribute("href")).toBe("https://example.com/wiki");
    expect(bubble!.parentElement).toHaveClass("pointer-events-auto");
    expect(link).toHaveClass("pointer-events-auto");

    // <a> with href is natively focusable — verify it can receive focus
    link!.focus();
    expect(document.activeElement).toBe(link);
  });

  it("opens on click when the trigger explicitly opts in", async () => {
    const { container } = await renderAndOpen(
      {
        title: "Touch Help",
        description: "Tap to read the explanation.",
        wikiUrl: "https://example.com/wiki",
        openOnClick: true,
      },
      false,
    );

    fireEvent.click(screen.getByRole("button", { name: "Trigger" }));

    expect(container.querySelector('[data-testid="tooltip-bubble"] a')).toHaveAttribute(
      "href",
      "https://example.com/wiki",
    );
  });

  it("builds a locale-aware public Wiki link from wikiPath", async () => {
    const { container } = await renderAndOpen({
      title: "Hue protection",
      description: "Keeps dark colors from drifting in hue.",
      wikiPath: "/docs/reference/color-matching/hue-protection/",
    });

    const link = container.querySelector('[data-testid="tooltip-bubble"] a');
    expect(link).not.toBeNull();
    expect(link!.getAttribute("href")).toBe(
      "https://wiki.luminastudio.com.cn/zh/docs/reference/color-matching/hue-protection/",
    );
  });

  it("opens Wiki through the desktop bridge once without changing the URL", async () => {
    const openWiki = vi.fn().mockResolvedValue({ opened: true });
    Object.defineProperty(window, "electronAPI", {
      configurable: true,
      value: { openWiki },
    });

    const { container } = await renderAndOpen({
      title: "Desktop Wiki",
      description: "Open the matching documentation.",
      wikiPath: "/docs/reference/color-matching/hue-protection/",
    });
    const link = container.querySelector('[data-testid="tooltip-bubble"] a');
    expect(link).not.toBeNull();

    const click = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
    });
    const dispatchResult = link!.dispatchEvent(click);

    expect(dispatchResult).toBe(false);
    expect(openWiki).toHaveBeenCalledTimes(1);
    expect(openWiki).toHaveBeenCalledWith(
      "https://wiki.luminastudio.com.cn/zh/docs/reference/color-matching/hue-protection/",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("keeps the normal new-tab link behavior on the web", async () => {
    const { container } = await renderAndOpen({
      title: "Web Wiki",
      description: "Open the matching documentation.",
      wikiUrl:
        "https://wiki.luminastudio.com.cn/en/docs/reference/color-matching/hue-protection/#source",
    });
    const link = container.querySelector('[data-testid="tooltip-bubble"] a');
    expect(link).not.toBeNull();

    const click = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
    });
    expect(link!.dispatchEvent(click)).toBe(true);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
