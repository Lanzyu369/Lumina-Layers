import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Language } from "../i18n/translations";

export type ThemeMode = "light" | "dark";
export type ViewKey = "materials" | "lut" | "solver_cache";

interface UiState {
  language: Language;
  theme: ThemeMode;
  view: ViewKey;
  setLanguage: (language: Language) => void;
  toggleLanguage: () => void;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  setView: (view: ViewKey) => void;
}

/** 全局 UI 偏好（语言/主题/当前视图），持久化到 localStorage */
export const useUiStore = create<UiState>()(
  persist(
    (set, get) => ({
      language: "zh",
      theme: "light",
      view: "materials",
      setLanguage: (language) => set({ language }),
      toggleLanguage: () => set({ language: get().language === "zh" ? "en" : "zh" }),
      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set({ theme: get().theme === "light" ? "dark" : "light" }),
      setView: (view) => set({ view }),
    }),
    { name: "mls-ui-preferences" },
  ),
);
