import { useEffect } from "react";
import { useSettingsStore } from "../stores/settingsStore";

interface ElectronAPI {
  setLanguage: (lang: string) => void;
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

/**
 * Whether this runtime can choose a default folder for generated-file dialogs.
 * 当前运行环境是否支持选择生成文件保存对话框的默认文件夹（仅桌面版）。
 */
export function canPickGeneratedFileDirectory(): boolean {
  return typeof electronAPI?.pickGeneratedFileDirectory === "function";
}

/**
 * Open the native folder picker; returns the chosen folder or null.
 * 打开系统文件夹选择器；返回选中的文件夹，取消或失败时返回 null。
 */
export async function pickGeneratedFileDirectory(): Promise<string | null> {
  const result = await electronAPI?.pickGeneratedFileDirectory?.();
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
