import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n/context";
import { useLuminaBoxBackedGradientSerialStore } from "../stores/luminaBoxBackedGradientSerialStore";
import { useLuminaBoxStackSerialStore } from "../stores/luminaBoxStackSerialStore";
import LuminaBoxMaterialPanel from "./LuminaBoxMaterialPanel";
import LuminaBoxStackSamplesPanel from "./LuminaBoxStackSamplesPanel";

type WorkspaceTab = "material" | "stack-samples";
const tabs: WorkspaceTab[] = ["material", "stack-samples"];
const tabLabels = {
  material: "lumina_box_workspace_material_capture",
  "stack-samples": "lumina_box_workspace_stack_samples",
};
const tabStores = {
  material: useLuminaBoxBackedGradientSerialStore,
  "stack-samples": useLuminaBoxStackSerialStore,
};

/** Switch between material and printed-card capture after releasing the device.
 * 释放设备连接后，在耗材采集和叠色验证卡采集之间切换。 */
export default function LuminaBoxWorkspace() {
  const { t } = useI18n();
  const [tab, setTab] = useState<WorkspaceTab>("material");
  const [switching, setSwitching] = useState(false);
  const [switchFailed, setSwitchFailed] = useState(false);
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const switchRef = useRef<AbortController | null>(null);
  const focusTabRef = useRef<WorkspaceTab | null>(null);
  useEffect(() => () => { switchRef.current?.abort(); }, []);
  useEffect(() => {
    if (!switching && focusTabRef.current === tab) {
      buttons.current[tabs.indexOf(tab)]?.focus();
      focusTabRef.current = null;
    }
  }, [tab, switching]);

  const chooseTab = async (next: WorkspaceTab, focus = false) => {
    if (next === tab || switchRef.current) return;
    const controller = new AbortController();
    switchRef.current = controller;
    setSwitching(true);
    setSwitchFailed(false);
    const store = tabStores[tab];
    try {
      await store.getState().disconnect();
      if (controller.signal.aborted) return;
      // A timed-out disconnect can resolve while the physical port remains busy.
      if (store.getState().status !== "disconnected") {
        setSwitchFailed(true);
        return;
      }
      if (focus) focusTabRef.current = next;
      setTab(next);
    } catch {
      if (!controller.signal.aborted) setSwitchFailed(true);
    } finally {
      if (!controller.signal.aborted) setSwitching(false);
      if (switchRef.current === controller) switchRef.current = null;
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="lumina-box-workspace">
      <div className="shrink-0 px-3 pt-3 sm:px-5 lg:px-7">
        <div role="tablist" aria-label={t("lumina_box_workspace_tabs")}
          className="inline-flex max-w-full gap-1 overflow-x-auto rounded-[10px] bg-[var(--surface-well)] p-1">
          {tabs.map((item, index) => <button key={item} type="button" role="tab" id={`lumina-box-${item}-tab`}
            ref={(element) => { buttons.current[index] = element; }} aria-selected={tab === item}
            aria-controls={`lumina-box-${item}-tabpanel`} tabIndex={tab === item ? 0 : -1} disabled={switching}
            className={`min-h-10 shrink-0 rounded-lg px-4 text-sm font-medium outline-none transition focus:ring-4 focus:ring-[var(--focus-ring)] disabled:cursor-wait disabled:opacity-60 ${tab === item
              ? "bg-[var(--surface-panel-strong)] text-blue-700 dark:text-blue-300"
              : "text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100"}`}
            onClick={() => void chooseTab(item)} onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
              event.preventDefault();
              const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
                : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
              void chooseTab(tabs[next], true);
            }} data-testid={`lumina-box-workspace-${item}`}>
            {t(tabLabels[item])}
          </button>)}
        </div>
        {switching || switchFailed ? <p className="mt-2 text-xs text-slate-500 dark:text-slate-400" role="status" data-testid="lumina-box-workspace-switch-status">
          {t(switchFailed ? "lumina_box_workspace_switch_failed" : "lumina_box_workspace_disconnecting")}
        </p> : null}
      </div>
      <div role="tabpanel" id={`lumina-box-${tab}-tabpanel`} aria-labelledby={`lumina-box-${tab}-tab`}
        className="min-h-0 flex-1" inert={switching} aria-busy={switching}>
        {tab === "material" ? <LuminaBoxMaterialPanel /> : <LuminaBoxStackSamplesPanel />}
      </div>
    </div>
  );
}
