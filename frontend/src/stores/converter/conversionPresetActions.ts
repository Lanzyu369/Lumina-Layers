import type { StoreApi } from "zustand";
import { useSettingsStore } from "../settingsStore";
  type ConversionParameters, type ConversionPreferences } from "../conversionPreferences";
import type { ConverterActions, ConverterState } from "./types";

type Store = ConverterState & ConverterActions;
type Actions = Pick<ConverterActions, "restoreConversionDefaults" | "applyConversionPreset" |
  "saveConversionPreset" | "updateConversionPreset" | "renameConversionPreset" | "deleteConversionPreset">;

/** Own preset operations here; the UI only renders their results. */
export function createConversionPresetActions(set: StoreApi<Store>["setState"], get: () => Store): Actions {
  const preferences = () => useSettingsStore.getState().conversionPreferences;
  const save = (value: ConversionPreferences) => useSettingsStore.getState().setConversionPreferences(value);

  const restore = (parameters: ConversionParameters, selectedPresetId: string | null) => {
    const previousContext = get().conversionParameterContext;
    let completed = false;
    set({ conversionParameterContext: "restoring" });
    try {
      // Setters may change dependent fields. Always compare the live state.
      applyConversionParameters(get, parameters);
      save({ ...preferences(), last: captureConversionParameters(get()), selectedPresetId });
      completed = true;
    } finally {
      set({ conversionParameterContext: completed ? "defaults" : previousContext });
    }
  };

  return {
    restoreConversionDefaults: () => {
      const saved = preferences();
      if (saved.last) restore(saved.last, saved.selectedPresetId ?? null);
      else set({ conversionParameterContext: "defaults" });
    },
    applyConversionPreset: (id) => {
      const saved = preferences();
      const parameters = id === null ? saved.last : saved.presets.find(p => p.id === id)?.parameters;
      if (!parameters) return false;
      restore(parameters, id);
      return true;
    },
      const saved = preferences();
      const error = validatePresetName(name, saved.presets);
      if (error) return { error };
      set({ conversionParameterContext: "defaults" });
      return { id: preset.id };
    },
    updateConversionPreset: (id) => {
      const saved = preferences();
      save({ ...saved, presets: saved.presets.map(p => p.id === id ? { ...p, parameters } : p) });
      return true;
    },
    renameConversionPreset: (id, name) => {
      const saved = preferences();
      if (!saved.presets.some(p => p.id === id)) return "missing-preset";
      const error = validatePresetName(name, saved.presets, id);
      if (error) return error;
      save({ ...saved, presets: saved.presets.map(p => p.id === id ? { ...p, name: name.trim() } : p) });
      return null;
    },
    deleteConversionPreset: (id) => {
      const saved = preferences();
      save({ ...saved, selectedPresetId: saved.selectedPresetId === id ? null : saved.selectedPresetId,
        presets: saved.presets.filter(p => p.id !== id) });
    },
  };
}
