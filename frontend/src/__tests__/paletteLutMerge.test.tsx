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
  MAIN_RENDERABLE_TABS,
  isMainRenderableTab,
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

  // ===== Main-app renderable-tab boundary =====
  // Regression for the MLS-decouple stale-activeTab bug: the shared widget
  // store keeps MLS-only tab ids valid (the MLS frontend reuses this store as
  // its router), so a persisted ``activeTab`` like "calibration" survives the
  // v8 migration. The main app must coerce such non-renderable tabs to
  // "converter" at its boundary, otherwise it renders an empty workspace.
  // 共享 store 保留 MLS 标签 id 有效（MLS 前端复用此 store 作路由），故持久化的
  // activeTab（如 "calibration"）在 v8 迁移后仍有效；主应用须在边界把这类不可渲染
  // 标签归位到 "converter"，否则渲染空工作区。
  describe('Main-app renderable tabs', () => {
    it('MAIN_RENDERABLE_TABS holds exactly converter / vectorizer / settings', () => {
      expect([...MAIN_RENDERABLE_TABS].sort()).toEqual(
        ['converter', 'settings', 'vectorizer'],
      );
    });

    it('isMainRenderableTab accepts the three main tabs', () => {
      expect(isMainRenderableTab('converter')).toBe(true);
      expect(isMainRenderableTab('vectorizer')).toBe(true);
      expect(isMainRenderableTab('settings')).toBe(true);
    });

    it('isMainRenderableTab rejects MLS-only material/LUT tabs', () => {
      const mlsOnly: TabId[] = [
        'calibration',
        'extractor',
        'gradient-card-generate',
        'gradient-card-extract',
        'material-library',
        'material-recipe',
        'lut-manager',
        'lut-details',
        'lut-compare',
        'five-color',
      ];
      for (const tab of mlsOnly) {
        expect(isMainRenderableTab(tab)).toBe(false);
      }
    });

    it('every MLS-only tab is still a valid TAB_WIDGET_MAP key (shared router contract)', () => {
      // The coercion lives at the app boundary precisely because the shared
      // store cannot drop these ids without breaking the MLS frontend.
      // 归位逻辑放在应用边界，正是因为共享 store 不能删除这些 id（否则破坏 MLS 前端）。
      const mlsOnly: TabId[] = ['calibration', 'lut-manager', 'material-library'];
      for (const tab of mlsOnly) {
        expect(Object.keys(TAB_WIDGET_MAP)).toContain(tab);
        expect(isMainRenderableTab(tab)).toBe(false);
      }
    });
  });
});
