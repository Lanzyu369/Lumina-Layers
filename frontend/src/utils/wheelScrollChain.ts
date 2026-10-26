/** Bridge a portal to its anchor's scroll chain. Ordinary DOM uses native scrolling. */
export function bindVerticalWheelScrollChain(
  portal: HTMLElement | null,
  anchor: Element | null,
): () => void {
  if (!portal || !anchor) return () => {};

  const canScroll = (element: HTMLElement, delta: number): boolean => {
    const overflow = getComputedStyle(element).overflowY;
    return /^(auto|scroll)$/.test(overflow) &&
      (delta < 0 ? element.scrollTop > 0 :
        element.scrollTop + element.clientHeight < element.scrollHeight - 1);
  };

  const stopsScrollChain = (element: HTMLElement): boolean => {
    const style = getComputedStyle(element);
    return /^(auto|scroll)$/.test(style.overflowY) &&
      /^(contain|none)$/.test(style.overscrollBehaviorY);
  };

  const handleWheel = (event: WheelEvent): void => {
    if (!event.cancelable || event.defaultPrevented ||
        event.ctrlKey || event.shiftKey || !event.deltaY ||
        Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;

    // Keep native scrolling inside a long menu while it has room to move.
    let target = event.target instanceof Element ? event.target : null;
    while (target && portal.contains(target)) {
      if (target instanceof HTMLElement &&
          (canScroll(target, event.deltaY) || stopsScrollChain(target))) return;
      target = target.parentElement;
    }

    for (let parent = anchor.parentElement; parent; parent = parent.parentElement) {
      if (!canScroll(parent, event.deltaY)) {
        // A portal is outside this DOM chain, so enforce the anchor boundary here.
        if (stopsScrollChain(parent)) {
          event.preventDefault();
          return;
        }
        continue;
      }
      const unit = event.deltaMode === 1 ? 16 :
        event.deltaMode === 2 ? parent.clientHeight : 1;
      event.preventDefault();
      parent.scrollTop += event.deltaY * unit;
      return;
    }
  };

  portal.addEventListener("wheel", handleWheel, { passive: false });
  return () => portal.removeEventListener("wheel", handleWheel);
}
