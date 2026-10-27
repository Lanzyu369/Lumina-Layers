# Viewer Hover Toggle I18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the missing localized labels for the Color Workstation hover toggles so `PalettePanel` no longer renders raw i18n keys.

**Architecture:** Keep the fix narrowly scoped to the frontend i18n dictionary and a focused regression test. Use TDD: add a failing translation regression test first, then restore the three missing translation entries referenced by `PalettePanel`.

**Tech Stack:** React 19, TypeScript, Vitest

---

### Task 1: Restore PalettePanel hover-toggle translations

**Files:**
- Modify: `frontend/src/__tests__/freeColor.test.ts`
- Modify: `frontend/src/i18n/translations.ts`
- Verify against: `frontend/src/components/sections/PalettePanel.tsx`

- [ ] **Step 1: Write the failing test**

```ts
  it("viewer hover toggle labels exist with zh/en", () => {
    expect(translations.viewer_hover_toggle_group).toBeDefined();
    expect(translations.viewer_hover_toggle_group.zh).toBe("悬停显示");
    expect(translations.viewer_hover_toggle_group.en).toBe("Hover Display");

    expect(translations.viewer_hover_toggle_magnifier).toBeDefined();
    expect(translations.viewer_hover_toggle_magnifier.zh).toBe("放大镜");
    expect(translations.viewer_hover_toggle_magnifier.en).toBe("Magnifier");

    expect(translations.viewer_hover_toggle_layers).toBeDefined();
    expect(translations.viewer_hover_toggle_layers.zh).toBe("分层颜色");
    expect(translations.viewer_hover_toggle_layers.en).toBe("Layer Colors");
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest --run src/__tests__/freeColor.test.ts`
Expected: FAIL because `translations.viewer_hover_toggle_group`, `translations.viewer_hover_toggle_magnifier`, and `translations.viewer_hover_toggle_layers` are currently missing.

- [ ] **Step 3: Write minimal implementation**

```ts
  viewer_hover_toggle_group: {
    zh: "悬停显示",
    en: "Hover Display",
  },
  viewer_hover_toggle_magnifier: {
    zh: "放大镜",
    en: "Magnifier",
  },
  viewer_hover_toggle_layers: {
    zh: "分层颜色",
    en: "Layer Colors",
  },
```

Insert the entries in `frontend/src/i18n/translations.ts` near the existing `viewer_hover_*` keys so the dictionary remains grouped by viewer-related labels.

- [ ] **Step 4: Run tests to verify they pass**

Run:
- `npx vitest --run src/__tests__/freeColor.test.ts`
- `npx vitest --run src/__tests__/i18n-keys-completeness.test.ts`

Expected: PASS. The targeted regression test should confirm the zh/en strings, and the completeness test should confirm `PalettePanel.tsx` no longer references missing literal keys.

- [ ] **Step 5: Self-review the touched files**

Confirm:
- `frontend/src/components/sections/PalettePanel.tsx` still references only those three keys and needs no logic change
- `frontend/src/i18n/translations.ts` remains UTF-8 and contains no mojibake markers
- No unrelated frontend strings or store logic were changed
