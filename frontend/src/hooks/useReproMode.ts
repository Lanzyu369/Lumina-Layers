/**
 * Detect whether the frontend is running in reproduction mode.
 * 判断前端是否运行在"复现模式"。
 *
 * When a developer has already run ``python scripts/load_bug_repro.py
 * <ticket_id>`` they open the frontend at
 * ``http://localhost:5174/?repro_session=<ticket_id>`` so they can tell
 * at a glance that they are looking at a reproduction run, not a normal
 * user session. This hook does the URL check once at mount and caches
 * the result; we intentionally do NOT tap into converter/singleStage
 * stores here to avoid any auto-loading behaviour — loading reproduction
 * assets is still a deliberate user action.
 *
 * 开发者跑过 ``load_bug_repro.py`` 后通过 URL query ``?repro_session=<id>``
 * 打开前端，就能在界面上看到「复现模式」提示，避免误把复现当作普通会话；
 * 本 hook 只做标识，不触发任何自动加载。
 */

import { useMemo } from "react";

export interface ReproModeState {
  enabled: boolean;
  ticketId: string | null;
}

export function useReproMode(): ReproModeState {
  return useMemo(() => {
    if (typeof window === "undefined") {
      return { enabled: false, ticketId: null };
    }
    try {
      const ticket = new URL(window.location.href).searchParams.get(
        "repro_session",
      );
      if (!ticket) {
        return { enabled: false, ticketId: null };
      }
      return { enabled: true, ticketId: ticket };
    } catch {
      // Malformed URL shouldn't crash bootstrap.
      // 非法 URL 不应阻塞 app 启动。
      return { enabled: false, ticketId: null };
    }
  }, []);
}
