declare const __LUMINA_VERSION__: string | undefined;

type RawUmamiRuntimeConfig = {
  enabled?: unknown;
  scriptUrl?: unknown;
  websiteId?: unknown;
  hostUrl?: unknown;
  tag?: unknown;
  domains?: unknown;
  doNotTrack?: unknown;
  excludeSearch?: unknown;
  excludeHash?: unknown;
  performance?: unknown;
};

export interface LuminaUmamiConfig {
  enabled: boolean;
  scriptUrl: string;
  websiteId: string;
  hostUrl: string | null;
  tag: string | null;
  domains: readonly string[];
  doNotTrack: boolean;
  excludeSearch: boolean;
  excludeHash: boolean;
  performance: boolean;
}

export type LuminaAnalyticsPayload = Record<
  string,
  string | number | boolean | null | undefined
>;

type UmamiWindow = Window & {
  __LUMINA_UMAMI_CONFIG__?: RawUmamiRuntimeConfig;
  umami?: {
    track?: (eventName: string, data?: Record<string, unknown>) => void;
  };
};

const SCRIPT_ELEMENT_ID = "lumina-umami-script";
const MAX_EVENT_NAME_LENGTH = 50;
const MAX_PAYLOAD_KEYS = 24;
const MAX_STRING_LENGTH = 120;
const MAX_PENDING_EVENTS = 20;
const BLOCKED_KEY_PATTERN =
  /(file|filename|path|url|session|ticket|email|description|query|search|hash|token|secret|password)/i;

const pendingEvents: Array<{
  eventName: string;
  payload: Record<string, string | number | boolean | null>;
}> = [];

function readRuntimeConfig(): RawUmamiRuntimeConfig {
  if (typeof window === "undefined") {
    return {};
  }
  const config = (window as UmamiWindow).__LUMINA_UMAMI_CONFIG__;
  return config && typeof config === "object" ? config : {};
}

function readEnvValue(key: string): string | undefined {
  const value = import.meta.env[key];
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value !== "string") return fallback;
  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return fallback;
}

function asStringList(value: unknown): readonly string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => asString(item))
      .filter((item): item is string => Boolean(item));
  }
  if (typeof value === "string") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

export function resolveLuminaUmamiConfig(): LuminaUmamiConfig {
  const runtime = readRuntimeConfig();
  const scriptUrl =
    asString(runtime.scriptUrl) ?? readEnvValue("VITE_UMAMI_SCRIPT_URL") ?? "";
  const websiteId =
    asString(runtime.websiteId) ?? readEnvValue("VITE_UMAMI_WEBSITE_ID") ?? "";
  const enabled = asBoolean(
    runtime.enabled ?? readEnvValue("VITE_UMAMI_ENABLED"),
    false,
  );

  return {
    enabled: enabled && Boolean(scriptUrl) && Boolean(websiteId),
    scriptUrl,
    websiteId,
    hostUrl:
      asString(runtime.hostUrl) ??
      readEnvValue("VITE_UMAMI_HOST_URL") ??
      null,
    tag: asString(runtime.tag) ?? readEnvValue("VITE_UMAMI_TAG") ?? null,
    domains: asStringList(
      runtime.domains ?? readEnvValue("VITE_UMAMI_DOMAINS"),
    ),
    doNotTrack: asBoolean(
      runtime.doNotTrack ?? readEnvValue("VITE_UMAMI_DO_NOT_TRACK"),
      true,
    ),
    excludeSearch: asBoolean(
      runtime.excludeSearch ?? readEnvValue("VITE_UMAMI_EXCLUDE_SEARCH"),
      true,
    ),
    excludeHash: asBoolean(
      runtime.excludeHash ?? readEnvValue("VITE_UMAMI_EXCLUDE_HASH"),
      true,
    ),
    performance: asBoolean(
      runtime.performance ?? readEnvValue("VITE_UMAMI_PERFORMANCE"),
      false,
    ),
  };
}

