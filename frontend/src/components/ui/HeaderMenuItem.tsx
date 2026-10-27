import type { ReactNode } from "react";
import { HEADER_MENU_ITEM_CLASS } from "./headerControls";

interface HeaderMenuItemProps {
  icon: ReactNode;
  label: string;
  onSelect: () => void;
  /** Optional value or state shown at the end of the row. */
  trailing?: ReactNode;
  /** Set for on/off items so assistive technology announces the state. */
  pressed?: boolean;
  testId?: string;
}

/**
 * One labelled action row inside the header's more-options menu.
 * 顶栏“更多选项”菜单中的一行带文字的操作。
 */
export function HeaderMenuItem({
  icon,
  label,
  onSelect,
  trailing,
  pressed,
  testId,
}: HeaderMenuItemProps) {
  return (
    <button
      type="button"
      data-testid={testId}
      aria-pressed={pressed}
      onClick={onSelect}
      className={HEADER_MENU_ITEM_CLASS}
    >
      <span
        aria-hidden="true"
        className="flex h-4 w-4 shrink-0 items-center justify-center text-slate-500 dark:text-slate-400"
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {trailing}
    </button>
  );
}
