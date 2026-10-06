/**
 * Color2DOverlay — color editing overlay above the 3D scene.
 * Color2DOverlay — 覆盖在 3D 场景上方的颜色编辑面板。
 *
 * Shows PalettePanel (top) + LUT Color Grid (bottom) for color
 * replacement. The user selects colors by clicking on the 3D model
 * in the scene underneath, then uses this panel to pick target colors.
 * 显示调色板（上）+ LUT 颜色网格（下）用于颜色替换。
 * 用户在下方 3D 场景中点击模型选色，然后在此面板中选择目标色。
 */

import { useEffect, useCallback, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { useWidgetStore } from '../../stores/widgetStore';
import { useConverterStore } from '../../stores/converter';
import ColorPreview2D from '../sections/ColorPreview2D';
import PalettePanel from '../sections/PalettePanel';
import LutColorGrid from '../sections/LutColorGrid';
import ColorQuickReplacePanel from '../colorQuickReplace/ColorQuickReplacePanel';

export default function Color2DOverlay() {
  const closeOverlay = useWidgetStore((s) => s.closeColor2DOverlay);

  const imageFile = useConverterStore((s) => s.imageFile);
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl);
  const isLoading = useConverterStore((s) => s.isLoading);
  const hasManualPreview = useConverterStore((s) => s.hasManualPreview);
  const autoRefreshPending = useConverterStore(
    (s) => s.previewAutoRefreshPending,
  );
  const submitPreview = useConverterStore((s) => s.submitPreview);
  const [showHoverMagnifier, setShowHoverMagnifier] = useState(true);
  const [showHoverLayerDetails, setShowHoverLayerDetails] = useState(true);

  const [contentReady, setContentReady] = useState(false);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setContentReady(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  // Auto-trigger preview when overlay opens with an image but no preview
  const didAutoPreview = useRef(false);
  useEffect(() => {
    if (
      contentReady &&
      imageFile &&
      !previewImageUrl &&
      !isLoading &&
      !hasManualPreview &&
      !autoRefreshPending &&
      !didAutoPreview.current
    ) {
      didAutoPreview.current = true;
      void submitPreview();
    }
  }, [
    autoRefreshPending,
    contentReady,
    hasManualPreview,
    imageFile,
    previewImageUrl,
    isLoading,
    submitPreview,
  ]);

  // ESC key to close (return to 3D view)
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeOverlay();
      }
    },
    [closeOverlay],
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      data-testid="color-2d-overlay"
      className="absolute inset-0 z-[45] flex flex-col bg-slate-50/95 dark:bg-slate-950/95 backdrop-blur-sm"
    >
      {/* Content: left = 2D preview, right = palette + LUT grid in two columns */}
      {contentReady && (
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(18rem,0.82fr)_minmax(17rem,0.46fr)_minmax(20rem,0.72fr)] gap-0">
        {/* Left: 2D preview image (click to select color/region) */}
        <div className="min-h-0 border-r border-slate-200/60 px-2 py-3 dark:border-slate-800/60">
          <ColorPreview2D
            showMagnifier={showHoverMagnifier}
            showLayerDetails={showHoverLayerDetails}
          />
        </div>

        {/* Middle: palette panel */}
        <div className="min-h-0 border-r border-slate-200/60 px-3 py-2 dark:border-slate-800/60">
          <div className="h-full overflow-y-auto">
            <PalettePanel
              showHoverMagnifier={showHoverMagnifier}
              showHoverLayerDetails={showHoverLayerDetails}
              onToggleHoverMagnifier={setShowHoverMagnifier}
              onToggleHoverLayerDetails={setShowHoverLayerDetails}
            />
          </div>
        </div>

        {/* Right: quick recolor card + LUT color grid */}
        <div className="flex min-h-0 flex-col gap-2 px-3 py-2">
          <ColorQuickReplacePanel />
          <div className="min-h-0 flex-1 overflow-y-auto">
            <LutColorGrid />
          </div>
        </div>
      </div>
      )}
    </motion.div>
  );
}