function setBooleanDataAttribute(
  element: HTMLScriptElement,
  name: string,
  value: boolean,
): void {
  element.setAttribute(name, value ? "true" : "false");
}

export function installLuminaUmami(): LuminaUmamiConfig {
  const config = resolveLuminaUmamiConfig();
  if (
    !config.enabled ||
    typeof document === "undefined" ||
    document.getElementById(SCRIPT_ELEMENT_ID)
  ) {
    return config;
  }

  const script = document.createElement("script");
  script.id = SCRIPT_ELEMENT_ID;
  script.async = true;
  script.defer = true;
  script.src = config.scriptUrl;
  script.setAttribute("data-website-id", config.websiteId);
  if (config.hostUrl) {
    script.setAttribute("data-host-url", config.hostUrl);
  }
  if (config.tag) {
    script.setAttribute("data-tag", config.tag);
  }
  if (config.domains.length > 0) {
    script.setAttribute("data-domains", config.domains.join(","));
  }
  setBooleanDataAttribute(script, "data-do-not-track", config.doNotTrack);
  setBooleanDataAttribute(script, "data-exclude-search", config.excludeSearch);
  setBooleanDataAttribute(script, "data-exclude-hash", config.excludeHash);
  setBooleanDataAttribute(script, "data-performance", config.performance);
  script.addEventListener("load", flushPendingLuminaEvents);

  document.head.appendChild(script);
  return config;
}

function getDeploymentTag(): string | null {
  return resolveLuminaUmamiConfig().tag;
}

function sanitizePayload(
  payload: LuminaAnalyticsPayload = {},
): Record<string, string | number | boolean | null> {
  const sanitized: Record<string, string | number | boolean | null> = {};
  for (const [key, value] of Object.entries(payload).slice(0, MAX_PAYLOAD_KEYS)) {
    if (BLOCKED_KEY_PATTERN.test(key) || value === undefined) {
      continue;
    }
    if (typeof value === "string") {
      sanitized[key] =
        value.length > MAX_STRING_LENGTH
          ? `${value.slice(0, MAX_STRING_LENGTH)}...`
          : value;
      continue;
    }
    if (typeof value === "number") {
      sanitized[key] = Number.isFinite(value) ? value : null;
      continue;
    }
    if (typeof value === "boolean" || value === null) {
      sanitized[key] = value;
    }
  }
  return sanitized;
}

export function getLuminaAnalyticsBasePayload(): LuminaAnalyticsPayload {
  return {
    app_version:
      typeof __LUMINA_VERSION__ === "string" ? __LUMINA_VERSION__ : "0.0.0",
    deployment_tag: getDeploymentTag(),
    hostname: typeof window === "undefined" ? null : window.location.hostname,
  };
}

export function trackLuminaEvent(
  eventName: string,
  payload: LuminaAnalyticsPayload = {},
): void {
  const config = resolveLuminaUmamiConfig();
  if (!config.enabled || typeof window === "undefined") {
    return;
  }
  const safeName = eventName.slice(0, MAX_EVENT_NAME_LENGTH);
  const safePayload = sanitizePayload({
    ...getLuminaAnalyticsBasePayload(),
    ...payload,
  });
  const track = (window as UmamiWindow).umami?.track;
  if (typeof track !== "function") {
    pendingEvents.push({ eventName: safeName, payload: safePayload });
    if (pendingEvents.length > MAX_PENDING_EVENTS) {
      pendingEvents.splice(0, pendingEvents.length - MAX_PENDING_EVENTS);
    }
    return;
  }
  track(safeName, safePayload);
}

function flushPendingLuminaEvents(): void {
  if (typeof window === "undefined") {
    return;
  }
  const track = (window as UmamiWindow).umami?.track;
  if (typeof track !== "function") {
    return;
  }
  const events = pendingEvents.splice(0);
  for (const event of events) {
    track(event.eventName, event.payload);
  }
}
