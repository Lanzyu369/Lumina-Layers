type DevLogArgs = readonly unknown[];
type DevConsoleMethod = "log" | "debug" | "warn" | "time" | "timeLog" | "timeEnd";

function isDevLogEnabled(): boolean {
  return import.meta.env.DEV;
}

function callDevConsole(method: DevConsoleMethod, args: DevLogArgs): void {
  if (!isDevLogEnabled()) {
    return;
  }

  const targetConsole = globalThis["console"] as
    | (Console & Record<DevConsoleMethod, (...args: unknown[]) => void>)
    | undefined;
  const logger = targetConsole?.[method];
  if (!logger) {
    return;
  }

  logger.apply(targetConsole, [...args]);
}

function callDevTiming(method: "time" | "timeLog" | "timeEnd", args: DevLogArgs): void {
  try {
    callDevConsole(method, args);
  } catch {
    void 0;
  }
}

export const devLog = {
  log: (...args: DevLogArgs): void => {
    callDevConsole("log", args);
  },
  debug: (...args: DevLogArgs): void => {
    callDevConsole("debug", args);
  },
  warn: (...args: DevLogArgs): void => {
    callDevConsole("warn", args);
  },
  timing: {
    start: (label: string): void => {
      callDevTiming("time", [label]);
    },
    mark: (label: string, ...args: DevLogArgs): void => {
      callDevTiming("timeLog", [label, ...args]);
    },
    end: (label: string): void => {
      callDevTiming("timeEnd", [label]);
    },
  },
};

export const debug = devLog.debug;
export const timing = devLog.timing;
