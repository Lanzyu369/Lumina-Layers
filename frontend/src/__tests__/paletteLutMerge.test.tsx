/**
 * Unit tests for Palette-LUT Merge (ColorWorkstation).
 * 调色板-LUT 合并（ColorWorkstation）单元测试。
 *
 * Validates registry cleanup, translations, persist version,
 * and ColorWorkstation rendering behavior.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { translations } from '../i18n/translations';
import {
  useWidgetStore,
  TAB_WIDGET_MAP,
  WIDGET_REGISTRY,
  DEFAULT_LAYOUT,
} from '../stores/widgetStore';
import type { TabId } from '../types/widget';

// The legacy ColorWorkstation bottom drawer has been replaced by a top-level
// secondary tab entry; this file now covers registry / translation / persist
// invariants only. 颜色编辑入口已迁移到顶部二级 tab，此处仅校验注册表/翻译/持久化版本。

describe('Palette-LUT Merge Unit Tests', () => {
  beforeEach(() => {
    useWidgetStore.setState({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
      activeTab: 'converter' as TabId,
    });
  });

  // ===== 注册表清理验证 =====
  describe('Registry cleanup — old WidgetIds removed', () => {
    it('TAB_WIDGET_MAP does not contain palette-panel or lut-color-grid', () => {
      // Requirements 3.2
      for (const [, widgetIds] of Object.entries(TAB_WIDGET_MAP)) {
        expect(widgetIds).not.toContain('palette-panel');
        expect(widgetIds).not.toContain('lut-color-grid');
      }
    });

    it('WIDGET_REGISTRY does not contain palette-panel or lut-color-grid', () => {
      // Requirements 3.4
      const registryIds = WIDGET_REGISTRY.map((w) => w.id);
      expect(registryIds).not.toContain('palette-panel');
      expect(registryIds).not.toContain('lut-color-grid');
    });

    it('DEFAULT_LAYOUT does not contain palette-panel or lut-color-grid', () => {
      // Requirements 3.3
      const layoutIds = Object.keys(DEFAULT_LAYOUT);
      expect(layoutIds).not.toContain('palette-panel');
      expect(layoutIds).not.toContain('lut-color-grid');
    });
  });

  // ===== 翻译字典验证 =====
  describe('Translation dictionary', () => {
    it('contains widget.colorWorkstation with zh and en entries', () => {
      // Requirements 6.1, 6.2
      const entry = translations['widget.colorWorkstation'];
      expect(entry).toBeDefined();
      expect(entry.zh).toBe('颜色工作站');
      expect(entry.en).toBe('Color Workstation');
    });
  });

  // ===== Persist version 验证 =====
  describe('Persist version', () => {
    it('persist version is 8', () => {
      // v6 -> v7: colour entry moved to a top-level secondary tab; dropped
      // colorWorkstationCollapsed.
      // v7 -> v8: persisted ``activeTab`` could point at a tab that was
      // removed during the MLS decouple (gradient-card-extract / -generate
      // / extractor / calibration), causing TAB_WIDGET_MAP[activeTab] to
      // return undefined and crashing App.tsx; the migrate now sanitizes
      // unknown tab ids back to "converter".
      // v6→v7：颜色入口迁移到顶部二级 tab，丢弃 colorWorkstationCollapsed。
      // v7→v8：MLS 解耦后持久化 activeTab 可能指向已删 tab，迁移时清回 "converter"。
      const options = (
        useWidgetStore.persist as unknown as { getOptions: () => { version: number } }
      ).getOptions();
      expect(options.version).toBe(8);
    });
  });
});
