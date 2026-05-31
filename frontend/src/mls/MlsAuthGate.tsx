/**
 * MlsAuthGate — entry-time gate for the MLS frontend.
 * MlsAuthGate — MLS 前端的入口门禁。
 *
 * The first time the MLS app boots in a tab it asks the backend whether a
 * write password is configured. When it is, the user gets a dialog with two
 * choices:
 *
 * - Enter the password, unlocking write mode (create / edit / delete).
 * - Enter read-only mode, where the UI loads normally but every write
 *   action is hidden or disabled.
 *
 * 首次启动时，先向后端拉取「是否配置写入密码」。若已配置，弹出对话框二选一：
 *
 * - 输入密码，解锁写入模式（新增 / 修改 / 删除）。
 * - 进入只读模式，界面正常加载但隐藏或禁用所有写操作。
 *
 * The dialog is dismissible only by choosing one of the two options. After
 * the choice is made the gate auto-disappears; users can re-open it later
 * via a header button so they can switch from read-only to write at any
 * time without reloading the page.
 *
 * 对话框只能通过两个选项之一关闭；之后通过 header 按钮可随时再次打开，无需刷新
 * 页面即可从只读切换到写入。
 */
import { useEffect, useState, type ReactElement } from "react";
import { useI18n } from "../i18n/context";
import { useMlsAuthStore } from "../stores/mlsAuthStore";
import { fetchMlsAuthStatus, verifyMlsPassword } from "../api/mlsAuth";

interface MlsAuthGateProps {
  /** Whether the gate dialog is currently shown. (是否当前显示门禁对话框) */
  open: boolean;
  /** Called when the user chooses read-only mode or unlocks successfully.
   * (用户选择只读 或 成功解锁后调用) */
  onClose: () => void;
}

/**
 * Boot-time + on-demand password dialog for the MLS frontend.
 * MLS 前端启动时与按需调用的密码对话框。
 */
export function MlsAuthGate({ open, onClose }: MlsAuthGateProps): ReactElement | null {
  const { t } = useI18n();
  const setPassword = useMlsAuthStore((s) => s.setPassword);
  const clearPassword = useMlsAuthStore((s) => s.clearPassword);
  const setStatus = useMlsAuthStore((s) => s.setStatus);
  // Defence in depth: even if a caller mistakenly opens the gate when no
  // password is configured on the server, refuse to render the dialog. The
  // user is treated as already authenticated (writes succeed; verify endpoint
  // would just return ok=true). This complements the boot guard in MlsApp
  // and makes the invariant impossible to bypass via future code paths.
  // 纵深防御：即便上游错误地在服务端无密码时打开门禁，本组件也拒绝渲染，使
  // 「未配置密码 == 用户已通过认证」的不变量在任何调用路径下都成立。
  const passwordRequired = useMlsAuthStore((s) => s.passwordRequired);

  const [candidate, setCandidate] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      setCandidate("");
      setErrorMsg(null);
      setSubmitting(false);
    }
  }, [open]);

  if (!open || !passwordRequired) {
    return null;
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (!candidate) {
      setErrorMsg(t("mls.auth.error_empty"));
      return;
    }
    setSubmitting(true);
    setErrorMsg(null);
    try {
      // Stash the candidate first so the verify request itself carries it
      // via the shared axios interceptor; this matches every other write
      // request and avoids a separate code path.
      // 先把候选密码存入 store，让校验请求也通过共享 axios 拦截器携带，避免额外
      // 代码路径与所有写请求保持一致。
      setPassword(candidate);
      const result = await verifyMlsPassword(candidate);
      if (result.ok) {
        setStatus(true, true);
        onClose();
      } else {
        clearPassword();
        setStatus(true, false);
        setErrorMsg(t("mls.auth.error_wrong"));
      }
    } catch {
      clearPassword();
      setErrorMsg(t("mls.auth.error_network"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleReadOnly = async (): Promise<void> => {
    clearPassword();
    try {
      const status = await fetchMlsAuthStatus();
      setStatus(status.password_required, status.write_enabled);
    } catch {
      setStatus(true, false);
    }
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-slate-900/40 backdrop-blur-sm dark:bg-slate-950/60"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mls-auth-gate-title"
    >
      <form
        onSubmit={handleSubmit}
        className="grid w-full max-w-sm gap-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-900"
      >
        <header className="grid gap-1">
          <h2
            id="mls-auth-gate-title"
            className="text-lg font-semibold text-slate-900 dark:text-slate-50"
          >
            {t("mls.auth.title")}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("mls.auth.description")}
          </p>
        </header>
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-slate-700 dark:text-slate-200">
            {t("mls.auth.password_label")}
          </span>
          <input
            type="password"
            autoFocus
            autoComplete="current-password"
            value={candidate}
            onChange={(e) => setCandidate(e.target.value)}
            disabled={submitting}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-50"
            placeholder={t("mls.auth.password_placeholder")}
          />
        </label>
        {errorMsg && (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {errorMsg}
          </p>
        )}
        <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={handleReadOnly}
            disabled={submitting}
            className="rounded-md border border-slate-300 bg-transparent px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-60 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {t("mls.auth.enter_read_only")}
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-60"
          >
            {submitting ? t("mls.auth.unlocking") : t("mls.auth.unlock")}
          </button>
        </div>
      </form>
    </div>
  );
}

export default MlsAuthGate;
