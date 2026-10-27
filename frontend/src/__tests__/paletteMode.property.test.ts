import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { SettingsState } from "../stores/settingsStore";

// ========== Helpers ==========

function resetStore() {
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  localStorage.clear();
}

// ========== Generators ==========

const arbPaletteMode = fc.constantFrom("swatch" as const, "card" as const);

// ========== Property 1: paletteMode persistence round-trip ==========

// **Validates: Requirements 1.1, 1.2, 1.3**
describe("Feature: swatch-style-toggle, Property 1: paletteMode persistence round-trip", () => {
  beforeEach(() => {
    resetStore();
  });

  it("setPaletteMode writes to store state correctly", () => {
    fc.assert(
      fc.property(arbPaletteMode, (mode) => {
        // Reset before each iteration
        localStorage.clear();
        useSettingsStore.setState({ ...DEFAULT_SETTINGS });

        // Write via the action (Req 1.1: paletteMode field exists, Req 1.2: persists)
        useSettingsStore.getState().setPaletteMode(mode);

        // Verify store state matches
        const storeValue = useSettingsStore.getState().paletteMode;
        expect(storeValue).toBe(mode);
      }),
      { numRuns: 100 }
    );
  });

  it("paletteMode persists to localStorage and can be restored (round-trip)", () => {
    fc.assert(
      fc.property(arbPaletteMode, (mode) => {
        // Reset before each iteration
        localStorage.clear();
        useSettingsStore.setState({ ...DEFAULT_SETTINGS });

        // Write via the action
        useSettingsStore.getState().setPaletteMode(mode);

        // Read persisted data from localStorage (Req 1.2: persist to localStorage)
        const raw = localStorage.getItem("lumina-settings");
        expect(raw).not.toBeNull();

        const parsed = JSON.parse(raw!);
        const persisted: SettingsState = parsed.state;

        // Verify localStorage round-trip (Req 1.3: restore on reload)
        expect(persisted.paletteMode).toBe(mode);
      }),
      { numRuns: 100 }
    );
  });

  it("sequential paletteMode changes always reflect the last written value", () => {
    fc.assert(
      fc.property(
        fc.array(arbPaletteMode, { minLength: 1, maxLength: 20 }),
        (modes) => {
          // Reset before each iteration
          localStorage.clear();
          useSettingsStore.setState({ ...DEFAULT_SETTINGS });

          // Apply a sequence of mode changes
          for (const mode of modes) {
            useSettingsStore.getState().setPaletteMode(mode);
          }

          const lastMode = modes[modes.length - 1];

          // Store state should reflect the last value
          expect(useSettingsStore.getState().paletteMode).toBe(lastMode);

          // localStorage should also reflect the last value
          const raw = localStorage.getItem("lumina-settings");
          expect(raw).not.toBeNull();
          const persisted: SettingsState = JSON.parse(raw!).state;
          expect(persisted.paletteMode).toBe(lastMode);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("default paletteMode is 'swatch' (Req 1.1)", () => {
    // Verify the default value from DEFAULT_SETTINGS
    expect(DEFAULT_SETTINGS.paletteMode).toBe("swatch");

    // Verify a fresh store has the default
    localStorage.clear();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    expect(useSettingsStore.getState().paletteMode).toBe("swatch");
  });
});
