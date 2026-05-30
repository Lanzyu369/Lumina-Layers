import { useCallback } from "react";
import { translations, interpolate, type TranslationKey } from "./translations";
import { useUiStore } from "../stores/uiStore";

/**
 * 翻译 Hook：根据当前语言返回 ``t(key, vars?)`` 函数。
 * 所有 UI 文案都通过它取用，禁止在组件内硬编码中英文字符串。
 */
export function useT(): (key: TranslationKey, vars?: Record<string, string | number>) => string {
  const language = useUiStore((s) => s.language);
  return useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      const dict = translations[language];
      const template = dict[key] ?? key;
      return interpolate(template, vars);
    },
    [language],
  );
}
