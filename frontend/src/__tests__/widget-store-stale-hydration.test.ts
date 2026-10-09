/**
 * Regression tests for stale SAME-version widget layout hydration.
 * 「同版本但过时」的 Widget 布局水合回归测试。
 *
 * Zustand persist skips ``migrate`` entirely when the stored version equals
 * the current version, so a payload written before
 * ``model-surface-settings`` joined DEFAULT_LAYOUT used to bypass the
 * sanitizer. The custom ``merge`` option must backfill every missing
 * DEFAULT_LAYOUT id on EVERY hydration, regardless of stored version.
 * A second wave of coverage covers the v8→v9 bump: layouts persisted earlier
 * on the day model-surface-settings shipped (v8, already containing the id)
 * must migrate with their entry relocated before ``basic-settings``.
 * 当存储版本与当前版本一致时，Zustand persist 会完全跳过 ``migrate``，
 * 导致早于新增 widget（如 model-surface-settings）写入的载荷绕过清洗。
 * 自定义 ``merge`` 必须在每次水合时补齐所有缺失的 DEFAULT_LAYOUT 条目。
 * 另一组用例覆盖 v8→v9 升级：当天更早写入、已包含该 id 的 v8 布局在迁移后，
 * 其条目必须被前移到 ``basic-settings`` 之前。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const STORAGE_KEY = "lumina-widget-layout";

/** Seed a realistic stale v8 payload that predates model-surface-settings. */
function seedStaleV8Layout(): void {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      state: {
        widgets: {
          "basic-settings": {
            position: { x: 12, y: 34 },
            collapsed: false,
            visible: true,
            snapEdge: "left",
            stackOrder: 0,
            expandedHeight: 655,
          },
          "action-bar": {
            position: { x: 900, y: 10 },
            collapsed: false,
            visible: true,
            snapEdge: "right",
            stackOrder: 0,
            expandedHeight: 420,
          },
          // A removed id lingering from an even older payload.
          "palette-panel": {
            position: { x: 0, y: 0 },
            collapsed: false,
            visible: false,
            snapEdge: null,
            stackOrder: -1,
            expandedHeight: 400,
          },
        },
        activeTab: "converter",
      },
      version: 8,
    }),
  );
}

/**
 * Seed a v8 payload persisted AFTER model-surface-settings shipped (earlier
 * on the same day): it already contains the id, listed after basic-settings.
 */
function seedV8LayoutWithModelSurface(): void {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      state: {
        widgets: {
          "basic-settings": {
            position: { x: 0, y: 0 },
            collapsed: false,
            visible: true,
            snapEdge: "left",
            stackOrder: 0,
            expandedHeight: 655,
          },
          "model-surface-settings": {
            position: { x: 0, y: 0 },
            collapsed: false,
            visible: true,
            snapEdge: "left",
            stackOrder: 0,
            expandedHeight: 480,
          },
        },
        activeTab: "converter",
      },
      version: 8,
    }),
  );
}

