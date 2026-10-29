import { describe, expect, it, vi } from 'vitest';
import type { SelectionDocument, SelectionMutationInput } from '../../stores/converter/types';
import { buildSelectionVisualDraft } from './selectionVisualDraft';

const RED = [255, 0, 0];
const BLUE = [0, 0, 255];

function buffer(rows: number[][][]) {
  const height = rows.length;
  const width = rows[0].length;
  const data = new Uint8ClampedArray(rows.flatMap((row) => row.flatMap(([r, g, b, a = 255]) => [r, g, b, a])));
  const getImageData = vi.fn(() => ({ data, width, height } as ImageData));
  return { width, height, context: { getImageData } as unknown as CanvasRenderingContext2D, getImageData };
}

function rectangle(left: number, top: number, right: number, bottom: number, height: number): number[][] {
  return [[left, height - top], [right, height - top], [right, height - bottom], [left, height - bottom]];
}

function document(contours: number[][][] = [], count = 0): SelectionDocument {
  return {
    selection_revision: 12, content_revision: 3,
    selected_pixel_count: count, selected_component_count: count ? 1 : 0,
    selected_color_hexes: count ? ['#ff0000'] : [],
    region_ids: count ? ['confirmed-selection'] : [], components: [], contours,
    can_undo: true, can_redo: true,
  };
}

