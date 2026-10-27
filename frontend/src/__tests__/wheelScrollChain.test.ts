import { afterEach, describe, expect, it } from "vitest";
import { bindVerticalWheelScrollChain } from "../utils/wheelScrollChain";

function scrollArea(height = 200, contentHeight = 800): HTMLDivElement {
  const element = document.createElement("div");
  element.style.overflowY = "auto";
  Object.defineProperties(element, {
    clientHeight: { value: height },
    scrollHeight: { value: contentHeight },
  });
  return element;
}

function wheel(target: Element, deltaY: number, extra = {}): WheelEvent {
  const event = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY, ...extra });
  target.dispatchEvent(event);
  return event;
}

afterEach(() => document.body.replaceChildren());

describe("vertical wheel scroll chaining", () => {
  it("forwards vertical wheel input from portal content and removes the bridge on cleanup", () => {
    const panel = scrollArea();
    const anchor = document.createElement("button");
    const portal = document.createElement("div");
    const label = document.createElement("span");
    const image = document.createElement("img");
    portal.append(label, image);
    panel.append(anchor);
    document.body.append(panel, portal);
    const cleanup = bindVerticalWheelScrollChain(portal, anchor);
    expect(wheel(label, 120).defaultPrevented).toBe(true);
    expect(panel.scrollTop).toBe(120);
    wheel(image, -60);
    expect(panel.scrollTop).toBe(60);
    expect(portal.scrollLeft).toBe(0);
    expect(wheel(label, 10, { deltaX: 100 }).defaultPrevented).toBe(false);
    expect(wheel(label, 100, { shiftKey: true }).defaultPrevented).toBe(false);
    expect(wheel(label, 100, { ctrlKey: true }).defaultPrevented).toBe(false);
    cleanup();
    wheel(label, 120);
    expect(panel.scrollTop).toBe(60);
  });

  it("keeps a long portal menu native until its boundary, then scrolls its anchor panel", () => {
    const panel = scrollArea();
    const anchor = document.createElement("button");
    panel.append(anchor);
    const menu = scrollArea(100, 300);
    const option = document.createElement("button");
    menu.append(option);
    document.body.append(panel, menu);
    const cleanup = bindVerticalWheelScrollChain(menu, anchor);
    expect(wheel(option, 120).defaultPrevented).toBe(false);
    expect(panel.scrollTop).toBe(0);
    menu.scrollTop = 200;
    expect(wheel(option, 3, { deltaMode: 1 }).defaultPrevented).toBe(true);
    expect(panel.scrollTop).toBe(48);
    expect(wheel(option, -120).defaultPrevented).toBe(false);
    cleanup();
  });

  it("scrolls the anchor panel from portal text and links, and leaves page boundaries alone", () => {
    const panel = scrollArea();
    const anchor = document.createElement("span");
    panel.append(anchor);
    const tooltip = document.createElement("div");
    const text = document.createElement("p");
    const link = document.createElement("a");
    tooltip.append(text, link);
    document.body.append(panel, tooltip);
    bindVerticalWheelScrollChain(tooltip, anchor);
    expect(wheel(text, -100).defaultPrevented).toBe(false);
    wheel(text, 100);
    wheel(link, 100);
    expect(panel.scrollTop).toBe(200);
  });

  it.each(["contain", "none"])("respects the anchor panel's %s boundary in both directions", (boundary) => {
    const outer = scrollArea();
    outer.scrollTop = 100;
    const panel = scrollArea();
    panel.style.overscrollBehaviorY = boundary;
    const anchor = document.createElement("button");
    const portal = document.createElement("div");
    panel.append(anchor);
    outer.append(panel);
    document.body.append(outer, portal);
    bindVerticalWheelScrollChain(portal, anchor);

    expect(wheel(portal, -100).defaultPrevented).toBe(true);
    expect(panel.scrollTop).toBe(0);
    expect(outer.scrollTop).toBe(100);
    wheel(portal, 100);
    expect(panel.scrollTop).toBe(100);

    panel.scrollTop = 600;
    expect(wheel(portal, 100).defaultPrevented).toBe(true);
    expect(panel.scrollTop).toBe(600);
    expect(outer.scrollTop).toBe(100);
    wheel(portal, -100);
    expect(panel.scrollTop).toBe(500);
  });

  it("chains through an exhausted nested list but stops at a short owning panel", () => {
    const outer = scrollArea();
    const panel = scrollArea(200, 200);
    panel.style.overscrollBehaviorY = "contain";
    const nestedList = scrollArea(100, 300);
    const anchor = document.createElement("button");
    const portal = document.createElement("div");
    nestedList.append(anchor);
    panel.append(nestedList);
    outer.append(panel);
    document.body.append(outer, portal);
    bindVerticalWheelScrollChain(portal, anchor);

    wheel(portal, 100);
    expect(nestedList.scrollTop).toBe(100);
    nestedList.scrollTop = 200;
    expect(wheel(portal, 100).defaultPrevented).toBe(true);
    expect(outer.scrollTop).toBe(0);

    panel.style.overscrollBehaviorY = "auto";
    wheel(portal, 100);
    expect(outer.scrollTop).toBe(100);
  });

  it("leaves an explicitly contained portal menu's boundary to native scrolling", () => {
    const panel = scrollArea();
    const anchor = document.createElement("button");
    const menu = scrollArea(100, 300);
    menu.style.overscrollBehaviorY = "contain";
    panel.append(anchor);
    document.body.append(panel, menu);
    bindVerticalWheelScrollChain(menu, anchor);

    menu.scrollTop = 200;
    expect(wheel(menu, 100).defaultPrevented).toBe(false);
    expect(panel.scrollTop).toBe(0);
  });
});
