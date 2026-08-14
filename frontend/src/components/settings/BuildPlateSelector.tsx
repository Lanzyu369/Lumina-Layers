import { useRef } from "react";
import type { KeyboardEvent } from "react";

import type { BuildPlateInfo } from "../../api/types";
import { useI18n } from "../../i18n/context";

interface BuildPlateSelectorProps {
  label: string;
  hint: string;
  plates: BuildPlateInfo[];
  selectedId: string;
  onSelect: (plateId: string) => void;
  language?: "zh" | "en";
}

export default function BuildPlateSelector({
  label,
  hint,
  plates,
  selectedId,
  onSelect,
  language,
}: BuildPlateSelectorProps) {
  const { lang } = useI18n();
  const resolvedLanguage = language ?? lang;
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedIndex = plates.findIndex((plate) => plate.id === selectedId);
  const tabStopIndex = selectedIndex >= 0 ? selectedIndex : 0;

  if (plates.length === 0) {
    return null;
  }

  const handleKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    let nextIndex: number;
    switch (event.key) {
      case "ArrowLeft":
      case "ArrowUp":
        nextIndex = (currentIndex - 1 + plates.length) % plates.length;
        break;
      case "ArrowRight":
      case "ArrowDown":
        nextIndex = (currentIndex + 1) % plates.length;
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = plates.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    optionRefs.current[nextIndex]?.focus();
    onSelect(plates[nextIndex].id);
  };

  return (
    <div
      data-testid="build-plate-selector"
      className="border-t border-slate-200/60 pt-5 dark:border-slate-700/60"
    >
      <div className="mb-3">
        <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
          {label}
        </h4>
        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
          {hint}
        </p>
      </div>
      <div
        role="radiogroup"
        aria-label={label}
        data-testid="build-plate-horizontal-strip"
        className="flex snap-x gap-3 overflow-x-auto px-0.5 pb-2 pt-0.5"
      >
        {plates.map((plate, index) => {
          const selected = plate.id === selectedId;
          const displayName =
            resolvedLanguage === "zh" && plate.display_name_zh
              ? plate.display_name_zh
              : plate.display_name;
          return (
            <button
              key={plate.id}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={index === tabStopIndex ? 0 : -1}
              ref={(element) => {
                optionRefs.current[index] = element;
              }}
              onClick={() => onSelect(plate.id)}
              onKeyDown={(event) => handleKeyDown(event, index)}
              className={`group relative flex w-44 shrink-0 snap-start flex-col rounded-2xl p-3 text-left transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950 ${
                selected
                  ? "bg-blue-500/10 ring-2 ring-inset ring-blue-500 dark:bg-blue-400/10 dark:ring-blue-400"
                  : "bg-slate-100/70 ring-1 ring-inset ring-slate-200/80 hover:bg-slate-100 dark:bg-slate-800/55 dark:ring-slate-700/80 dark:hover:bg-slate-800"
              }`}
            >
              <span className="flex h-24 w-full items-center justify-center overflow-hidden rounded-xl bg-[var(--surface-panel-strong)] px-2 py-2 dark:bg-slate-950/35">
                <img
                  src={plate.image_url}
                  alt=""
                  aria-hidden="true"
                  className="max-h-full max-w-full object-contain"
                  loading="lazy"
                />
              </span>
              <span className="mt-2 min-h-10 text-xs font-medium leading-5 text-slate-800 dark:text-slate-100">
                {displayName}
              </span>
              <span
                aria-hidden="true"
                className={`absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full border ${
                  selected
                    ? "border-blue-500 bg-blue-500 dark:border-blue-400 dark:bg-blue-400"
                    : "border-slate-300 bg-[var(--surface-panel-strong)] dark:border-slate-600 dark:bg-slate-900"
                }`}
              >
                {selected && (
                  <span className="h-2 w-2 rounded-full bg-[color:var(--surface-panel-strong)]" />
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
