import { useEffect, useRef } from "react";

import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";

/** Apply renderer preference changes without replacing the preview session. */
export function useVectorPreviewRenderer(): void {
  const enabled = useSettingsStore(
    (state) => state.enableSmoothVectorPreview,
  );
  const rebuild = useConverterStore(
    (state) => state.rebuildVectorPreviewRenderer,
  );
  const previousEnabled = useRef(enabled);

  useEffect(() => {
    const changed = previousEnabled.current !== enabled;
    previousEnabled.current = enabled;
    if (!changed) {
      return;
    }
    void rebuild(enabled);
  }, [enabled, rebuild]);
}