describe("widget store stale same-version hydration", () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  it("hydrates cleanly when no saved layout exists", async () => {
    const { useWidgetStore, DEFAULT_LAYOUT } = await import(
      "../stores/widgetStore"
    );

    await useWidgetStore.persist.rehydrate();

    expect(useWidgetStore.persist.hasHydrated()).toBe(true);
    expect(useWidgetStore.getState().widgets).toEqual(DEFAULT_LAYOUT);
  });

  it("backfills model-surface-settings with its DEFAULT_LAYOUT values", async () => {
    seedStaleV8Layout();

    const { useWidgetStore, DEFAULT_LAYOUT } = await import(
      "../stores/widgetStore"
    );
    await useWidgetStore.persist.rehydrate();

    const state = useWidgetStore.getState();
    expect(state.widgets["model-surface-settings"]).toEqual(
      DEFAULT_LAYOUT["model-surface-settings"],
    );
    expect(state.widgets["model-surface-settings"].visible).toBe(true);
    expect(state.widgets["model-surface-settings"].collapsed).toBe(false);
    expect(state.widgets["model-surface-settings"].snapEdge).toBe("left");
  });

  it("contains every DEFAULT_LAYOUT id after hydration", async () => {
    seedStaleV8Layout();

    const { useWidgetStore, DEFAULT_LAYOUT } = await import(
      "../stores/widgetStore"
    );
    await useWidgetStore.persist.rehydrate();

    const widgets = useWidgetStore.getState()
      .widgets as unknown as Record<string, unknown>;
    for (const id of Object.keys(DEFAULT_LAYOUT)) {
      expect(widgets[id], `widget "${id}" should be backfilled`).toBeDefined();
    }
  });

  it("keeps user-customized entries and drops removed ids during same-version hydration", async () => {
    seedStaleV8Layout();

    const { useWidgetStore } = await import("../stores/widgetStore");
    await useWidgetStore.persist.rehydrate();

    const state = useWidgetStore.getState();
    expect(state.widgets["basic-settings"].position).toEqual({ x: 12, y: 34 });
    expect(state.widgets["action-bar"].snapEdge).toBe("right");
    expect(
      (state.widgets as unknown as Record<string, unknown>)["palette-panel"],
    ).toBeUndefined();
    expect(state.activeTab).toBe("converter");
  });

  it("also backfills when the stored version is older and migrate already ran", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        state: {
          widgets: {
            "basic-settings": {
              position: { x: 1, y: 2 },
              collapsed: false,
              visible: true,
              snapEdge: "left",
              stackOrder: 0,
              expandedHeight: 400,
            },
          },
          activeTab: "converter",
        },
        version: 5,
      }),
    );

    const { useWidgetStore } = await import("../stores/widgetStore");
    await useWidgetStore.persist.rehydrate();

    const state = useWidgetStore.getState();
    expect(state.widgets["model-surface-settings"]).toBeDefined();
    expect(state.widgets["fridge-magnet-settings"]).toBeDefined();
    expect(state.widgets["puzzle-settings"]).toBeDefined();
  });

  it("relocates an existing model-surface-settings entry before basic-settings during the v8→v9 migration", async () => {
    seedV8LayoutWithModelSurface();

    const { useWidgetStore } = await import("../stores/widgetStore");
    await useWidgetStore.persist.rehydrate();

    const state = useWidgetStore.getState();
    // The user's persisted layout values survive the migration untouched...
    expect(state.widgets["model-surface-settings"].expandedHeight).toBe(480);
    expect(state.widgets["basic-settings"].position).toEqual({ x: 0, y: 0 });
    // ...but the record order now lists model-surface-settings first, matching
    // the new default left-dock order (record order feeds autoArrange and
    // equal-stackOrder tie-breaks).
    const keyOrder = Object.keys(state.widgets);
    expect(keyOrder.indexOf("model-surface-settings")).toBeLessThan(
      keyOrder.indexOf("basic-settings"),
    );
  });

  it("keeps the relocated order stable across a rehydration round-trip", async () => {
    seedV8LayoutWithModelSurface();

    const { useWidgetStore } = await import("../stores/widgetStore");
    await useWidgetStore.persist.rehydrate();

    // Simulate a reload: persist current state, then rehydrate from storage.
    useWidgetStore.getState().toggleCollapse("basic-settings");
    const stored = JSON.parse(
      localStorage.getItem(STORAGE_KEY) ?? "{}",
    ) as { state?: { widgets?: Record<string, unknown> } };
    expect(
      Object.keys(stored.state?.widgets ?? {}).indexOf(
        "model-surface-settings",
      ),
    ).toBeLessThan(
      Object.keys(stored.state?.widgets ?? {}).indexOf("basic-settings"),
    );

    await useWidgetStore.persist.rehydrate();
    const keyOrder = Object.keys(useWidgetStore.getState().widgets);
    expect(keyOrder.indexOf("model-surface-settings")).toBeLessThan(
      keyOrder.indexOf("basic-settings"),
    );
    expect(useWidgetStore.getState().widgets["basic-settings"].collapsed).toBe(
      true,
    );
  });

  it("pins record key order after stale-v8-without-id hydration: model-surface-settings precedes basic-settings in the rehydrated and re-persisted record", async () => {
    seedStaleV8Layout();

    const { useWidgetStore } = await import("../stores/widgetStore");
    await useWidgetStore.persist.rehydrate();

    const state = useWidgetStore.getState();
    const keyOrder = Object.keys(state.widgets);
    // DEFAULT_LAYOUT intent: model-surface-settings sits immediately before
    // basic-settings; the backfilled entry must not trail the user's entries.
    expect(keyOrder.indexOf("model-surface-settings")).toBeLessThan(
      keyOrder.indexOf("basic-settings"),
    );
    expect(keyOrder.indexOf("basic-settings")).toBe(
      keyOrder.indexOf("model-surface-settings") + 1,
    );
    expect(state.widgets["basic-settings"].position).toEqual({ x: 12, y: 34 });
    expect(state.widgets["action-bar"].position).toEqual({ x: 900, y: 10 });

    // The healed order survives re-persisting (order feeds autoArrange and
    // equal-stackOrder tie-breaks after a reload).
    useWidgetStore.getState().toggleCollapse("action-bar");
    const stored = JSON.parse(
      localStorage.getItem(STORAGE_KEY) ?? "{}",
    ) as {
      version?: number;
      state?: { widgets?: Record<string, unknown> };
    };
    expect(stored.version).toBe(9);
    const persistedOrder = Object.keys(stored.state?.widgets ?? {});
    expect(persistedOrder.indexOf("model-surface-settings")).toBeLessThan(
      persistedOrder.indexOf("basic-settings"),
    );

    await useWidgetStore.persist.rehydrate();
    const reloadedOrder = Object.keys(useWidgetStore.getState().widgets);
    expect(reloadedOrder.indexOf("model-surface-settings")).toBeLessThan(
      reloadedOrder.indexOf("basic-settings"),
    );
  });

  it("repairs a same-version v9 record whose model-surface-settings entry trails basic-settings via merge-path promotion", async () => {
    // Shape of a v9 payload written by the pre-fix merge path: migrate already
    // backfilled the id behind basic-settings and that order was persisted.
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        state: {
          widgets: {
            "basic-settings": {
              position: { x: 12, y: 34 },
              collapsed: false,
              visible: true,
              snapEdge: "left",
              stackOrder: 0,
              expandedHeight: 655,
            },
            "action-bar": {
              position: { x: 900, y: 10 },
              collapsed: false,
              visible: true,
              snapEdge: "right",
              stackOrder: 0,
              expandedHeight: 420,
            },
            "model-surface-settings": {
              position: { x: 0, y: 0 },
              collapsed: false,
              visible: true,
              snapEdge: "left",
              stackOrder: 0,
              expandedHeight: 400,
            },
          },
          activeTab: "converter",
        },
        version: 9,
      }),
    );

    const { useWidgetStore } = await import("../stores/widgetStore");
    await useWidgetStore.persist.rehydrate();

    // Stored version equals the current version, so ``migrate`` is skipped
    // entirely; only the merge-path promotion can realign the record.
    const keyOrder = Object.keys(useWidgetStore.getState().widgets);
    expect(keyOrder.indexOf("model-surface-settings")).toBeLessThan(
      keyOrder.indexOf("basic-settings"),
    );
    expect(useWidgetStore.getState().widgets["model-surface-settings"]
      .expandedHeight).toBe(400);

    useWidgetStore.getState().toggleCollapse("basic-settings");
    const stored = JSON.parse(
      localStorage.getItem(STORAGE_KEY) ?? "{}",
    ) as { state?: { widgets?: Record<string, unknown> } };
    const persistedOrder = Object.keys(stored.state?.widgets ?? {});
    expect(persistedOrder.indexOf("model-surface-settings")).toBeLessThan(
      persistedOrder.indexOf("basic-settings"),
    );
  });
});
