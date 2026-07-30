import { useState } from "react";

import Button from "../../../components/ui/Button";
import {
  PanelIntro,
  StatusBanner,
  cx,
  resolveSectionCardClass,
  workstationFieldLabelClass,
  workstationInputClass,
} from "../../../components/ui/panelPrimitives";
import type { WorkshopRaster } from "../../types";
import { BeadSourceCanvas, type CalibrationPickMode } from "./BeadSourceCanvas";
import {
  MAX_BEAD_GRID_SIZE,
  type BeadEmptySelection,
  type BeadGridGeometry,
  type BeadInputMode,
  type BeadOrientation,
  type PatternClassification,
} from "./types";

export interface BeadCalibrationDraft {
  inputMode: BeadInputMode;
  rows: number;
  columns: number;
  geometry: BeadGridGeometry;
  orientation: BeadOrientation;
  emptySelection: BeadEmptySelection | null;
  transparentSupportSampleCellIndex: number | null;
}

interface BeadCalibrationStepProps {
  source: WorkshopRaster;
  fileName: string;
  classification: PatternClassification | null;
  draft: BeadCalibrationDraft;
  busy: boolean;
  translate(key: string): string;
  onChange(next: BeadCalibrationDraft): void;
  onRecognize(): void;
  onOpenCrop(): void;
  canCrop: boolean;
}

function interpolate(
  template: string,
  values: Record<string, string | number>,
): string {
  return Object.entries(values).reduce(
    (result, [key, value]) =>
      result.replace(`{${key}}`, String(value)),
    template,
  );
}

function clampDimension(value: number): number {
  return Math.min(
    MAX_BEAD_GRID_SIZE,
    Math.max(1, Math.round(value)),
  );
}

function isValidBeadCalibrationGrid(
  draft: BeadCalibrationDraft,
): boolean {
  const { geometry } = draft;
  if (
    !Number.isFinite(geometry.originX) ||
    !Number.isFinite(geometry.originY) ||
    !Number.isFinite(geometry.cellWidth) ||
    !Number.isFinite(geometry.cellHeight) ||
    geometry.originX < 0 ||
    geometry.originY < 0 ||
    geometry.cellWidth <= 0 ||
    geometry.cellHeight <= 0
  ) {
    return false;
  }
  const squareError =
    Math.abs(geometry.cellWidth - geometry.cellHeight) /
    Math.max(geometry.cellWidth, geometry.cellHeight);
  return squareError <= 0.12;
}

function segmentClass(active: boolean): string {
  return cx(
    "min-h-10 rounded-xl px-3 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)]",
    active
      ? "bg-blue-600 text-white shadow-[var(--shadow-control)]"
      : "border border-slate-200/80 bg-white/70 text-slate-600 hover:bg-white dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-900",
  );
}

