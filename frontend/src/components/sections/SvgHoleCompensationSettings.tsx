import { useState } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  useConverterStore,
  isSvgHoleCompensationAvailable,
} from "../../stores/converter/store";
import { useI18n } from "../../i18n/context";
import Switch from "../ui/Switch";
import HelpDot from "../ui/HelpDot";
import { workstationInputClass } from "../ui/panelPrimitives";

/** Optional hole filling for the shared source SVG. 共用 SVG 原图的可选补洞设置。 */
export default function SvgHoleCompensationSettings() {
  const { t } = useI18n();
  const state = useConverterStore(useShallow((s) => ({
    available: isSvgHoleCompensationAvailable(s),
    enabled: s.svg_hole_compensation_enabled,
    area: s.svg_hole_max_area_mm2,
    width: s.svg_hole_max_width_mm,
    setEnabled: s.setSvgHoleCompensationEnabled,
    setArea: s.setSvgHoleMaxAreaMm2,
    setWidth: s.setSvgHoleMaxWidthMm,
  })));

  return (
    <section className="flex flex-col gap-4 border-t panel-divider pt-5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-1.5">
          <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {t("svg_hole_compensation")}
          </h3>
          <HelpDot
            title={t("svg_hole_compensation")}
            description={t("svg_hole_compensation_hint")}
          />
        </div>
        <Switch
          ariaLabel={t("svg_hole_compensation")}
          checked={state.available && state.enabled}
          disabled={!state.available}
          onChange={state.setEnabled}
        />
      </div>
      {!state.available && (
        <p role="status" className="text-xs text-[var(--surface-text-muted)]">
          {t("svg_hole_compensation_unavailable")}
        </p>
      )}
      {state.available && state.enabled && (
        <div className="grid gap-3 sm:grid-cols-2">
          <PhysicalThresholdInput
            label={t("svg_hole_max_area")}
            hint={t("svg_hole_max_area_hint")}
            value={state.area}
            onChange={state.setArea}
          />
          <PhysicalThresholdInput
            label={t("svg_hole_max_width")}
            hint={t("svg_hole_max_width_hint")}
            value={state.width}
            onChange={state.setWidth}
          />
        </div>
      )}
    </section>
  );
}

function PhysicalThresholdInput({ label, hint, value, onChange }: {
  label: string;
  hint: string;
  value: number;
  onChange: (value: number) => void;
}) {
  // Keep intermediate text such as "0." local until the user commits it.
  const [draft, setDraft] = useState<string | null>(null);

  const commitValue = (text: string) => {
    const next = Number(text);
    if (text.trim() !== "" && Number.isFinite(next) && next >= 0) {
      onChange(next);
    }
    setDraft(null);
  };

  return (
    <label className="flex flex-col gap-1.5 text-sm text-slate-700 dark:text-slate-200">
      <span className="flex items-center gap-1.5">
        {label}<HelpDot title={label} description={hint} />
      </span>
      <input
        type="text"
        inputMode="decimal"
        value={draft ?? String(value)}
        aria-label={label}
        className={workstationInputClass}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onBlur={(event) => commitValue(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            event.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}
