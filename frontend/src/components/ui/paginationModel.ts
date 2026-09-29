export type PaginationItem = number | "gap-start" | "gap-end";

/** Page count for `total` items; always at least one page. */
export const resolvePageCount = (total: number, pageSize: number): number =>
  Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, pageSize)));

export const clampPage = (page: number, pageCount: number): number =>
  Math.min(Math.max(1, Math.trunc(page) || 1), Math.max(1, pageCount));

/**
 * Compact page list: first, last, and `siblings` pages around the current one,
 * with gap markers in between (1 … 4 5 6 … 29).
 */
export const buildPaginationItems = (
  page: number,
  pageCount: number,
  siblings = 1,
): PaginationItem[] => {
  const current = clampPage(page, pageCount);
  if (pageCount <= siblings * 2 + 5) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }
  // A gap always hides at least two pages; a single hidden page is shown instead.
  const start = Math.max(Math.min(current - siblings, pageCount - siblings * 2 - 2), 3);
  const end = Math.min(Math.max(current + siblings, siblings * 2 + 3), pageCount - 2);
  const items: PaginationItem[] = [1, start > 3 ? "gap-start" : 2];
  for (let value = start; value <= end; value += 1) {
    items.push(value);
  }
  items.push(end < pageCount - 2 ? "gap-end" : pageCount - 1, pageCount);
  return items;
};
