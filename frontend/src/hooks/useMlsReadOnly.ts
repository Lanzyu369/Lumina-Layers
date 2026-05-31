import { useMlsAuthStore } from "../stores/mlsAuthStore";

/**
 * React hook returning ``true`` when the MLS app is in read-only mode.
 * 当 MLS 应用处于只读模式时返回 ``true`` 的 React Hook。
 *
 * Read-only is the combination of:
 *   - the auth status check has resolved (``ready``)
 *   - the server requires a password (``passwordRequired``)
 *   - the cached password (if any) has not unlocked writes (``!writeEnabled``)
 *
 * 只读判定 = 状态查询完成 ∧ 服务端要求密码 ∧ 当前未解锁写入。
 *
 * In the main converter app this hook always returns ``false`` because the
 * converter never enables the MLS password injection, leaving the auth store
 * in its initial ``passwordRequired=false, writeEnabled=true`` state.
 *
 * 主转换器应用从不启用 MLS 密码注入，store 保持初始的 ``passwordRequired=false,
 * writeEnabled=true``，所以该 Hook 在主应用中永远返回 ``false``，被复用面板
 * 在主应用环境下行为不变。
 */
export function useMlsReadOnly(): boolean {
  const ready = useMlsAuthStore((s) => s.ready);
  const passwordRequired = useMlsAuthStore((s) => s.passwordRequired);
  const writeEnabled = useMlsAuthStore((s) => s.writeEnabled);
  return ready && passwordRequired && !writeEnabled;
}
