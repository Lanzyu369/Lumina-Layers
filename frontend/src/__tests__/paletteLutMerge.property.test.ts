/**
 * Property-Based Tests: ColorWorkstation (Palette + LUT Merge)
 *
 * Feature: palette-lut-merge
 * Tests the correctness properties of the ColorWorkstation composite component.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { useWidgetStore, DEFAULT_LAYOUT } from '../stores/widgetStore';
import type { TabId } from '../types/widget';

type PersistMigrate = (persistedState: unknown, version: number) => unknown;
type PersistWithOptions = { getOptions: () => { migrate?: PersistMigrate } };

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null) {
    return value as Record<string, unknown>;
  }
  return {};
}

describe('Palette-LUT Merge Property-Based Tests', () => {
  beforeEach(() => {
    useWidgetStore.setState({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
      activeTab: 'converter' as TabId,
    });
  });

  // The legacy `colorWorkstationCollapsed` field and bottom-drawer ColorWorkstation
  // component have been removed; the color editor entry now lives in the top-level
  // secondary tab row. Only the persist-migration invariants below remain. 颜色编辑
  // 入口已迁至顶部二级 tab，仅保留持久化迁移不变式。
  describe.skip('Property 1–3 (legacy ColorWorkstation, retired)', () => {
    it.skip('placeholder', () => undefined);
  });

  // Feature: palette-lut-merge, Property 4: 持久化迁移正确性
  describe('Property 4: 持久化迁移正确性', () => {
    // Access the migrate function from Zustand persist options
    const persistApi = useWidgetStore.persist as unknown as PersistWithOptions;
    const migrate = persistApi.getOptions().migrate as PersistMigrate;

    // Generator for a single widget layout entry (simulates old persisted data)
    const widgetLayoutArb = fc.record({
      position: fc.record({ x: fc.integer({ min: 0, max: 1920 }), y: fc.integer({ min: 0, max: 1080 }) }),
      collapsed: fc.boolean(),
      visible: fc.boolean(),
      snapEdge: fc.constantFrom('left' as const, 'right' as const, null),
      stackOrder: fc.integer({ min: 0, max: 20 }),
      expandedHeight: fc.integer({ min: 100, max: 600 }),
    });

    // All current valid WidgetIds plus the two old ones that may exist in persisted data
    const allWidgetIds = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'fridge-magnet-settings', 'action-bar',
      'calibration', 'extractor', 'lut-manager', 'five-color',
      'palette-panel', 'lut-color-grid',
    ] as const;

    // Generator for a persisted state with random subset of widgets (always includes the two old ones)
    const persistedStateArb = fc
      .tuple(
        // Generate layout entries for each possible widget id
        ...allWidgetIds.map((id) =>
          fc.tuple(fc.constant(id), fc.option(widgetLayoutArb, { nil: undefined }))
        )
      )
      .chain((entries) => {
        // Build widgets record from generated entries, always include palette-panel and lut-color-grid
        return widgetLayoutArb.chain((palLayout) =>
          widgetLayoutArb.map((lutLayout) => {
            const widgets: Record<string, unknown> = {};
            for (const [id, layout] of entries) {
              if (layout !== undefined) {
                widgets[id] = { id, ...layout };
              }
            }
            // Ensure old WidgetIds are always present to test removal
            widgets['palette-panel'] = { id: 'palette-panel', ...palLayout };
            widgets['lut-color-grid'] = { id: 'lut-color-grid', ...lutLayout };
            return {
              widgets,
              activeTab: 'converter',
              colorWorkstationCollapsed: false,
            };
          })
        );
      });

    it('migration result never contains palette-panel or lut-color-grid keys', () => {
      // **Validates: Requirements 5.1, 5.2, 5.3**
      //
      // For any version (0-5) and any persisted state containing old WidgetIds,
      // the migrate function must produce a result without 'palette-panel' or 'lut-color-grid'.
      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: 6 }),
          persistedStateArb,
          (version: number, persistedState: Record<string, unknown>) => {
            const result = migrate(persistedState, version);
            const resultWidgets = asRecord(asRecord(result).widgets);

            // Core invariant: old WidgetIds must never exist after migration
            expect(resultWidgets).not.toHaveProperty('palette-panel');
            expect(resultWidgets).not.toHaveProperty('lut-color-grid');
            // colorWorkstationCollapsed has been retired; migration must drop it.
            expect(asRecord(result)).not.toHaveProperty('colorWorkstationCollapsed');
          }
        ),
        { numRuns: 100 }
      );
    });

    it('version < 3 resets to DEFAULT_LAYOUT without old WidgetIds', () => {
      // **Validates: Requirements 5.2**
      //
      // When version < 3, migration should reset to the new DEFAULT_LAYOUT.
      // The result widgets must exactly match DEFAULT_LAYOUT keys.
      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: 2 }),
          persistedStateArb,
          (version: number, persistedState: Record<string, unknown>) => {
            const result = migrate(persistedState, version);
            const resultWidgets = asRecord(asRecord(result).widgets);

            // Should match DEFAULT_LAYOUT keys exactly
            const defaultKeys = Object.keys(DEFAULT_LAYOUT).sort();
            const resultKeys = Object.keys(resultWidgets).sort();
            expect(resultKeys).toEqual(defaultKeys);

            // DEFAULT_LAYOUT itself must not contain old WidgetIds
            expect(defaultKeys).not.toContain('palette-panel');
            expect(defaultKeys).not.toContain('lut-color-grid');
          }
        ),
        { numRuns: 100 }
      );
    });

    it('version 3-6 drops removed widgets and seeds the full default layout', () => {
      // **Validates: Requirements 5.1 + the v7 → v8 sanitize step**
      //
      // Migration drops 'palette-panel', 'lut-color-grid' (legacy v6
      // removal) **and any widget id whose layout no longer exists in
      // DEFAULT_LAYOUT** (added in the v8 sanitize pass when MLS-only
      // tabs/widgets like ``lut-manager`` were removed from the
      // converter app), then seeds every still-default widget. The
      // pre-MLS expectation that only 'fridge-magnet-settings' +
      // 'puzzle-settings' got injected no longer holds.
      // 迁移会丢弃 'palette-panel'、'lut-color-grid'（v6 旧迁移），并丢弃
      // DEFAULT_LAYOUT 中已不存在的 widget（v8 sanitize 添加，对应 MLS 解耦
      // 后从转换器移除的 widget），再补齐所有保留的默认 widget。
      const expectedDefaultIds = new Set(Object.keys(DEFAULT_LAYOUT));
      fc.assert(
        fc.property(
          fc.constantFrom(3, 4, 5, 6),
          persistedStateArb,
          (version: number, persistedState: Record<string, unknown>) => {
            const inputWidgets = asRecord(persistedState.widgets);
            const expectedRetained = Object.keys(inputWidgets).filter(
              (k) =>
                k !== 'palette-panel' &&
                k !== 'lut-color-grid' &&
                expectedDefaultIds.has(k),
            );

            const result = migrate(persistedState, version);
            const resultWidgets = asRecord(asRecord(result).widgets);
            const resultKeys = Object.keys(resultWidgets);

            // Retained input widgets that still exist in DEFAULT_LAYOUT
            // must survive. (输入中仍存在于 DEFAULT_LAYOUT 的 widget 必须存活)
            for (const key of expectedRetained) {
              expect(resultKeys).toContain(key);
            }
            // The fridge widget is among the seeded defaults.
            // (fridge widget 必须出现作为兼容性锚点)
            expect(resultWidgets).toHaveProperty('fridge-magnet-settings');
            // Removed widgets must not survive. (旧 widget 不能残留)
            expect(resultWidgets).not.toHaveProperty('palette-panel');
            expect(resultWidgets).not.toHaveProperty('lut-color-grid');
            // Every result key must be a current default widget id.
            // (结果中只能包含当前默认布局已知的 widget)
            for (const key of resultKeys) {
              expect(expectedDefaultIds.has(key)).toBe(true);
            }

            // The legacy collapsed flag must be dropped, not propagated.
            // (旧 collapsed 字段必须丢弃)
            expect(asRecord(result)).not.toHaveProperty('colorWorkstationCollapsed');
          }
        ),
        { numRuns: 100 }
      );
    });

    it('version 3-6 reorders right-dock converter widgets to unique stack orders', () => {
      const persistedState = {
        widgets: {
          'action-bar': { ...DEFAULT_LAYOUT['action-bar'], stackOrder: 0, snapEdge: 'right' as const },
          'keychain-loop': { ...DEFAULT_LAYOUT['keychain-loop'], stackOrder: 1, snapEdge: 'right' as const },
          'advanced-settings': { ...DEFAULT_LAYOUT['advanced-settings'], stackOrder: 2, snapEdge: 'right' as const },
        },
        activeTab: 'converter',
      };

      for (const version of [3, 4, 5, 6] as const) {
        const result = migrate(persistedState, version);
        const widgets = asRecord(asRecord(result).widgets) as Record<string, { stackOrder: number; snapEdge: string | null }>;
        const rightOrders = ['action-bar', 'keychain-loop', 'fridge-magnet-settings', 'puzzle-settings', 'advanced-settings']
          .map((id) => widgets[id])
          .filter((widget) => widget?.snapEdge === 'right')
          .map((widget) => widget.stackOrder);
        const sortedRightOrders = [...rightOrders].sort((a, b) => a - b);

        expect(sortedRightOrders).toEqual(Array.from({ length: rightOrders.length }, (_, index) => index));
        expect(new Set(rightOrders).size).toBe(rightOrders.length);
      }
    });
  });
});
