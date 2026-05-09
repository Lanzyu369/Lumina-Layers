import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../i18n/context";
import { useExtractorStore } from "../stores/extractorStore";
import Button from "./ui/Button";

export interface ColorcheckerConfirmDialogProps {
  phase: "calibrating" | "confirming" | "done" | null;
  imageFile: File | null;
  originalPreviewUrl: string | null;
  calibratedPreviewUrl: string | null;
  receiveCalibrated: (dataUrl: string) => void;
  confirmCalibrated: () => void;
  rejectCalibrated: () => void;
  closeDialog: () => void;
}

/**
 * Full-screen dialog that embeds the standalone ColorChecker calibration
 * tool inside an iframe.  When calibration finishes the bridge script
 * sends a ``postMessage`` with the calibrated data URL.  The dialog then
 * switches to a side-by-side comparison view so the user can accept or
 * reject the result before it is applied to the extraction flow.
 *
 * Can be driven by any store — pass the relevant state/actions as props.
 * The default export ``ColorcheckerConfirmDialogExtractor`` wires it to
 * ``extractorStore`` for backward compatibility.
 */
export function ColorcheckerConfirmDialogInner({
  phase,
  imageFile,
  originalPreviewUrl,
  calibratedPreviewUrl,
  receiveCalibrated,
  confirmCalibrated,
  rejectCalibrated,
  closeDialog,
}: ColorcheckerConfirmDialogProps) {
  const { t } = useI18n();

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const sentImage = useRef(false);
  const iframeLoaded = useRef(false);

  const isCalibrating = phase === "calibrating";
  const isConfirming = phase === "confirming";
  const open = isCalibrating || isConfirming;

  // --- Slider state for before/after comparison ---
  const [sliderPos, setSliderPos] = useState(50);
  const compareRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const handlePointerMove = useCallback((e: PointerEvent) => {
    if (!dragging.current || !compareRef.current) return;
    const rect = compareRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    setSliderPos((x / rect.width) * 100);
  }, []);

  const handlePointerUp = useCallback(() => {
    dragging.current = false;
    window.removeEventListener("pointermove", handlePointerMove);
    window.removeEventListener("pointerup", handlePointerUp);
  }, [handlePointerMove]);

  const handlePointerDown = useCallback(() => {
    dragging.current = true;
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  }, [handlePointerMove, handlePointerUp]);

  // --- PostMessage listener ---
  const handleMessage = useCallback(
    (e: MessageEvent) => {
      if (e.data?.type === "colorchecker-calibrated" && e.data.calibratedImageData) {
        receiveCalibrated(e.data.calibratedImageData as string);
      }
    },
    [receiveCalibrated],
  );

  useEffect(() => {
    if (!open) return;
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [open, handleMessage]);

  // --- Send image to iframe ---
  const sendImageToIframe = useCallback(() => {
    if (!imageFile || !iframeRef.current?.contentWindow || sentImage.current || !iframeLoaded.current) return;
    sentImage.current = true;
    setTimeout(() => {
      iframeRef.current?.contentWindow?.postMessage(
        { type: "colorchecker-load-image", blob: imageFile, fileName: imageFile.name },
        "*",
      );
    }, 600);
  }, [imageFile]);

  const handleIframeLoad = useCallback(() => {
    iframeLoaded.current = true;
    sendImageToIframe();
  }, [sendImageToIframe]);

  useEffect(() => {
    if (isCalibrating && imageFile) sendImageToIframe();
  }, [isCalibrating, imageFile, sendImageToIframe]);

  useEffect(() => {
    if (isCalibrating) {
      sentImage.current = false;
      iframeLoaded.current = false;
    }
  }, [isCalibrating]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
    >
      <div
        className="relative mx-4 flex h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-2 dark:border-slate-700">
          <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
            {isConfirming ? t("ext_cc_confirm_title") : t("ext_cc_dialog_title")}
          </h2>
          <button
            type="button"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            onClick={closeDialog}
          >
            ✕
          </button>
        </div>

        {/* Body: iframe (calibrating) or comparison (confirming) */}
        {isCalibrating && (
          <iframe
            ref={iframeRef}
            src="/api/colorchecker-ui"
            title={t("ext_cc_dialog_title")}
            className="flex-1 w-full border-0"
            onLoad={handleIframeLoad}
          />
        )}

        {isConfirming && (
          <div className="flex flex-1 flex-col overflow-hidden">
            {/* Before / After slider comparison */}
            <div
              ref={compareRef}
              className="relative flex-1 min-h-0 cursor-col-resize select-none overflow-hidden"
              onPointerDown={handlePointerDown}
            >
              {/* Original (full width, below) */}
              {originalPreviewUrl && (
                <img
                  src={originalPreviewUrl}
                  alt={t("ext_cc_compare_original")}
                  className="absolute inset-0 h-full w-full object-contain"
                  draggable={false}
                />
              )}
              {/* Calibrated (clipped to slider position, above) */}
              {calibratedPreviewUrl && (
                <div
                  className="absolute inset-0 overflow-hidden"
                  style={{ clipPath: `inset(0 ${100 - sliderPos}% 0 0)` }}
                >
                  <img
                    src={calibratedPreviewUrl}
                    alt={t("ext_cc_compare_calibrated")}
                    className="absolute inset-0 h-full w-full object-contain"
                    draggable={false}
                  />
                </div>
              )}
              {/* Slider line */}
              <div
                className="absolute top-0 bottom-0 z-10 w-0.5 shadow-lg"
                style={{ left: `${sliderPos}%`, transform: "translateX(-50%)", background: "var(--surface-overlay)" }}
              >
                <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full px-1.5 py-0.5 text-[10px] font-bold text-slate-700 shadow" style={{ background: "var(--surface-panel)" }}>
                  ◀ ▶
                </div>
              </div>
              {/* Labels */}
              <span className="absolute left-3 top-3 z-10 rounded bg-black/50 px-2 py-0.5 text-xs font-medium text-white">
                {t("ext_cc_compare_calibrated")}
              </span>
              <span className="absolute right-3 top-3 z-10 rounded bg-black/50 px-2 py-0.5 text-xs font-medium text-white">
                {t("ext_cc_compare_original")}
              </span>
            </div>

            {/* Action buttons */}
            <div className="flex items-center justify-center gap-4 border-t border-slate-200 px-5 py-3 dark:border-slate-700">
              <Button
                label={t("ext_cc_confirm_accept")}
                variant="primary"
                onClick={confirmCalibrated}
              />
              <Button
                label={t("ext_cc_confirm_reject")}
                variant="secondary"
                onClick={rejectCalibrated}
              />
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** Default export wired to ``extractorStore`` for the legacy extractor panel. */
export default function ColorcheckerConfirmDialogExtractor() {
  const phase = useExtractorStore((s) => s.colorchecker_phase);
  const imageFile = useExtractorStore((s) => s.imageFile);
  const originalPreviewUrl = useExtractorStore((s) => s.originalPreviewUrl);
  const calibratedPreviewUrl = useExtractorStore((s) => s.calibratedPreviewUrl);
  const receiveCalibrated = useExtractorStore((s) => s.receiveCalibratedFromCC);
  const confirmCalibrated = useExtractorStore((s) => s.confirmCalibrated);
  const rejectCalibrated = useExtractorStore((s) => s.rejectCalibrated);
  const closeDialog = useExtractorStore((s) => s.closeColorcheckerDialog);

  return (
    <ColorcheckerConfirmDialogInner
      phase={phase}
      imageFile={imageFile}
      originalPreviewUrl={originalPreviewUrl}
      calibratedPreviewUrl={calibratedPreviewUrl}
      receiveCalibrated={receiveCalibrated}
      confirmCalibrated={confirmCalibrated}
      rejectCalibrated={rejectCalibrated}
      closeDialog={closeDialog}
    />
  );
}
