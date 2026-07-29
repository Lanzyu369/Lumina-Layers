import {
  WORKSHOP_MANIFEST_SCHEMA_VERSION,
  type WorkshopCapability,
  type WorkshopModuleDefinition,
  type WorkshopModuleManifest,
} from "./types";

export const WORKSHOP_CAPABILITIES = [
  "file.pick-image",
  "project.read-write",
  "handoff.image",
  "ui.theme",
  "ui.locale",
  "status.progress",
  "status.error",
] as const satisfies readonly WorkshopCapability[];

const KNOWN_CAPABILITIES = new Set<string>(WORKSHOP_CAPABILITIES);
const SEMVER_PATTERN = /^\d+\.\d+\.\d+$/;
const MODULE_ID_PATTERN = /^[a-z0-9]+(?:[.-][a-z0-9]+)+$/;

export type WorkshopModuleDisabledReason =
  | "duplicate-id"
  | "invalid-manifest"
  | "unsupported-manifest"
  | "unknown-capability"
  | "app-version-too-old"
  | "not-whitelisted";

export interface RegisteredWorkshopModule {
  definition: WorkshopModuleDefinition;
  enabled: boolean;
  reason: WorkshopModuleDisabledReason | null;
}

export interface WorkshopRegistryOptions {
  appVersion: string;
  whitelist: ReadonlySet<string>;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isLocalizedText(value: unknown): boolean {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const localized = value as Record<string, unknown>;
  return isNonEmptyString(localized.zh) && isNonEmptyString(localized.en);
}

function isStringArray(value: unknown, allowEmpty = false): value is string[] {
  return (
    Array.isArray(value) &&
    (allowEmpty || value.length > 0) &&
    value.every(isNonEmptyString)
  );
}

function hasValidManifestShape(
  manifest: WorkshopModuleManifest,
): boolean {
  return (
    MODULE_ID_PATTERN.test(manifest.id) &&
    isLocalizedText(manifest.name) &&
    isLocalizedText(manifest.description) &&
    isNonEmptyString(manifest.author) &&
    SEMVER_PATTERN.test(manifest.version) &&
    isNonEmptyString(manifest.icon) &&
    SEMVER_PATTERN.test(manifest.minLuminaVersion) &&
    isStringArray(manifest.inputKinds) &&
    isStringArray(manifest.outputKinds) &&
    Array.isArray(manifest.capabilities) &&
    new Set(manifest.capabilities).size === manifest.capabilities.length
  );
}

function compareSemanticVersions(left: string, right: string): number {
  const leftParts = left.split(".").map(Number);
  const rightParts = right.split(".").map(Number);

  for (let index = 0; index < 3; index += 1) {
    const difference = leftParts[index] - rightParts[index];
    if (difference !== 0) {
      return difference;
    }
  }

  return 0;
}

function disabledReason(
  definition: WorkshopModuleDefinition,
  options: WorkshopRegistryOptions,
  duplicateIds: ReadonlySet<string>,
): WorkshopModuleDisabledReason | null {
  const { manifest } = definition;

  if (duplicateIds.has(manifest.id)) {
    return "duplicate-id";
  }
  if (manifest.manifestSchemaVersion !== WORKSHOP_MANIFEST_SCHEMA_VERSION) {
    return "unsupported-manifest";
  }
  if (!hasValidManifestShape(manifest) || !SEMVER_PATTERN.test(options.appVersion)) {
    return "invalid-manifest";
  }
  if (
    manifest.capabilities.some(
      (capability) => !KNOWN_CAPABILITIES.has(capability),
    )
  ) {
    return "unknown-capability";
  }
  if (compareSemanticVersions(options.appVersion, manifest.minLuminaVersion) < 0) {
    return "app-version-too-old";
  }
  if (!options.whitelist.has(manifest.id)) {
    return "not-whitelisted";
  }

  return null;
}

export function validateWorkshopModules(
  definitions: readonly WorkshopModuleDefinition[],
  options: WorkshopRegistryOptions,
): RegisteredWorkshopModule[] {
  const idCounts = new Map<string, number>();
  for (const { manifest } of definitions) {
    idCounts.set(manifest.id, (idCounts.get(manifest.id) ?? 0) + 1);
  }
  const duplicateIds = new Set(
    [...idCounts.entries()]
      .filter(([, count]) => count > 1)
      .map(([id]) => id),
  );

  return definitions.map((definition) => {
    const reason = disabledReason(definition, options, duplicateIds);
    return {
      definition,
      enabled: reason === null,
      reason,
    };
  });
}