function bounds(polygons: number[][][]) {
  return polygons.map((polygon) => [
    Math.min(...polygon.map(([x]) => x)), Math.min(...polygon.map(([, y]) => y)),
    Math.max(...polygon.map(([x]) => x)), Math.max(...polygon.map(([, y]) => y)),
  ]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
}

const point = (x: number, y = 0): SelectionMutationInput => ({ operation: 'point-toggle', x, y });

describe('selection visual draft', () => {
  it('shows adjacent new blocks immediately and lets confirmation supply their union', () => {
    const previewBuffer = buffer([[RED, BLUE]]);
    const confirmed = document();
    const snapshot = structuredClone(confirmed);
    const mutations = [point(0), point(1)];
    const result = buildSelectionVisualDraft({ document: confirmed, mutations, previewBuffer, previewWidthMm: 2 });

    expect(result).toHaveLength(2);
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[0, 0, 1, 1], [1, 0, 2, 1]]);
    expect(confirmed).toEqual(snapshot);
    expect(mutations).toEqual([point(0), point(1)]);
    expect(buildSelectionVisualDraft({ document: document([rectangle(0, 0, 2, 1, 1)], 2), mutations: [], previewBuffer, previewWidthMm: 2 }))
      .toBeNull();
  });

  it('keeps the next pending block visible when the first block is confirmed', () => {
    const previewBuffer = buffer([[RED, BLUE]]);
    const result = buildSelectionVisualDraft({
      document: document([rectangle(0, 0, 1, 1, 1)], 1), mutations: [point(1)],
      previewBuffer, previewWidthMm: 2,
    });
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[0, 0, 1, 1], [1, 0, 2, 1]]);
  });

  it('replays A, B, A as only B and repeated A clicks as empty without editing revisions', () => {
    const previewBuffer = buffer([[RED, BLUE]]);
    const confirmed = document();
    expect(buildSelectionVisualDraft({ document: confirmed, mutations: [point(0), point(0)], previewBuffer, previewWidthMm: 2 }))
      .toEqual([]);
    const result = buildSelectionVisualDraft({
      document: confirmed, mutations: [point(0), point(1), point(0)], previewBuffer, previewWidthMm: 2,
    });
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[1, 0, 2, 1]]);
    expect(confirmed.selection_revision).toBe(12);
    expect(confirmed.can_redo).toBe(true);
  });

  it('removes one block from a confirmed union and exposes its neighbor boundary', () => {
    const previewBuffer = buffer([[RED, BLUE]]);
    const result = buildSelectionVisualDraft({
      document: document([rectangle(0, 0, 2, 1, 1)], 2),
      mutations: [{ operation: 'point-remove', x: 0, y: 0 }], previewBuffer, previewWidthMm: 2,
    });
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[1, 0, 2, 1]]);
  });

  it('fills a partially selected component before a later toggle removes it', () => {
    const previewBuffer = buffer([[RED, RED, RED]]);
    const confirmed = document([rectangle(0, 0, 1, 1, 1)], 1);
    const added = buildSelectionVisualDraft({ document: confirmed, mutations: [point(0)], previewBuffer, previewWidthMm: 3 });
    expect(bounds(added!.flatMap((target) => target.polygons))).toContainEqual([0, 0, 3, 1]);
    expect(buildSelectionVisualDraft({ document: confirmed, mutations: [point(0), point(0)], previewBuffer, previewWidthMm: 3 }))
      .toEqual([]);
  });

  it('preserves holes while restoring the confirmed display mask', () => {
    const previewBuffer = buffer([
      [RED, RED, RED, RED, RED],
      [RED, BLUE, BLUE, BLUE, RED],
      [RED, BLUE, BLUE, BLUE, RED],
      [RED, BLUE, BLUE, BLUE, RED],
      [RED, RED, RED, RED, RED],
    ]);
    // Same loop orientation deliberately requires even-odd filling.
    const confirmed = document([rectangle(0, 0, 5, 5, 5), rectangle(1, 1, 4, 4, 5)], 16);
    const filled = buildSelectionVisualDraft({ document: confirmed, mutations: [point(2, 2)], previewBuffer, previewWidthMm: 5 });
    expect(filled).not.toEqual([]);
    const removedRing = buildSelectionVisualDraft({
      document: confirmed, mutations: [{ operation: 'point-remove', x: 0, y: 0 }], previewBuffer, previewWidthMm: 5,
    });
    expect(removedRing).toEqual([]);
    const restoredHole = buildSelectionVisualDraft({
      document: confirmed, mutations: [point(2, 2), point(2, 2)], previewBuffer, previewWidthMm: 5,
    });
    expect(bounds(restoredHole!.flatMap((target) => target.polygons))).toEqual([[0, 0, 5, 5], [1, 1, 4, 4]]);
  });

  it('same-color toggle completes all islands, then removes them together', () => {
    const previewBuffer = buffer([[RED, BLUE, RED]]);
    const confirmed = document([rectangle(0, 0, 1, 1, 1)], 1);
    const toggle: SelectionMutationInput = { operation: 'same-color-toggle', colorHex: '#FF0000' };
    const result = buildSelectionVisualDraft({ document: confirmed, mutations: [toggle], previewBuffer, previewWidthMm: 3 });
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[0, 0, 1, 1], [2, 0, 3, 1]]);
    expect(buildSelectionVisualDraft({ document: confirmed, mutations: [toggle, toggle], previewBuffer, previewWidthMm: 3 }))
      .toEqual([]);
  });

  it('color-set replaces the previous mask and repeated removal stays empty', () => {
    const previewBuffer = buffer([[RED, BLUE, RED]]);
    const confirmed = document([rectangle(1, 0, 2, 1, 1)], 1);
    const replace: SelectionMutationInput = { operation: 'colors-set', colorHexes: ['ff0000'] };
    const remove: SelectionMutationInput = { operation: 'same-color-remove', colorHex: 'ff0000' };
    const result = buildSelectionVisualDraft({ document: confirmed, mutations: [replace], previewBuffer, previewWidthMm: 3 });
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[0, 0, 1, 1], [2, 0, 3, 1]]);
    expect(buildSelectionVisualDraft({ document: confirmed, mutations: [replace, remove, remove], previewBuffer, previewWidthMm: 3 }))
      .toEqual([]);
  });

  it('clear supersedes pending geometry even without a ready preview buffer', () => {
    expect(buildSelectionVisualDraft({
      document: document(), mutations: [point(0), { operation: 'brush-add' }, { operation: 'clear' }],
      previewBuffer: null, previewWidthMm: 1,
    })).toEqual([]);
  });

  it.each<SelectionMutationInput>([
    { operation: 'brush-add' },
    { operation: 'color-range-toggle', x: 0, y: 0, colorTolerance: 6 },
  ])('keeps a pending clear visible before $operation can be resolved', (unsupported) => {
    expect(buildSelectionVisualDraft({
      document: document([rectangle(0, 0, 1, 1, 1)], 1),
      mutations: [{ operation: 'clear' }, unsupported], previewBuffer: null, previewWidthMm: 1,
    })).toEqual([]);
  });

  it('keeps the predictable point selection before an unsupported gesture', () => {
    const previewBuffer = buffer([[RED, BLUE]]);
    const result = buildSelectionVisualDraft({
      document: document(),
      mutations: [point(0), { operation: 'color-range-toggle', x: 1, y: 0, colorTolerance: 6 }, point(1)],
      previewBuffer, previewWidthMm: 2,
    });
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[0, 0, 1, 1]]);
  });

  it('keeps a clear visible when the next point cannot read a preview buffer', () => {
    const confirmed = document([rectangle(0, 0, 1, 1, 1)], 1);
    const mutations: SelectionMutationInput[] = [{ operation: 'clear' }, point(0)];
    expect(buildSelectionVisualDraft({ document: confirmed, mutations, previewBuffer: null, previewWidthMm: 1 }))
      .toEqual([]);
    const unreadable = buffer([[RED]]);
    unreadable.getImageData.mockImplementation(() => { throw new Error('unavailable pixels'); });
    expect(buildSelectionVisualDraft({ document: confirmed, mutations, previewBuffer: unreadable, previewWidthMm: 1 }))
      .toEqual([]);
  });

  it.each([1, 4])('keeps A when the next point at x=%i is transparent or outside the image', (x) => {
    const previewBuffer = buffer([[RED, [0, 0, 0, 0]]]);
    const result = buildSelectionVisualDraft({
      document: document(), mutations: [point(0), point(x)], previewBuffer, previewWidthMm: 2,
    });
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[0, 0, 1, 1]]);
    expect(buildSelectionVisualDraft({ document: document(), mutations: [point(x)], previewBuffer, previewWidthMm: 2 }))
      .toBeNull();
  });

  it('treats color-set without its color list as unknown instead of clearing the draft', () => {
    const previewBuffer = buffer([[RED]]);
    const incomplete: SelectionMutationInput = { operation: 'colors-set' };
    const result = buildSelectionVisualDraft({
      document: document(), mutations: [point(0), incomplete], previewBuffer, previewWidthMm: 1,
    });
    expect(bounds(result!.flatMap((target) => target.polygons))).toEqual([[0, 0, 1, 1]]);
    expect(buildSelectionVisualDraft({
      document: document([rectangle(0, 0, 1, 1, 1)], 1), mutations: [incomplete], previewBuffer, previewWidthMm: 1,
    })).toBeNull();
    expect(buildSelectionVisualDraft({
      document: document(), mutations: [{ operation: 'clear' }, incomplete], previewBuffer, previewWidthMm: 1,
    })).toEqual([]);
  });

  it('falls back to the confirmed document for unavailable pixels or unsupported operations', () => {
    const previewBuffer = buffer([[RED]]);
    expect(buildSelectionVisualDraft({
      document: document(), mutations: [{ operation: 'color-range-toggle', x: 0, y: 0, colorTolerance: 6 }, point(0)],
      previewBuffer, previewWidthMm: 1,
    })).toBeNull();
    expect(previewBuffer.getImageData).not.toHaveBeenCalled();
    expect(buildSelectionVisualDraft({ document: document(), mutations: [point(0)], previewBuffer: null, previewWidthMm: 1 }))
      .toBeNull();
    const transparent = buffer([[[0, 0, 0, 0]]]);
    expect(buildSelectionVisualDraft({ document: document(), mutations: [point(0)], previewBuffer: transparent, previewWidthMm: 1 }))
      .toBeNull();
  });

  it('reads preview pixels once across successive clicks and keeps another buffer independent', () => {
    const previewBuffer = buffer([[RED, BLUE, RED]]);
    const confirmed = document();
    for (const mutations of [[point(0)], [point(0), point(1)], [point(0), point(1), point(0)]]) {
      buildSelectionVisualDraft({ document: confirmed, mutations, previewBuffer, previewWidthMm: 3 });
    }
    expect(previewBuffer.getImageData).toHaveBeenCalledTimes(1);
    const changedBuffer = buffer([[BLUE, RED, BLUE]]);
    const changed = buildSelectionVisualDraft({ document: confirmed, mutations: [point(0)], previewBuffer: changedBuffer, previewWidthMm: 3 });
    expect(changed?.[0].hex).toBe('0000ff');
    expect(changedBuffer.getImageData).toHaveBeenCalledTimes(1);
  });

  it('uses physical contour coordinates and rescales cached local outlines', () => {
    const previewBuffer = buffer([[RED, BLUE]]);
    buildSelectionVisualDraft({ document: document(), mutations: [point(0)], previewBuffer, previewWidthMm: 2 });
    const enlarged = buildSelectionVisualDraft({
      document: document(), mutations: [point(0)], previewBuffer, previewWidthMm: 200,
    });
    expect(bounds(enlarged!.flatMap((target) => target.polygons))).toEqual([[0, 0, 100, 100]]);
    const removed = buildSelectionVisualDraft({
      document: document([rectangle(0, 0, 200, 100, 100)], 2),
      mutations: [{ operation: 'point-remove', x: 0, y: 0 }], previewBuffer, previewWidthMm: 200,
    });
    expect(bounds(removed!.flatMap((target) => target.polygons))).toEqual([[100, 0, 200, 100]]);
    expect(previewBuffer.getImageData).toHaveBeenCalledTimes(1);
  });
});
