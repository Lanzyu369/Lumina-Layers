import type { ReactNode } from "react";

/** Keep the original footprint while loading; only the centered spinner is visible. */
export default function ButtonContent({ loading, children }: { loading: boolean; children: ReactNode }) {
  return <>
    <span className={`inline-flex min-w-0 items-center justify-center gap-2 ${loading ? "invisible" : ""}`} aria-hidden={loading || undefined}>{children}</span>
    {loading && <span aria-hidden="true" className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-current/25 border-t-current" />
    </span>}
  </>;
}
