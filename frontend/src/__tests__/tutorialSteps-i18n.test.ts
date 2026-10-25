import { describe, expect, it } from "vitest";
import { collectTutorialStepKeys, TUTORIAL_STEPS } from "../data/tutorialSteps";
import { translations } from "../i18n/translations";

describe("beginner tutorial steps", () => {
  it("reference translation keys that exist with non-empty zh and en text", () => {
    const problems = collectTutorialStepKeys().filter((key) => {
      const entry = translations[key];
      return !entry || !entry.zh.trim() || !entry.en.trim();
    });
    expect(problems).toEqual([]);
  });

  it("have unique ids", () => {
    const ids = TUTORIAL_STEPS.map((step) => step.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("explain available color sources in selector order with a principle flow", () => {
    const sourceSteps = TUTORIAL_STEPS.filter((step) => step.id.startsWith("source-"));
    expect(sourceSteps.map((step) => step.id)).toEqual([
      "source-material-archive",
      "source-legacy-lut",
    ]);
    for (const step of sourceSteps) {
      expect(step.flowKeys?.length).toBeGreaterThanOrEqual(3);
      expect(step.needKey).toBeTruthy();
      expect(step.fitKey).toBeTruthy();
    }
  });
});
