import { useEffect } from "react";
import { getSettings } from "../api/system";
import { useSettingsStore } from "../stores/settingsStore";

const SETTINGS_SYNC_DEBOUNCE_MS = 150;

/**
 * Hydrate settings from the launcher-owned backend file and keep later
 * changes synchronized. The backend copy survives the changing loopback
 * ports used by launcher-managed runtimes.
 *
 * 从启动器托管的后端文件恢复设置，并持续同步后续更改。即使启动器为不同
 * 运行版本分配了不同本机端口，后端副本仍能跨版本保留。
 */
export function useSharedSettingsPersistence(): void {
  useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => void) | null = null;
    let timer: number | null = null;

    const subscribeAfterHydration = (): void => {
      if (cancelled) return;
      unsubscribe = useSettingsStore.subscribe(() => {
        if (timer !== null) {
          window.clearTimeout(timer);
        }
        timer = window.setTimeout(() => {
          timer = null;
          void useSettingsStore.getState().syncToBackend();
        }, SETTINGS_SYNC_DEBOUNCE_MS);
      });
    };

    void getSettings({ suppressClientLog: true })
      .then(async (response) => {
        if (!cancelled && response?.settings) {
          useSettingsStore
            .getState()
            .hydrateDeviceSettingsFromBackend(response.settings);
          // The browser origin changes with the launcher's random loopback
          // port. Copy any origin-local preferences that won precedence
          // during hydration into the launcher-owned settings file now,
          // rather than waiting for the user to edit another setting.
          await useSettingsStore.getState().syncToBackend();
        }
      })
      .catch(() => {
        /* best effort */
      })
      .finally(subscribeAfterHydration);

    return () => {
      cancelled = true;
      unsubscribe?.();
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
        void useSettingsStore.getState().syncToBackend();
      }
    };
  }, []);
}
