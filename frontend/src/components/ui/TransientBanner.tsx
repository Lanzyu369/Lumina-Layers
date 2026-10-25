import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { StatusBanner } from "./panelPrimitives";

const READABLE_MS = 5000;
const FADE_MS = 200;
const COLLAPSE_MS = 250;

type Phase = "visible" | "fade" | "collapse" | "gone";

/**
 * Status banner with a graceful exit: transient messages fade after five
 * seconds, persistent ones wait for the caller to clear the message; both
 * fade out and collapse so the content below reflows into the freed space
 * instead of jumping.
 */
export default function TransientBanner({
  message,
  tone = "success",
  autoDismiss = true,
  onDismiss,
  action,
  "data-testid": testId,
}: {
  message: string | null;
  tone?: "info" | "success" | "warning" | "error";
  /** Auto-fade after five seconds; false keeps the banner until the caller clears the message. */
  autoDismiss?: boolean;
  onDismiss?: () => void;
  action?: ReactNode;
  "data-testid"?: string;
}) {
  const [phase, setPhase] = useState<Phase>("visible");
  const phaseRef = useRef<Phase>(phase);
  phaseRef.current = phase;
  const heldRef = useRef<string | null>(message);
  const ref = useRef<HTMLDivElement>(null);
  const dismiss = useRef(onDismiss);
  dismiss.current = onDismiss;
  const reduced = useReducedMotion();
  const [gap, setGap] = useState(0);

  useEffect(() => {
    if (message) {
      heldRef.current = message;
      setPhase("visible");
      const parent = ref.current?.parentElement;
      setGap(parent ? parseFloat(getComputedStyle(parent).rowGap) || 0 : 0);
      if (!autoDismiss) return;
      const fade = window.setTimeout(() => setPhase("fade"), READABLE_MS);
      const collapse = window.setTimeout(() => setPhase("collapse"), READABLE_MS + FADE_MS);
      const done = window.setTimeout(() => {
        setPhase("gone");
        dismiss.current?.();
      }, READABLE_MS + FADE_MS + COLLAPSE_MS);
      return () => { clearTimeout(fade); clearTimeout(collapse); clearTimeout(done); };
    }
    if (phaseRef.current === "gone" || heldRef.current === null) return;
    // Cleared by the caller while still shown: play the same fade → collapse tail.
    setPhase("fade");
    const collapse = window.setTimeout(() => setPhase("collapse"), FADE_MS);
    const gone = window.setTimeout(() => setPhase("gone"), FADE_MS + COLLAPSE_MS);
    return () => { clearTimeout(collapse); clearTimeout(gone); };
  }, [message, autoDismiss]);

  const text = message ?? heldRef.current;
  if (text === null || phase === "gone") return null;
  return <motion.div ref={ref} initial={false} data-phase={phase}
    animate={{ opacity: phase === "visible" ? 1 : 0, height: phase === "collapse" ? 0 : "auto", marginBottom: phase === "collapse" ? -gap : 0 }}
    transition={{ opacity: { duration: reduced ? 0 : FADE_MS / 1000 }, height: { duration: reduced ? 0 : COLLAPSE_MS / 1000 }, marginBottom: { duration: reduced ? 0 : COLLAPSE_MS / 1000 } }}
    className="min-h-0 overflow-hidden">
    <StatusBanner data-testid={testId} role="status" tone={tone} action={action}>{text}</StatusBanner>
  </motion.div>;
}