export function BeadCalibrationStep({
  source,
  fileName,
  classification,
  draft,
  busy,
  translate: t,
  onChange,
  onRecognize,
  onOpenCrop,
  canCrop,
}: BeadCalibrationStepProps) {
  const [pickMode, setPickMode] =
    useState<CalibrationPickMode>("none");
  const validGrid = isValidBeadCalibrationGrid(draft);
  const hasEmptyDecision = draft.emptySelection !== null;
  const canRecognize = validGrid && hasEmptyDecision && !busy;

  const updateDimensions = (
    rows: number,
    columns: number,
  ) => {
    const safeRows = clampDimension(rows);
    const safeColumns = clampDimension(columns);
    onChange({
      ...draft,
      rows: safeRows,
      columns: safeColumns,
      geometry: {
        ...draft.geometry,
        cellWidth:
          (source.width - draft.geometry.originX) / safeColumns,
        cellHeight:
          (source.height - draft.geometry.originY) / safeRows,
      },
      emptySelection: null,
      transparentSupportSampleCellIndex: null,
    });
  };

  const updateOrigin = (axis: "x" | "y", value: number) => {
    const maximum = axis === "x" ? source.width - 1 : source.height - 1;
    const safeValue = Math.min(
      maximum,
      Math.max(0, Number.isFinite(value) ? value : 0),
    );
    const originX =
      axis === "x" ? safeValue : draft.geometry.originX;
    const originY =
      axis === "y" ? safeValue : draft.geometry.originY;
    onChange({
      ...draft,
      geometry: {
        originX,
        originY,
        cellWidth: (source.width - originX) / draft.columns,
        cellHeight: (source.height - originY) / draft.rows,
      },
      emptySelection: null,
      transparentSupportSampleCellIndex: null,
    });
  };

  const handleCellPick = (cellIndex: number) => {
    if (pickMode === "empty") {
      onChange({
        ...draft,
        emptySelection: { kind: "sample", cellIndex },
      });
    } else if (pickMode === "transparent-support") {
      onChange({
        ...draft,
        transparentSupportSampleCellIndex: cellIndex,
      });
    }
    setPickMode("none");
  };

  const setRotation = (rotation: BeadOrientation["rotation"]) => {
    onChange({
      ...draft,
      orientation: { ...draft.orientation, rotation },
    });
  };

  const classificationText = classification
    ? interpolate(t("workshop.bead.classification"), {
        mode: t(`workshop.bead.mode.${classification.mode}`),
        confidence: Math.round(classification.confidence * 100),
      })
    : t("workshop.bead.classifying");

  return (
    <div className="flex flex-col gap-5">
      <PanelIntro
        eyebrow={fileName}
        title={t("workshop.bead.calibrationTitle")}
        description={t("workshop.bead.calibrationDescription")}
        action={
          canCrop ? (
            <Button
              label={t("workshop.bead.cropPattern")}
              variant="secondary"
              onClick={onOpenCrop}
            />
          ) : undefined
        }
      />

      <div className="grid min-h-0 gap-5 xl:grid-cols-[minmax(19rem,24rem)_minmax(0,1fr)]">
        <section
          className={cx(
            resolveSectionCardClass("standard"),
            "flex flex-col gap-4",
          )}
        >
          <StatusBanner tone="info">
            {classificationText}
          </StatusBanner>

          <label className="flex flex-col gap-1.5">
            <span className={workstationFieldLabelClass}>
              {t("workshop.bead.inputMode")}
            </span>
            <select
              className={workstationInputClass}
              value={draft.inputMode}
              onChange={(event) =>
                onChange({
                  ...draft,
                  inputMode: event.target.value as BeadInputMode,
                  emptySelection: null,
                  transparentSupportSampleCellIndex: null,
                })
              }
            >
              {(
                [
                  "numbered-grid",
                  "hard-pixel",
                  "ring-preview",
                ] as const
              ).map((mode) => (
                <option key={mode} value={mode}>
                  {t(`workshop.bead.mode.${mode}`)}
                </option>
              ))}
            </select>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5">
              <span className={workstationFieldLabelClass}>
                {t("workshop.bead.rows")}
              </span>
              <input
                aria-label={t("workshop.bead.rows")}
                className={workstationInputClass}
                type="number"
                min={1}
                max={MAX_BEAD_GRID_SIZE}
                value={draft.rows}
                onChange={(event) =>
                  updateDimensions(
                    Number(event.target.value),
                    draft.columns,
                  )
                }
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={workstationFieldLabelClass}>
                {t("workshop.bead.columns")}
              </span>
              <input
                aria-label={t("workshop.bead.columns")}
                className={workstationInputClass}
                type="number"
                min={1}
                max={MAX_BEAD_GRID_SIZE}
                value={draft.columns}
                onChange={(event) =>
                  updateDimensions(
                    draft.rows,
                    Number(event.target.value),
                  )
                }
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={workstationFieldLabelClass}>
                {t("workshop.bead.originX")}
              </span>
              <input
                aria-label={t("workshop.bead.originX")}
                className={workstationInputClass}
                type="number"
                min={0}
                value={draft.geometry.originX}
                onChange={(event) =>
                  updateOrigin("x", Number(event.target.value))
                }
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={workstationFieldLabelClass}>
                {t("workshop.bead.originY")}
              </span>
              <input
                aria-label={t("workshop.bead.originY")}
                className={workstationInputClass}
                type="number"
                min={0}
                value={draft.geometry.originY}
                onChange={(event) =>
                  updateOrigin("y", Number(event.target.value))
                }
              />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {([0, 90, 180, 270] as const).map((rotation) => (
              <button
                key={rotation}
                type="button"
                aria-pressed={draft.orientation.rotation === rotation}
                onClick={() => setRotation(rotation)}
                className={segmentClass(
                  draft.orientation.rotation === rotation,
                )}
              >
                {t(`workshop.bead.rotate${rotation}`)}
              </button>
            ))}
            <button
              type="button"
              aria-pressed={draft.orientation.flipHorizontal}
              onClick={() =>
                onChange({
                  ...draft,
                  orientation: {
                    ...draft.orientation,
                    flipHorizontal:
                      !draft.orientation.flipHorizontal,
                  },
                })
              }
              className={segmentClass(
                draft.orientation.flipHorizontal,
              )}
            >
              {t("workshop.bead.flipHorizontal")}
            </button>
            <button
              type="button"
              aria-pressed={draft.orientation.flipVertical}
              onClick={() =>
                onChange({
                  ...draft,
                  orientation: {
                    ...draft.orientation,
                    flipVertical: !draft.orientation.flipVertical,
                  },
                })
              }
              className={segmentClass(
                draft.orientation.flipVertical,
              )}
            >
              {t("workshop.bead.flipVertical")}
            </button>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
            <button
              type="button"
              aria-pressed={pickMode === "empty"}
              className={segmentClass(pickMode === "empty")}
              onClick={() => setPickMode("empty")}
            >
              {t("workshop.bead.pickEmpty")}
            </button>
            <button
              type="button"
              aria-pressed={
                draft.emptySelection?.kind === "none"
              }
              className={segmentClass(
                draft.emptySelection?.kind === "none",
              )}
              onClick={() => {
                setPickMode("none");
                onChange({
                  ...draft,
                  emptySelection: { kind: "none" },
                });
              }}
            >
              {t("workshop.bead.noEmpty")}
            </button>
            <button
              type="button"
              aria-pressed={pickMode === "transparent-support"}
              className={segmentClass(
                pickMode === "transparent-support",
              )}
              onClick={() => setPickMode("transparent-support")}
            >
              {t("workshop.bead.pickSupport")}
            </button>
            {draft.transparentSupportSampleCellIndex !== null && (
              <button
                type="button"
                className={segmentClass(false)}
                onClick={() =>
                  onChange({
                    ...draft,
                    transparentSupportSampleCellIndex: null,
                  })
                }
              >
                {t("workshop.bead.clearSupport")}
              </button>
            )}
          </div>

          <div className="space-y-1 text-xs text-slate-500 dark:text-slate-400">
            {draft.emptySelection?.kind === "sample" && (
              <p>
                {interpolate(t("workshop.bead.emptySample"), {
                  index: draft.emptySelection.cellIndex + 1,
                })}
              </p>
            )}
            {draft.emptySelection?.kind === "none" && (
              <p>{t("workshop.bead.noEmptySelected")}</p>
            )}
            {draft.transparentSupportSampleCellIndex !== null && (
              <p>
                {interpolate(t("workshop.bead.supportSample"), {
                  index:
                    draft.transparentSupportSampleCellIndex + 1,
                })}
              </p>
            )}
          </div>

          {!validGrid && (
            <StatusBanner tone="warning">
              {t("workshop.bead.gridInvalid")}
            </StatusBanner>
          )}
          {validGrid && !hasEmptyDecision && (
            <StatusBanner tone="warning">
              {t("workshop.bead.emptyDecisionRequired")}
            </StatusBanner>
          )}
          <Button
            label={t(
              busy
                ? "workshop.bead.recognizing"
                : "workshop.bead.recognize",
            )}
            loading={busy}
            disabled={!canRecognize}
            onClick={onRecognize}
            className="w-full"
          />
        </section>

        <section
          className={cx(
            resolveSectionCardClass("standard"),
            "flex min-w-0 items-center justify-center overflow-hidden",
          )}
        >
          <BeadSourceCanvas
            source={source}
            rows={draft.rows}
            columns={draft.columns}
            geometry={draft.geometry}
            ariaLabel={t("workshop.bead.calibrationCanvas")}
            pickMode={pickMode}
            emptyCellIndex={
              draft.emptySelection?.kind === "sample"
                ? draft.emptySelection.cellIndex
                : null
            }
            transparentSupportCellIndex={
              draft.transparentSupportSampleCellIndex
            }
            onPickCell={handleCellPick}
          />
        </section>
      </div>
    </div>
  );
}
