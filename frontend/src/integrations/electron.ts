import { useEffect } from "react";
import { useSettingsStore } from "../stores/settingsStore";

interface ElectronAPI {
  setLanguage: (lang: string) => void;
  getAppVersion: () => Promise<string>;
}

export const electronAPI: ElectronAPI | null =
  (window as unknown as { electronAPI?: ElectronAPI }).electronAPI ?? null;

export function useElectronLanguageSync(): void {
  useEffect(() => {
    if (!electronAPI) return;

    const language = useSettingsStore.getState().language;
    electronAPI.setLanguage(language);

    const unsub = useSettingsStore.subscribe((state, prev) => {
      if (state.language !== prev.language) {
        electronAPI?.setLanguage(state.language);
      }
    });

    return unsub;
  }, []);
}
