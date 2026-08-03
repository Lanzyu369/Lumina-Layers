import { WORKSHOP_API_VERSION } from "../contracts";

export const WORKSHOP_HANDSHAKE_TIMEOUT_MS = 10_000;
export const WORKSHOP_RUNTIME_CLOSE_GRACE_MS = 350;

export const WORKSHOP_RUNTIME_CSP = [
  "default-src 'none'",
  "connect-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  "worker-src data: blob:",
  "img-src data: blob:",
  "font-src data:",
  "media-src data: blob:",
  "object-src 'none'",
  "frame-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");

export type WorkshopRuntimeMode =
  | "browser"
  | "browser-unsafe-development"
  | "desktop-secure";

export type WorkshopInstallSource =
  | "registry"
  | "github"
  | "local"
  | "seed"
  | "fixture";

export interface WorkshopApiRange {
  min: string;
  maxExclusive: string;
}

export type WorkshopStartupFailureReason =
  | "candidate-prepare-failed"
  | "runtime-load-failed"
  | "handshake-timeout"
  | "activation-failed";

export interface WorkshopStartupFailure {
  moduleId: string;
  moduleVersion: string;
  reason: WorkshopStartupFailureReason;
  consecutiveFailures: number;
}

interface SemverParts {
  core: [number, number, number];
  prerelease: Array<number | string> | null;
}

function parseSemver(value: string): SemverParts | null {
  const match = value.match(
    /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/,
  );
  if (match === null) {
    return null;
  }
  const prerelease =
    match[4] === undefined
      ? null
      : match[4].split(".").map((part) =>
          /^(0|[1-9]\d*)$/.test(part)
            ? Number(part)
            : part,
        );
  return {
    core: [Number(match[1]), Number(match[2]), Number(match[3])],
    prerelease,
  };
}

function compareIdentifiers(
  left: number | string,
  right: number | string,
): number {
  if (typeof left === "number" && typeof right === "number") {
    return Math.sign(left - right);
  }
  if (typeof left === "number") {
    return -1;
  }
  if (typeof right === "number") {
    return 1;
  }
  return left.localeCompare(right);
}

export function compareWorkshopSemver(
  leftValue: string,
  rightValue: string,
): number | null {
  const left = parseSemver(leftValue);
  const right = parseSemver(rightValue);
  if (left === null || right === null) {
    return null;
  }
  for (let index = 0; index < left.core.length; index += 1) {
    if (left.core[index] !== right.core[index]) {
      return Math.sign(left.core[index] - right.core[index]);
    }
  }
  if (left.prerelease === null || right.prerelease === null) {
    if (left.prerelease === right.prerelease) {
      return 0;
    }
    return left.prerelease === null ? 1 : -1;
  }
  const length = Math.max(
    left.prerelease.length,
    right.prerelease.length,
  );
  for (let index = 0; index < length; index += 1) {
    const leftPart = left.prerelease[index];
    const rightPart = right.prerelease[index];
    if (leftPart === undefined || rightPart === undefined) {
      if (leftPart === rightPart) {
        return 0;
      }
      return leftPart === undefined ? -1 : 1;
    }
    const compared = compareIdentifiers(leftPart, rightPart);
    if (compared !== 0) {
      return Math.sign(compared);
    }
  }
  return 0;
}

export function isWorkshopApiCompatible(
  range: WorkshopApiRange,
  hostVersion = WORKSHOP_API_VERSION,
): boolean {
  const minimum = compareWorkshopSemver(hostVersion, range.min);
  const maximum = compareWorkshopSemver(
    hostVersion,
    range.maxExclusive,
  );
  return minimum !== null && maximum !== null && minimum >= 0 && maximum < 0;
}

export function desktopModuleUrl(
  moduleId: string,
  version: string,
): string {
  const safeModuleId =
    /^[a-z0-9]+(?:[.-][a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)*$/.test(
      moduleId,
    );
  const safeVersion =
    /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/.test(
      version,
    );
  if (!safeModuleId || !safeVersion) {
    throw new Error("Workshop desktop URL identity is invalid.");
  }
  return `lumina-workshop://${moduleId}/${version}/ui/index.html`;
}

export function canRunWorkshopInBrowser(
  source: WorkshopInstallSource,
  official: boolean,
  mode: WorkshopRuntimeMode,
): boolean {
  if (mode === "desktop-secure") {
    return true;
  }
  if (source === "fixture") {
    return true;
  }
  if (source === "seed" && official) {
    return true;
  }
  return mode === "browser-unsafe-development" && source === "local";
}

export function injectWorkshopRuntimeCsp(html: string): string {
  const head = /<head\b[^>]*>/i.exec(html);
  const firstScript = /<script(?:\s|>)/i.exec(html);
  if (
    head === null ||
    (firstScript !== null && firstScript.index < head.index)
  ) {
    throw new Error(
      "Workshop runtime HTML must place <head> before scripts.",
    );
  }
  const meta =
    '<meta http-equiv="Content-Security-Policy" ' +
    `content="${WORKSHOP_RUNTIME_CSP}">`;
  const insertion = head.index + head[0].length;
  return `${html.slice(0, insertion)}${meta}${html.slice(insertion)}`;
}
