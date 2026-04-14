export const DEFAULT_DEV_HOST = "0.0.0.0";
export const DEFAULT_DEV_PORT = 4174;

interface DevServerEnv {
  VITE_DEV_HOST?: string;
  VITE_DEV_PORT?: string;
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

export function resolveDevServerConfig(env: DevServerEnv) {
  return {
    host: env.VITE_DEV_HOST?.trim() || DEFAULT_DEV_HOST,
    port: parsePort(env.VITE_DEV_PORT) ?? DEFAULT_DEV_PORT,
    strictPort: true,
  };
}
