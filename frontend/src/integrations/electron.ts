import { useEffect } from "react";
import { useSettingsStore } from "../stores/settingsStore";
import { translations } from "../i18n/translations";
import type { LuminaBoxNativeSerialApi } from "../api/luminaBoxDesktopSerial";

interface SerialPickerLabels {
  title: string;
  message: string;
  empty: string;
  cancel: string;
  next: string;
  previous: string;
}

interface ElectronAPI {
  nativeSerial?: LuminaBoxNativeSerialApi;
  setLanguage: (lang: string, serialLabels?: SerialPickerLabels) => void;
  getAppVersion: () => Promise<string>;
  getNativeBedModel?: (
    deviceProfileId: string,
  ) => Promise<ArrayBuffer | Uint8Array | null>;
  pickWorkshopImage?: () => Promise<{
    name: string;
    mimeType: string;
    bytes: ArrayBuffer | Uint8Array;
  } | null>;
  setGeneratedFileDirectory?: (
    directory: string,
  ) => Promise<{ status: string; directory?: string }>;
  pickGeneratedFileDirectory?: () => Promise<{
    status: "selected" | "canceled" | "error";
    directory?: string;
    code?: string;
  }>;
}

export const electronAPI: ElectronAPI | null =
  (window as unknown as { electronAPI?: ElectronAPI }).electronAPI ?? null;

function syncLanguage(language: "zh" | "en"): void {
  electronAPI?.setLanguage(language, {
    title: translations.lumina_box_serial_picker_title[language],
    message: translations.lumina_box_serial_picker_message[language],
    empty: translations.lumina_box_serial_picker_empty[language],
    cancel: translations.app_quit_cancel[language],
    next: translations.lumina_box_serial_picker_next[language],
    previous: translations.lumina_box_serial_picker_previous[language],
  });
}

export function useElectronLanguageSync(): void {
  useEffect(() => {
    if (!electronAPI) return;

    const language = useSettingsStore.getState().language;
    syncLanguage(language);

    const unsub = useSettingsStore.subscribe((state, prev) => {
      if (state.language !== prev.language) {
        syncLanguage(state.language);
      }
    });

    return unsub;
  }, []);
}

/**
 * Whether this runtime can choose a default folder for generated-file dialogs.
 * 当前运行环境是否支持选择生成文件保存对话框的默认文件夹（仅桌面版）。
 */
export function canPickGeneratedFileDirectory(): boolean {
  return typeof electronAPI?.pickGeneratedFileDirectory === "function";
}

/**
 * Open the native folder picker; return null on cancel and throw on failure.
 * 打开系统文件夹选择器；取消时返回 null，失败时抛错供界面显示提示。
 */
export async function pickGeneratedFileDirectory(): Promise<string | null> {
  const result = await electronAPI?.pickGeneratedFileDirectory?.();
  if (result?.status === "error") {
    throw new Error(result.code ?? "dialog-failed");
  }
  return result?.status === "selected" && result.directory ? result.directory : null;
}

/**
 * Keep the desktop main process in sync with the saved default folder.
 * 将设置中的默认保存文件夹同步给桌面主进程。
 */
export function useElectronGeneratedFileDirectorySync(): void {
  useEffect(() => {
    const setDirectory = electronAPI?.setGeneratedFileDirectory;
    if (!setDirectory) return;
    const push = (directory: string) => {
      void setDirectory(directory).catch(() => {
        // Best effort: the dialog falls back to the OS default folder.
      });
    };
    push(useSettingsStore.getState().generatedFileDirectory);
    return useSettingsStore.subscribe((state, prev) => {
      if (state.generatedFileDirectory !== prev.generatedFileDirectory) {
        push(state.generatedFileDirectory);
      }
    });
  }, []);
}
