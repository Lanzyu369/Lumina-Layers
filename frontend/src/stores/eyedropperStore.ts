/**
 * Eyedropper hand-off between the 2D preview and the quick-recolor card.
 * 2D 预览与快速换色卡片之间的吸管取色交接。
 *
 * While active, the next click on the 2D preview reads that pixel's color
 * instead of changing the selection. Kept separate from the converter store
 * so the preview and the card only share this one small contract.
 * 启用时，2D 预览上的下一次点击只读取该点颜色，不改变选区。独立于转换器
 * store，预览与卡片之间只共享这一个小约定。
 */

import { create } from "zustand";

export interface EyedropperPick {
  /** Picked color as ``#rrggbb``. */
  hex: string;
  /** Increments on every pick so picking the same color twice still notifies. */
  seq: number;
}

interface EyedropperState {
  active: boolean;
  lastPick: EyedropperPick | null;
  start: () => void;
  cancel: () => void;
  /** Record a picked color and leave eyedropper mode. */
  complete: (hex: string) => void;
}

export const useEyedropperStore = create<EyedropperState>()((set) => ({
  active: false,
  lastPick: null,
  start: () => set({ active: true }),
  cancel: () => set({ active: false }),
  complete: (hex: string) =>
    set((state) => ({
      active: false,
      lastPick: {
        hex: `#${hex.replace(/^#/, "").toLowerCase()}`,
        seq: (state.lastPick?.seq ?? 0) + 1,
      },
    })),
}));
