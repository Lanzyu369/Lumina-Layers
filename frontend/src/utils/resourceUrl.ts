const RELATIVE_PATH_PREFIXES = ["/api", "/output"] as const;

/**
 * Normalize backend resource URLs to frontend-relative paths.
 * - Relative inputs are returned as-is.
 * - Absolute HTTP(S) URLs pointing to known backend resource paths are converted to relative.
 * - Other absolute URLs are preserved.
 */
export function normalizeResourceUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (!/^https?:\/\//i.test(url)) {
    return url;
  }

  try {
    const parsed = new URL(url);
    const path = parsed.pathname;
    const shouldRelativize = RELATIVE_PATH_PREFIXES.some(
      (prefix) => path === prefix || path.startsWith(`${prefix}/`),
    );
    if (!shouldRelativize) {
      return url;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return url;
  }
}
