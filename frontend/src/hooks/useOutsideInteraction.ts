import { useEffect, type RefObject } from "react";

/**
 * Call ``handler`` when a mouse or touch press, or keyboard focus, lands
 * outside ``ref``. Listening only while ``enabled`` keeps closed popovers
 * from reacting to the rest of the page.
 * 鼠标或触摸按下、或键盘焦点落到 ref 元素之外时调用 handler；仅在 enabled 为真时监听，
 * 浮层收起后不再响应页面其他位置的操作。
 */
export function useOutsideInteraction(
  ref: RefObject<HTMLElement | null>,
  handler: () => void,
  enabled = true,
): void {
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const listener = (event: Event) => {
      if (!ref.current || ref.current.contains(event.target as Node)) {
        return;
      }
      handler();
    };
    const events = ["mousedown", "touchstart", "focusin"] as const;
    for (const type of events) {
      document.addEventListener(type, listener);
    }
    return () => {
      for (const type of events) {
        document.removeEventListener(type, listener);
      }
    };
  }, [ref, handler, enabled]);
}
