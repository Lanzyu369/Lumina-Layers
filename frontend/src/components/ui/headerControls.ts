// No `shadow-*` utility here: a global rule strips box-shadow from any class
// containing "shadow-", which would also remove the focus ring.
export const HEADER_ICON_BUTTON_CLASS =
  "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-slate-200/80 bg-slate-100/85 text-slate-600 transition-colors hover:bg-slate-200/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800/80";

/** Dropdown surface shared by the header's panel-controls and more-options menus. */
export const HEADER_MENU_PANEL_CLASS =
  "absolute right-0 top-full z-50 mt-2 flex origin-top-right flex-col gap-1 overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-100 p-2 shadow-[var(--shadow-control-hover)] dark:border-slate-800/80 dark:bg-slate-900";

export const HEADER_MENU_ITEM_CLASS =
  "flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm font-semibold tracking-wide text-slate-600 outline-none transition-colors duration-200 hover:bg-[var(--nav-chip-hover)] hover:text-slate-900 focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:text-slate-300 dark:hover:text-slate-100";

export const HEADER_MENU_DIVIDER_CLASS = "mx-2 my-1 h-px bg-slate-200 dark:bg-slate-700/80";
