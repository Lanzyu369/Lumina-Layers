import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * MLS write-access auth store (frontend-side cache of the entered password
 * and the latest server-reported status).
 *
 * MLS 写入鉴权前端 store：缓存用户输入的密码与服务端最近一次返回的状态。
 *
 * Persistence: only the ``password`` is persisted in ``sessionStorage`` so a
 * page reload during the same browser tab keeps write mode unlocked, while
 * closing the tab forgets the secret. Status flags are derived from the
 * server on each app boot via ``fetchMlsAuthStatus`` and never persisted —
 * the source of truth is always the MLS backend.
 *
 * 持久化：仅密码本身保存到 ``sessionStorage``，刷新页面仍解锁，关闭标签页即遗忘；
 * 状态标志每次启动通过 ``fetchMlsAuthStatus`` 从服务端拉取，不做持久化，事实
 * 来源始终是 MLS 后端。
 */
export interface MlsAuthState {
  /**
   * Candidate password the user typed. Sent on every request as
   * ``X-MLS-Password``; an empty string disables the header entirely.
   * 用户输入的候选密码；每次请求作为 ``X-MLS-Password`` 头发送，空串则不附带。
   */
  password: string;
  /**
   * Whether the server currently requires a password for write operations.
   * 服务端当前是否要求写操作携带密码。
   */
  passwordRequired: boolean;
  /**
   * Whether the current cached password unlocks write operations on the
   * server. ``true`` also when ``passwordRequired === false``.
   * 当前缓存密码是否能解锁服务端写操作；``passwordRequired === false`` 时永真。
   */
  writeEnabled: boolean;
  /**
   * Whether the initial status check has resolved at least once.
   * 首次状态查询是否已完成。
   */
  ready: boolean;
}

export interface MlsAuthActions {
  setPassword: (password: string) => void;
  clearPassword: () => void;
  setStatus: (passwordRequired: boolean, writeEnabled: boolean) => void;
  markReady: () => void;
}

const INITIAL_STATE: MlsAuthState = {
  password: "",
  passwordRequired: false,
  writeEnabled: true,
  ready: false,
};

/**
 * Custom storage that targets ``sessionStorage`` so the secret is forgotten
 * when the browser tab closes. (使用 sessionStorage 让密码在标签页关闭后失效)
 */
const sessionStorageBackend = {
  getItem: (name: string): string | null => {
    try {
      return window.sessionStorage.getItem(name);
    } catch {
      return null;
    }
  },
  setItem: (name: string, value: string): void => {
    try {
      window.sessionStorage.setItem(name, value);
    } catch {
      // sessionStorage may be disabled (private mode); ignore silently.
      // 私有模式下 sessionStorage 可能不可用，静默忽略。
    }
  },
  removeItem: (name: string): void => {
    try {
      window.sessionStorage.removeItem(name);
    } catch {
      // see setItem comment.
    }
  },
};

export const useMlsAuthStore = create<MlsAuthState & MlsAuthActions>()(
  persist(
    (set) => ({
      ...INITIAL_STATE,
      setPassword: (password: string) => set({ password }),
      clearPassword: () => set({ password: "", writeEnabled: false }),
      setStatus: (passwordRequired: boolean, writeEnabled: boolean) =>
        set({ passwordRequired, writeEnabled }),
      markReady: () => set({ ready: true }),
    }),
    {
      name: "lumina-mls-auth",
      storage: {
        getItem: (name) => {
          const raw = sessionStorageBackend.getItem(name);
          return raw ? JSON.parse(raw) : null;
        },
        setItem: (name, value) => {
          sessionStorageBackend.setItem(name, JSON.stringify(value));
        },
        removeItem: (name) => sessionStorageBackend.removeItem(name),
      },
      // Only persist the password — flags must come from the server every boot.
      // 只持久化密码本身，标志位每次启动都从服务端拉取。
      partialize: (state) =>
        ({ password: state.password }) as MlsAuthState & MlsAuthActions,
    },
  ),
);

/**
 * Read-only helper that returns the currently cached password. Safe for use
 * inside axios interceptors (no React subscription).
 *
 * 仅读取当前缓存密码的辅助函数，可在 axios 拦截器中直接调用（不订阅 React）。
 */
export function getMlsPassword(): string {
  return useMlsAuthStore.getState().password;
}
