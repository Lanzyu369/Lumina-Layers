import { useEffect, useState } from "react";
import { useI18n } from "../../i18n/context";
import {
  INTERFACE_SCALE_PREFERENCES,
  canChooseInterfaceScale,
  getInterfaceScale,
  isInterfaceScalePreference,
  onInterfaceScaleChanged,
  setInterfaceScale,
  type InterfaceScalePreference,
} from "../../integrations/electron";
import Dropdown from "../ui/Dropdown";

/**
 * Desktop-only interface scale. The desktop host keeps the value because it
 * zooms the window before the page loads; browsers have their own zoom.
 * 仅桌面版显示的界面缩放。缩放值由桌面主进程保存，以便页面加载前就按它缩放窗口；浏览器使用自带缩放。
 */
export default function InterfaceScaleSetting() {
  const { t } = useI18n();
  const available = canChooseInterfaceScale();
  const [preference, setPreference] = useState<InterfaceScalePreference | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!available) return;
    let active = true;
    const unsubscribe = onInterfaceScaleChanged((next) => {
      setPreference(next);
      setFailed(false);
    });
    getInterfaceScale()
      .then((current) => {
        if (active) setPreference(current);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [available]);

  if (!available) {
    return null;
  }

  const choose = async (next: InterfaceScalePreference) => {
    setFailed(false);
    try {
      setPreference(await setInterfaceScale(next));
    } catch {
      setFailed(true);
    }
  };

  return (
    <div
      data-testid="settings-interface-scale-section"
      className="flex flex-col gap-3 border-t border-slate-200/60 pt-5 dark:border-slate-700/60"
    >
      <Dropdown
        label={t("settings.interface_scale_label")}
        tooltip={t("settings.interface_scale_description")}
        value={preference ?? ""}
        disabled={preference === null}
        options={INTERFACE_SCALE_PREFERENCES.map((value) => ({
          value,
          label: `${value}%`,
        }))}
        onChange={(value) => {
          if (isInterfaceScalePreference(value)) void choose(value);
        }}
      />
      {failed && (
        <p role="alert" className="text-xs text-red-500 dark:text-red-400">
          {t("settings.interface_scale_failed")}
        </p>
      )}
    </div>
  );
}
