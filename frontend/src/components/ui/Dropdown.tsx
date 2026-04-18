import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cx, workstationFieldLabelClass, workstationInputClass } from "./panelPrimitives";

interface DropdownProps {
  label: string;
  value: string;
  options: { label: string; value: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  labelAccessory?: ReactNode;
}

export default function Dropdown({
  label,
  value,
  options,
  onChange,
  disabled = false,
  placeholder,
  labelAccessory,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  const selectedOption = useMemo(
    () => options.find((opt) => opt.value === value) ?? null,
    [options, value],
  );

  const updateMenuPos = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const viewportPadding = 16;
    const maxMenuHeight = 288; // max-h-72 = 18rem = 288px
    // 估算实际菜单高度：每项约 44px（py-2.5 + leading-6），外层 padding 约 16px。
    // 选项少时远小于 maxMenuHeight，避免仅因未到 288px 就误判向上展开。
    const ITEM_HEIGHT = 44;
    const MENU_PADDING = 16;
    const estimatedMenuHeight = Math.min(
      maxMenuHeight,
      options.length * ITEM_HEIGHT + MENU_PADDING,
    );
    // 菜单宽度贴合触发器，避免在窄侧栏里被强制撑到最小宽度而溢出卡片边界。
    const maxWidth = window.innerWidth - viewportPadding * 2;
    const nextWidth = Math.min(rect.width, maxWidth);
    const nextLeft = Math.min(
      Math.max(rect.left, viewportPadding),
      window.innerWidth - viewportPadding - nextWidth,
    );

    // 只有当菜单实际装不下时才考虑向上展开；并且向上要比向下空间更大才翻转。
    const spaceBelow = window.innerHeight - rect.bottom - viewportPadding;
    const spaceAbove = rect.top - viewportPadding;
    const shouldOpenUpward =
      spaceBelow < estimatedMenuHeight && spaceAbove > spaceBelow;
    const upwardHeight = Math.min(estimatedMenuHeight, Math.max(spaceAbove, 0));

    setMenuPos({
      top: shouldOpenUpward ? rect.top - upwardHeight - 6 : rect.bottom + 6,
      left: nextLeft,
      width: nextWidth,
    });
  }, [options.length]);

  useEffect(() => {
    if (!open) return;
    updateMenuPos();
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        menuRef.current && !menuRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("resize", updateMenuPos);
    window.addEventListener("scroll", updateMenuPos, true);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("resize", updateMenuPos);
      window.removeEventListener("scroll", updateMenuPos, true);
    };
  }, [open, updateMenuPos]);

  const handleToggle = () => {
    if (disabled) return;
    if (!open) updateMenuPos();
    setOpen((prev) => !prev);
  };

  const handleSelect = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
  };

  const triggerLabel = selectedOption?.label ?? placeholder ?? "";
  const showPlaceholder = !selectedOption && !!placeholder;

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      {labelAccessory ? (
        <div className="flex items-center gap-2">
          <label className={workstationFieldLabelClass}>{label}</label>
          {labelAccessory}
        </div>
      ) : (
        <label className={workstationFieldLabelClass}>{label}</label>
      )}
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={label}
        disabled={disabled}
        onClick={handleToggle}
        className={cx(
          workstationInputClass,
          "flex w-full min-w-0 items-center justify-between gap-3 overflow-hidden py-2.5 text-left",
          showPlaceholder && "text-slate-400 dark:text-slate-500",
        )}
      >
        <span className="block min-w-0 flex-1 truncate text-sm leading-6">{triggerLabel}</span>
        <span
          aria-hidden="true"
          className={cx(
            "shrink-0 text-xs text-slate-400 transition-transform duration-200 dark:text-slate-500",
            open && "rotate-180"
          )}
        >
          <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.1 1.02l-4.25 4.52a.75.75 0 01-1.1 0L5.21 8.25a.75.75 0 01.02-1.04z" />
          </svg>
        </span>
      </button>

      {open && menuPos && createPortal(
        <div
          ref={menuRef}
          className="z-[1200] overflow-hidden rounded-[24px] border border-slate-200/85 bg-slate-100/96 shadow-[var(--shadow-control)] backdrop-blur-xl dark:border-slate-700/85 dark:bg-slate-950/96"
          style={{
            position: "fixed",
            top: `${menuPos.top}px`,
            left: `${menuPos.left}px`,
            width: `${menuPos.width}px`,
          }}
        >
          <div
            id={listboxId}
            role="listbox"
            className="dock-scrollbar max-h-72 overflow-y-auto p-2"
          >
            {options.map((opt) => {
              const isSelected = opt.value === value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => handleSelect(opt.value)}
                  className={cx(
                    "flex w-full items-start rounded-[18px] px-3 py-2.5 text-left text-sm leading-6 transition-colors duration-150",
                    isSelected
                      ? "bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
                      : "text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-900"
                  )}
                >
                  <span className="min-w-0 flex-1 break-all">{opt.label}</span>
                </button>
              );
            })}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
