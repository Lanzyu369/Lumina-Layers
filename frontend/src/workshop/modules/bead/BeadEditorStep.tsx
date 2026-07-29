import { useMemo, useState } from "react";

import Button from "../../../components/ui/Button";
import Checkbox from "../../../components/ui/Checkbox";
import HelpDot from "../../../components/ui/HelpDot";
import Slider from "../../../components/ui/Slider";
import {
  PanelIntro,
  StatusBanner,
  cx,
  resolveSectionCardClass,
  workstationFieldLabelClass,
  workstationInputClass,
} from "../../../components/ui/panelPrimitives";
import type { WorkshopRaster } from "../../types";
import { BeadMatrixCanvas } from "./BeadMatrixCanvas";
import { BeadSourceCanvas } from "./BeadSourceCanvas";
import type {
  BeadEditorAction,
  BeadEditorState,
  BeadEditorTool,
} from "./editorReducer";
import { calculatePhysicalSize } from "./project";
import type { BeadRenderResult } from "./renderer";
import type { RgbColor } from "./types";

type EditorView = "original" | "matrix" | "pressure";

interface BeadEditorStepProps {
  state: BeadEditorState;
  renderResult: BeadRenderResult | null;
  renderBusy: boolean;
  sourceRaster: WorkshopRaster | null;
  translate(key: string): string;
  dispatch(action: BeadEditorAction): void;
  onNewProject(): void;
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

function toHex(color: RgbColor): string {
  return `#${color
    .map((channel) => channel.toString(16).padStart(2, "0"))
    .join("")}`;
}

function fromHex(value: string): RgbColor | null {
  const match = /^#([0-9a-f]{6})$/i.exec(value);
  if (!match) {
    return null;
  }
  const number = Number.parseInt(match[1], 16);
  return [
    (number >> 16) & 255,
    (number >> 8) & 255,
    number & 255,
  ];
}

function formatMillimeters(value: number): string {
  return Number(value.toFixed(3)).toString();
}

function controlClass(active: boolean): string {
  return cx(
    "min-h-10 rounded-xl px-3 text-xs font-semibold transition-all focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)]",
    active
      ? "bg-blue-600 text-white shadow-[var(--shadow-control)]"
      : "border border-slate-200/80 bg-white/70 text-slate-600 hover:bg-white dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-900",
  );
}

export function BeadEditorStep({
  state,
  renderResult,
  renderBusy,
  sourceRaster,
  translate: t,
  dispatch,
  onNewProject,
}: BeadEditorStepProps) {
  const [view, setView] = useState<EditorView>("matrix");
  const [showGrid, setShowGrid] = useState(true);
  const project = state.present;
  const unresolvedIssueIndices = useMemo(
    () =>
      project.confidenceIssues.flatMap((issue, index) =>
        issue.resolved ? [] : [index],
      ),
    [project.confidenceIssues],
  );
  const selectedPendingPosition = unresolvedIssueIndices.indexOf(
    state.selectedIssueIndex ?? -1,
  );
  const size = calculatePhysicalSize(
    project,
    project.beadPitchMm,
  );

  const selectIssue = (direction: -1 | 1) => {
    if (unresolvedIssueIndices.length === 0) {
      return;
    }
    const current =
      selectedPendingPosition >= 0 ? selectedPendingPosition : -1;
    const next =
      (current + direction + unresolvedIssueIndices.length) %
      unresolvedIssueIndices.length;
    dispatch({
      type: "select-issue",
      issueIndex: unresolvedIssueIndices[next],
    });
  };

  const applyAt = (cellIndex: number) => {
    dispatch({
      type: "apply-tool",
      tool: state.activeTool,
      cellIndex,
      paletteIndex: state.activePaletteIndex,
      updatedAt: new Date().toISOString(),
    });
  };

  const setCompression = (compression: number) => {
    dispatch({
      type: "set-compression",
      compression,
      updatedAt: new Date().toISOString(),
    });
  };

  const sourceGeometry = sourceRaster
    ? {
        originX: 0,
        originY: 0,
        cellWidth: sourceRaster.width / project.columns,
        cellHeight: sourceRaster.height / project.rows,
      }
    : null;

  const toolNames: BeadEditorTool[] = [
    "paint",
    "erase",
    "eyedropper",
    "fill",
    "support",
  ];

  return (
    <div className="flex flex-col gap-5">
      <PanelIntro
        eyebrow={`${project.columns} × ${project.rows}`}
        title={t("workshop.bead.editorTitle")}
        description={t("workshop.bead.editorDescription")}
        action={
          <Button
            label={t("workshop.bead.newProject")}
            variant="secondary"
            onClick={onNewProject}
          />
        }
      />

      <div className="grid min-h-0 gap-5 xl:grid-cols-[minmax(19rem,25rem)_minmax(0,1fr)]">
        <aside
          className={cx(
            resolveSectionCardClass("standard"),
            "flex flex-col gap-5",
          )}
        >
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-2">
            {toolNames.map((tool) => (
              <button
                key={tool}
                type="button"
                aria-pressed={state.activeTool === tool}
                className={controlClass(state.activeTool === tool)}
                onClick={() => dispatch({ type: "set-tool", tool })}
              >
                {t(`workshop.bead.tool.${tool}`)}
              </button>
            ))}
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              className={cx(controlClass(false), "flex-1")}
              onClick={() => dispatch({ type: "undo" })}
            >
              {t("workshop.bead.undo")}
            </button>
            <button
              type="button"
              className={cx(controlClass(false), "flex-1")}
              onClick={() => dispatch({ type: "redo" })}
            >
              {t("workshop.bead.redo")}
            </button>
          </div>

          <div className="flex flex-wrap gap-2">
            {project.palette.map((color, index) => (
              <button
                key={`${color.join("-")}-${index}`}
                type="button"
                aria-label={interpolate(
                  t("workshop.bead.paletteColor"),
                  { index: index + 1 },
                )}
                aria-pressed={state.activePaletteIndex === index}
                onClick={() =>
                  dispatch({ type: "set-palette", paletteIndex: index })
                }
                className={cx(
                  "h-10 w-10 rounded-full border-2 shadow-[var(--shadow-control)] transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)]",
                  state.activePaletteIndex === index
                    ? "border-blue-500"
                    : "border-slate-200 dark:border-slate-700",
                )}
                style={{
                  backgroundColor: `rgb(${color[0]} ${color[1]} ${color[2]})`,
                }}
              />
            ))}
            <label className="panel-section-muted flex min-h-10 items-center gap-2 rounded-xl px-2.5 text-xs font-medium text-slate-600 dark:text-slate-300">
              <span>{t("workshop.bead.customColor")}</span>
              <input
                type="color"
                aria-label={t("workshop.bead.customColor")}
                value={
                  toHex(
                    project.palette[state.activePaletteIndex] ??
                      project.palette[0] ??
                      ([0, 0, 0] as RgbColor),
                  )
                }
                onChange={(event) => {
                  const color = fromHex(event.target.value);
                  if (color) {
                    dispatch({
                      type: "add-palette-color",
                      color,
                      updatedAt: new Date().toISOString(),
                    });
                  }
                }}
                className="h-7 w-8 cursor-pointer rounded-lg border-0 bg-transparent p-0"
              />
            </label>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-medium text-slate-600 dark:text-slate-300">
              {interpolate(t("workshop.bead.reviewSummary"), {
                pending: unresolvedIssueIndices.length,
                total: project.confidenceIssues.length,
              })}
            </p>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                className={controlClass(false)}
                onClick={() => selectIssue(-1)}
              >
                {t("workshop.bead.previousIssue")}
              </button>
              <button
                type="button"
                className={controlClass(false)}
                onClick={() => selectIssue(1)}
              >
                {t("workshop.bead.nextIssue")}
              </button>
            </div>
          </div>

          <Slider
            label={t("workshop.bead.compression")}
            tooltip={t("workshop.bead.compressionHint")}
            value={project.compression}
            min={0}
            max={100}
            step={1}
            onChange={setCompression}
          />

          <div className="grid grid-cols-3 gap-2">
            {(
              [
                [0, "workshop.bead.pressureLight"],
                [50, "workshop.bead.pressureStandard"],
                [100, "workshop.bead.pressureTight"],
              ] as const
            ).map(([compression, key]) => (
              <button
                key={compression}
                type="button"
                aria-pressed={project.compression === compression}
                className={controlClass(
                  project.compression === compression,
                )}
                onClick={() => setCompression(compression)}
              >
                {t(key)}
              </button>
            ))}
          </div>

          <label className="flex flex-col gap-1.5">
            <span
              className={cx(
                workstationFieldLabelClass,
                "flex items-center gap-1.5",
              )}
            >
              <span>{t("workshop.bead.beadPitch")}</span>
              <HelpDot
                title={t("workshop.bead.beadPitch")}
                description={t("workshop.bead.beadPitchHint")}
              />
            </span>
            <input
              aria-label={t("workshop.bead.beadPitch")}
              type="number"
              min={0.5}
              max={10}
              step={0.1}
              value={project.beadPitchMm}
              className={workstationInputClass}
              onChange={(event) =>
                dispatch({
                  type: "set-bead-pitch",
                  beadPitchMm: Number(event.target.value),
                  updatedAt: new Date().toISOString(),
                })
              }
            />
          </label>

          <p className="text-center text-sm font-semibold tabular-nums text-slate-700 dark:text-slate-200">
            {interpolate(t("workshop.bead.physicalSize"), {
              width: formatMillimeters(size.widthMm),
              height: formatMillimeters(size.heightMm),
            })}
          </p>

          <Checkbox
            label={t("workshop.bead.showGrid")}
            checked={showGrid}
            onChange={setShowGrid}
          />
        </aside>

        <section
          className={cx(
            resolveSectionCardClass("standard"),
            "flex min-w-0 flex-col gap-4",
          )}
        >
          <div className="flex flex-wrap gap-2">
            {(
              ["original", "matrix", "pressure"] as const
            ).map((candidate) => (
              <button
                key={candidate}
                type="button"
                aria-pressed={view === candidate}
                disabled={
                  candidate === "original" && sourceRaster === null
                }
                className={controlClass(view === candidate)}
                onClick={() => setView(candidate)}
              >
                {t(`workshop.bead.view.${candidate}`)}
              </button>
            ))}
          </div>

          {renderBusy && view === "pressure" && (
            <StatusBanner tone="info">
              {t("workshop.bead.rendering")}
            </StatusBanner>
          )}

          <div className="flex min-h-72 flex-1 items-center justify-center overflow-auto rounded-[22px] bg-slate-100/65 p-3 dark:bg-slate-950/45">
            {view === "original" && sourceRaster && sourceGeometry ? (
              <BeadSourceCanvas
                source={sourceRaster}
                rows={project.rows}
                columns={project.columns}
                geometry={sourceGeometry}
                ariaLabel={t("workshop.bead.originalCanvas")}
              />
            ) : view === "pressure" ? (
              <BeadMatrixCanvas
                project={project}
                renderResult={renderResult}
                showGrid={false}
                selectedCellIndex={state.selectedCellIndex}
                ariaLabel={t("workshop.bead.pressureCanvas")}
              />
            ) : (
              <BeadMatrixCanvas
                project={project}
                showGrid={showGrid}
                selectedCellIndex={state.selectedCellIndex}
                onPickCell={applyAt}
                ariaLabel={t("workshop.bead.matrixCanvas")}
              />
            )}
          </div>

          {state.selectedCellIndex !== null && (
            <div className="panel-section fixed bottom-5 right-5 z-20 w-44 rounded-[22px] p-2 shadow-xl backdrop-blur">
              <p className="mb-2 text-center text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                {t("workshop.bead.magnifier")}
              </p>
              <BeadMatrixCanvas
                project={project}
                ariaLabel={t("workshop.bead.magnifier")}
                showGrid
                selectedCellIndex={state.selectedCellIndex}
                viewport={{
                  centerCellIndex: state.selectedCellIndex,
                  radius: 2,
                }}
              />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
