import { translations } from "./translations"
import { useSettingsStore } from "../stores/settingsStore"

export function tRuntime(
  key: string,
  params: Record<string, string | number> = {},
): string {
  const lang = useSettingsStore.getState().language
  const template = translations[key]?.[lang] ?? translations[key]?.zh ?? key
  return template.replace(/\{(\w+)\}/g, (_match, paramKey) => {
    const value = params[paramKey]
    return value === undefined ? `{${paramKey}}` : String(value)
  })
}

