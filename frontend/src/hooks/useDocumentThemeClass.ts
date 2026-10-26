import { useLayoutEffect } from "react";
import { useSettingsStore } from "../stores/settingsStore";
import { electronAPI } from "../integrations/electron";

/**
 * Mirror the persisted theme onto the root element's ``dark`` class.
 * 将持久化的主题同步到根元素的 dark 类。
 *
 * Must stay mounted for the whole app lifetime; the theme switch itself
 * lives in a collapsible header menu that is not always rendered. A layout
 * effect sets the class before first paint and before any child's passive
 * effect, which can read it (the five-color canvas draws on mount).
 * 需在应用整个生命周期内保持挂载；主题开关位于可折叠的顶栏菜单中，并非一直渲染。
 * 使用 layout effect，保证在首次绘制和任何子组件的普通 effect 之前设置好该类
 * （五色查询画布在挂载时就会读取它来绘制）。
 */
export function useDocumentThemeClass(): void {
  const theme = useSettingsStore((s) => s.theme);

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    if (electronAPI?.platform === "win32") electronAPI.setTitlebarTheme?.(theme);
  }, [theme]);
}
