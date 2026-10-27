/**
 * Property-Based Tests for Widget drag performance optimizations.
 * Widget 拖拽性能优化 Property-Based 测试。
 *
 * Tests pure utility functions extracted during the performance refactor.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  computeSnap,
  computeStackPositions,
  WIDGET_WIDTH,
  COLLAPSED_HEIGHT,
  EXPANDED_HEIGHT,
  STACK_GAP,
} from '../utils/widgetUtils';
import type { WidgetId, WidgetLayoutState } from '../types/widget';

describe('Widget Drag Performance Property-Based Tests', () => {
  describe('Nearest edge selection', () => {
    it('always returns a left or right edge, including drag overshoot', () => {
      fc.assert(
        fc.property(
          fc.double({ min: -2000, max: 5000, noNaN: true, noDefaultInfinity: true }),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgetLeft, containerWidth) => {
            expect(['left', 'right']).toContain(computeSnap(widgetLeft, widgetLeft + WIDGET_WIDTH, containerWidth));
          }
        ),
        { numRuns: 200, verbose: true }
      );
    });

    it('returns the same edge for identical inputs', () => {
      fc.assert(
        fc.property(
          fc.double({ min: -2000, max: 5000, noNaN: true, noDefaultInfinity: true }),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgetLeft, containerWidth) => {
            const widgetRight = widgetLeft + WIDGET_WIDTH;
            expect(computeSnap(widgetLeft, widgetRight, containerWidth)).toBe(computeSnap(widgetLeft, widgetRight, containerWidth));
          }
        ),
        { numRuns: 100 }
      );
    });

    it('snaps to the left when the widget center is in the left half', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          fc.double({ min: 1, max: 2000, noNaN: true, noDefaultInfinity: true }),
          (containerWidth, offset) => {
            const widgetLeft = (containerWidth - WIDGET_WIDTH) / 2 - offset;
            expect(computeSnap(widgetLeft, widgetLeft + WIDGET_WIDTH, containerWidth)).toBe('left');
          }
        ),
        { numRuns: 100 }
      );
    });

    it('snaps to the right when the widget center is in the right half', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          fc.double({ min: 1, max: 2000, noNaN: true, noDefaultInfinity: true }),
          (containerWidth, offset) => {
            const widgetLeft = (containerWidth - WIDGET_WIDTH) / 2 + offset;
            expect(computeSnap(widgetLeft, widgetLeft + WIDGET_WIDTH, containerWidth)).toBe('right');
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Feature: slider-drag-performance, Property 2: computeStackPositions 产生无重叠布局
  describe('Property 2: computeStackPositions 产生无重叠布局', () => {
    // All valid WidgetId values for generating realistic widgets
    const WIDGET_IDS: WidgetId[] = [
      'basic-settings', 'advanced-settings', 'relief-settings',
      'outline-settings', 'cloisonne-settings', 'coating-settings',
      'keychain-loop', 'fridge-magnet-settings', 'puzzle-settings', 'action-bar'];

    /**
     * Smart generator: creates a valid WidgetLayoutState with unique id and stackOrder.
     * Uses the provided index to pick a unique WidgetId and assign stackOrder.
     */
    const arbWidgetLayout = (index: number): fc.Arbitrary<WidgetLayoutState> =>
      fc.record({
        id: fc.constant(WIDGET_IDS[index % WIDGET_IDS.length]),
        position: fc.record({
          x: fc.integer({ min: 0, max: 3000 }),
          y: fc.integer({ min: 0, max: 3000 }),
        }),
        collapsed: fc.boolean(),
        visible: fc.constant(true),
        snapEdge: fc.constantFrom('left' as const, 'right' as const),
        stackOrder: fc.constant(index),
        expandedHeight: fc.integer({ min: COLLAPSED_HEIGHT + 10, max: 800 }),
      });

    /**
     * Generator for a list of 1..N widgets with unique IDs and sequential stackOrder.
     */
    const arbWidgetList = (maxCount: number = 8): fc.Arbitrary<WidgetLayoutState[]> =>
      fc.integer({ min: 1, max: Math.min(maxCount, WIDGET_IDS.length) }).chain((count) =>
        fc.tuple(...Array.from({ length: count }, (_, i) => arbWidgetLayout(i))).map(
          (widgets) => widgets
        )
      );

    /**
     * **Validates: Requirements 5.2, 5.4**
     *
     * For any valid widget list with different collapsed states and expandedHeights,
     * computeStackPositions returns positions where adjacent widgets (sorted by stackOrder)
     * satisfy: prev.y + height + STACK_GAP === next.y.
     * For identical inputs, results are always consistent (pure function).
     */
    it('produces non-overlapping layout for adjacent stacked widgets', () => {
      // **Validates: Requirements 5.2, 5.4**
      fc.assert(
        fc.property(
          arbWidgetList(),
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgets, edge, containerWidth) => {
            const positions = computeStackPositions(widgets, edge, containerWidth);

            // Sort widgets by stackOrder (same as the function does internally)
            const sorted = [...widgets].sort((a, b) => a.stackOrder - b.stackOrder);

            // Every widget should have a computed position
            expect(positions.size).toBe(widgets.length);

            // Check adjacent pairs: prev.y + height + STACK_GAP === next.y
            for (let i = 0; i < sorted.length - 1; i++) {
              const curr = sorted[i];
              const next = sorted[i + 1];
              const currPos = positions.get(curr.id)!;
              const nextPos = positions.get(next.id)!;

              const currHeight = curr.collapsed
                ? COLLAPSED_HEIGHT
                : (curr.expandedHeight ?? EXPANDED_HEIGHT);

              expect(nextPos.y).toBe(currPos.y + currHeight + STACK_GAP);
            }

            // First widget starts at y = STACK_GAP (top padding)
            if (sorted.length > 0) {
              const firstPos = positions.get(sorted[0].id)!;
              expect(firstPos.y).toBe(STACK_GAP);
            }
          }
        ),
        { numRuns: 200, verbose: true }
      );
    });

    it('is a pure function — identical inputs always produce identical outputs', () => {
      // **Validates: Requirements 5.2, 5.4**
      fc.assert(
        fc.property(
          arbWidgetList(),
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgets, edge, containerWidth) => {
            const result1 = computeStackPositions(widgets, edge, containerWidth);
            const result2 = computeStackPositions(widgets, edge, containerWidth);

            // Convert Maps to comparable objects
            const obj1 = Object.fromEntries(result1);
            const obj2 = Object.fromEntries(result2);
            expect(obj1).toEqual(obj2);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('assigns correct x position based on edge', () => {
      // **Validates: Requirements 5.2, 5.4**
      fc.assert(
        fc.property(
          arbWidgetList(),
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgets, edge, containerWidth) => {
            const positions = computeStackPositions(widgets, edge, containerWidth);
            const expectedX = edge === 'left' ? STACK_GAP : Math.max(0, containerWidth - WIDGET_WIDTH - STACK_GAP);

            for (const [, pos] of positions) {
              expect(pos.x).toBe(expectedX);
            }
          }
        ),
        { numRuns: 100 }
      );
    });

    it('produces no overlapping y-ranges between any two widgets', () => {
      // **Validates: Requirements 5.2, 5.4**
      fc.assert(
        fc.property(
          arbWidgetList(),
          fc.constantFrom('left' as const, 'right' as const),
          fc.integer({ min: WIDGET_WIDTH, max: 5000 }),
          (widgets, edge, containerWidth) => {
            const positions = computeStackPositions(widgets, edge, containerWidth);

            // Build y-ranges for each widget
            const ranges = widgets.map((w) => {
              const pos = positions.get(w.id)!;
              const height = w.collapsed
                ? COLLAPSED_HEIGHT
                : (w.expandedHeight ?? EXPANDED_HEIGHT);
              return { id: w.id, top: pos.y, bottom: pos.y + height };
            });

            // No two widgets should overlap in y
            for (let i = 0; i < ranges.length; i++) {
              for (let j = i + 1; j < ranges.length; j++) {
                const a = ranges[i];
                const b = ranges[j];
                // Overlap exists if a.top < b.bottom AND b.top < a.bottom
                const overlaps = a.top < b.bottom && b.top < a.bottom;
                expect(overlaps).toBe(false);
              }
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });

});
