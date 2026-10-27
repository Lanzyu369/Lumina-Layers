/** Normalize pixel, line and page wheel units and bound a single impulse. */
export function wheelZoomDelta(deltaY: number, deltaMode = 0, pageHeight = 800): number {
  if (!Number.isFinite(deltaY)) return 0;
  const unit = deltaMode === 1 ? 16 : deltaMode === 2 ? Math.max(1, pageHeight) : 1;
  return Math.max(-100, Math.min(100, deltaY * unit));
}

export function wheelZoomFactor(deltaPixels: number, step = 1.1): number {
  return Math.pow(step, -wheelZoomDelta(deltaPixels) / 100);
}

/** Adapt the pinned OrbitControls' direction-only wheel handler without
 * replacing its camera, gesture guards, cursor anchor or start/end events. */
export function bindOrbitWheelZoom(
  element: HTMLElement,
  controls: { zoomSpeed: number; enabled?: boolean; enableZoom?: boolean },
): () => void {
  let replaying = false;
  const handler = (event: WheelEvent) => {
    if (replaying || controls.enabled === false || controls.enableZoom === false) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const delta = wheelZoomDelta(event.deltaY, event.deltaMode, element.clientHeight);
    if (delta === 0) return;
    const speed = controls.zoomSpeed;
    try {
      controls.zoomSpeed = speed * Math.abs(delta) / 100;
      replaying = true;
      element.dispatchEvent(new WheelEvent("wheel", event));
    } finally {
      replaying = false;
      controls.zoomSpeed = speed;
    }
  };
  element.addEventListener("wheel", handler, { capture: true, passive: false });
  return () => element.removeEventListener("wheel", handler, true);
}
