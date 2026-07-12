/**
 * One-shot directory_name migration helpers for saved materials.
 * 已保存耗材的 directory_name 一次性迁移辅助函数。
 *
 * Before the brand-subdirectory feature, materials were saved flat as
 * ``<material_name>/``; persisted selections referenced those flat names.
 * After reorganising archives under ``<brand>/<material_name>/``, those
 * cached flat names no longer resolve on the backend (404).
 *
 * This module maps legacy flat names to the unique nested directory_name
 * now advertised by the material library endpoint. Ambiguous and missing
 * legacy entries are dropped so that stale selections cannot block the UI.
 */

/** Minimal shape of the material library item required for migration. */
export interface DirectoryNameCandidate {
  directory_name: string;
}

const MATERIAL_BRAND_DIRECTORY_RENAMES = [["无境新材", "Karvax"]] as const;

const resolveRenamedBrandDirectoryName = (
  directoryName: string,
  knownDirectoryNames: ReadonlySet<string>,
): string | null => {
  for (const [formerBrand, currentBrand] of MATERIAL_BRAND_DIRECTORY_RENAMES) {
    if (!directoryName.startsWith(`${formerBrand}/`)) continue;
    const renamedDirectoryName = directoryName.replaceAll(formerBrand, currentBrand);
    return knownDirectoryNames.has(renamedDirectoryName) ? renamedDirectoryName : null;
  }
  return null;
};

/**
 * Build a lookup that maps a legacy flat name (e.g. ``"瑞贝思 PLA 白"``) to
 * the unique current directory_name (e.g. ``"瑞贝思/瑞贝思 PLA 白"``).
 *
 * A legacy name is only remapped when exactly one advertised directory_name
 * ends with ``/<legacy>``. Ambiguous matches are skipped so we never pick
 * the wrong archive silently.
 */
export function buildLegacyDirectoryNameMap(
  library: readonly DirectoryNameCandidate[],
): Map<string, string> {
  const trailingCounts = new Map<string, number>();
  const trailingPicks = new Map<string, string>();
  for (const item of library) {
    const full = item.directory_name;
    if (!full || !full.includes("/")) continue;
    const tail = full.substring(full.lastIndexOf("/") + 1);
    if (!tail) continue;
    trailingCounts.set(tail, (trailingCounts.get(tail) ?? 0) + 1);
    trailingPicks.set(tail, full);
  }
  const result = new Map<string, string>();
  for (const [tail, count] of trailingCounts) {
    if (count === 1) {
      const pick = trailingPicks.get(tail);
      if (pick) result.set(tail, pick);
    }
  }
  return result;
}

/**
 * Reconcile a persisted directory_name list against the current library.
 *
 * Return object:
 * - ``names``: the reconciled list, preserving input order, with legacy
 *   flat entries substituted to their unique nested equivalents and
 *   unresolvable entries dropped.
 * - ``changed``: whether any substitution or drop occurred. Callers should
 *   re-persist only when ``true`` to avoid needless localStorage churn.
 *
 * Directory names already matching a library entry are kept verbatim, so
 * this function is safe to run on fresh selections as well.
 */
export function reconcileDirectoryNames(
  selected: readonly string[],
  library: readonly DirectoryNameCandidate[],
): { names: string[]; changed: boolean } {
  if (selected.length === 0) {
    return { names: [], changed: false };
  }
  const knownDirNames = new Set(library.map((item) => item.directory_name));
  const legacyMap = buildLegacyDirectoryNameMap(library);

  const next: string[] = [];
  let changed = false;
  for (const raw of selected) {
    const name = raw.trim();
    if (!name) {
      changed = true;
      continue;
    }
    if (knownDirNames.has(name)) {
      next.push(name);
      continue;
    }
    const renamedDirectoryName = resolveRenamedBrandDirectoryName(name, knownDirNames);
    if (renamedDirectoryName) {
      next.push(renamedDirectoryName);
      changed = true;
      continue;
    }
    const mapped = legacyMap.get(name);
    if (mapped && knownDirNames.has(mapped)) {
      next.push(mapped);
      changed = true;
      continue;
    }
    // Unresolvable entry: drop so the backend never sees a stale name.
    changed = true;
  }
  return { names: next, changed };
}
