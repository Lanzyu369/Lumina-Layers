import { useEffect, useMemo, useRef, useState } from "react";
import { useConverterStore } from "../stores/converter";

const PUZZLE_PREVIEW_DEBOUNCE_MS = 250;
const MAX_PUZZLE_PREVIEW_RETRIES = 1;

/**
 * Auto-refresh the puzzle layout overlay without rerunning the main preview.
 * 自动刷新拼图叠线预览，而不重跑整图预览。
 */
export function usePuzzleLayoutPreview(): void {
  const puzzleEnabled = useConverterStore((s) => s.puzzleEnabled ?? false);
  const sessionId = useConverterStore((s) => s.sessionId);
  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl);
  const previewBaseImageUrl = useConverterStore((s) => s.previewBaseImageUrl);
  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth);
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight);
  const targetHeightMm = useConverterStore((s) => s.target_height_mm);
  const puzzleStyle = useConverterStore((s) => s.puzzleStyle ?? "regular");
  const puzzleSizingMode = useConverterStore((s) => s.puzzleSizingMode ?? "piece_size");
  const pieceWidthMm = useConverterStore((s) => s.pieceWidthMm ?? 20);
  const pieceHeightMm = useConverterStore((s) => s.pieceHeightMm ?? 20);
  const puzzleRows = useConverterStore((s) => s.puzzleRows ?? 3);
  const puzzleCols = useConverterStore((s) => s.puzzleCols ?? 3);
  const targetPieceCount = useConverterStore((s) => s.targetPieceCount ?? 12);
  const connectorStyle = useConverterStore((s) => s.connectorStyle ?? "classic");
  const labelsEnabled = useConverterStore((s) => s.labelsEnabled ?? false);
  const engraveBackLabels = useConverterStore((s) => s.engraveBackLabels ?? false);
  const irregularityStrength = useConverterStore((s) => s.irregularityStrength ?? 0.35);
  const minNeckWidthMm = useConverterStore((s) => s.minNeckWidthMm ?? 1.2);
  const submitPuzzleLayoutPreview = useConverterStore(
    (s) => s.submitPuzzleLayoutPreview,
  );
  const clearPuzzleLayoutPreview = useConverterStore(
    (s) => s.clearPuzzleLayoutPreview,
  );

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentRequestKeyRef = useRef<string>("");
  const lastAppliedKeyRef = useRef<string>("");
  const inFlightKeyRef = useRef<string | null>(null);
  const retryCountRef = useRef<number>(0);
  const [retryNonce, setRetryNonce] = useState(0);

  const requestKey = useMemo(
    () =>
      JSON.stringify({
        sessionId,
        previewGlbUrl,
        previewImageUrl,
        previewBaseImageUrl,
        previewPixelWidth,
        previewPixelHeight,
        targetHeightMm,
        puzzleStyle,
        puzzleSizingMode,
        pieceWidthMm,
        pieceHeightMm,
        puzzleRows,
        puzzleCols,
        targetPieceCount,
        connectorStyle,
        labelsEnabled,
        engraveBackLabels,
        irregularityStrength,
        minNeckWidthMm,
      }),
    [
      sessionId,
      previewGlbUrl,
      previewImageUrl,
      previewBaseImageUrl,
      previewPixelWidth,
      previewPixelHeight,
      targetHeightMm,
      puzzleStyle,
      puzzleSizingMode,
      pieceWidthMm,
      pieceHeightMm,
      puzzleRows,
      puzzleCols,
      targetPieceCount,
      connectorStyle,
      labelsEnabled,
      engraveBackLabels,
      irregularityStrength,
      minNeckWidthMm,
    ],
  );

  useEffect(() => {
    const previousRequestKey = currentRequestKeyRef.current;
    currentRequestKeyRef.current = requestKey;
    retryCountRef.current = 0;
    inFlightKeyRef.current = null;
    if (
      previousRequestKey
      && previousRequestKey !== requestKey
      && typeof clearPuzzleLayoutPreview === "function"
    ) {
      lastAppliedKeyRef.current = "";
      clearPuzzleLayoutPreview();
    }
  }, [clearPuzzleLayoutPreview, requestKey]);

  useEffect(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (
      !puzzleEnabled ||
      !sessionId ||
      typeof clearPuzzleLayoutPreview !== "function" ||
      typeof submitPuzzleLayoutPreview !== "function"
    ) {
      currentRequestKeyRef.current = "";
      lastAppliedKeyRef.current = "";
      inFlightKeyRef.current = null;
      retryCountRef.current = 0;
      if (typeof clearPuzzleLayoutPreview === "function") {
        clearPuzzleLayoutPreview();
      }
      return;
    }

    if (
      lastAppliedKeyRef.current === requestKey
      || inFlightKeyRef.current === requestKey
    ) {
      return;
    }

    timerRef.current = setTimeout(() => {
      inFlightKeyRef.current = requestKey;
      void submitPuzzleLayoutPreview().then((applied) => {
        if (currentRequestKeyRef.current !== requestKey) {
          if (inFlightKeyRef.current === requestKey) {
            inFlightKeyRef.current = null;
          }
          return;
        }

        if (inFlightKeyRef.current === requestKey) {
          inFlightKeyRef.current = null;
        }

        if (applied) {
          lastAppliedKeyRef.current = requestKey;
          retryCountRef.current = 0;
          return;
        }

        lastAppliedKeyRef.current = "";
        if (retryCountRef.current < MAX_PUZZLE_PREVIEW_RETRIES) {
          retryCountRef.current += 1;
          setRetryNonce((value) => value + 1);
          return;
        }
        retryCountRef.current = 0;
      });
    }, PUZZLE_PREVIEW_DEBOUNCE_MS);

    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [
    clearPuzzleLayoutPreview,
    puzzleEnabled,
    requestKey,
    retryNonce,
    sessionId,
    submitPuzzleLayoutPreview,
  ]);
}
