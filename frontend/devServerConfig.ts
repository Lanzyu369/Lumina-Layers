export const DEFAULT_DEV_HOST = "0.0.0.0";
export const DEFAULT_DEV_PORT = 4174;
export const DEFAULT_API_PROXY_TARGET = "http://localhost:8000";
export const DEFAULT_ALLOWED_HOSTS = ["online.luminastudio.com.cn"] as const;

interface DevServerEnv {
  PORT?: string;
  VITE_DEV_HOST?: string;
  VITE_DEV_PORT?: string;
  VITE_API_PROXY_TARGET?: string;
  VITE_ALLOWED_HOSTS?: string;
}

function parsePort(rawPort: string | undefined): number | null {
  if (!rawPort) {
    return null;
  }

  const parsed = Number(rawPort);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    return null;
  }

  return parsed;
}

function parseAllowedHosts(rawHosts: string | undefined): string[] {
  const extras = (rawHosts ?? "")
    .split(",")
    .map((host) => host.trim())
    .filter((host) => host.length > 0);
  return Array.from(new Set([...DEFAULT_ALLOWED_HOSTS, ...extras]));
}

export function resolveDevServerConfig(env: DevServerEnv) {
  return {
    host: env.VITE_DEV_HOST?.trim() || DEFAULT_DEV_HOST,
    port: parsePort(env.PORT) ?? parsePort(env.VITE_DEV_PORT) ?? DEFAULT_DEV_PORT,
    strictPort: true,
    allowedHosts: parseAllowedHosts(env.VITE_ALLOWED_HOSTS),
  };
}

export function resolveApiProxyTarget(env: DevServerEnv): string {
  return env.VITE_API_PROXY_TARGET?.trim() || DEFAULT_API_PROXY_TARGET;
}
