import mlsClient from "./mlsClient";

/**
 * MLS auth status — does the server require a write password and does the
 * caller currently have it?
 *
 * MLS 鉴权状态——服务端是否要求写入密码、当前调用方是否已携带正确密码。
 */
export interface MlsAuthStatus {
  status: string;
  password_required: boolean;
  write_enabled: boolean;
}

/**
 * MLS password verification result. ``ok`` is true only when the supplied
 * password matched the configured one.
 *
 * MLS 密码校验结果。仅当提供的密码与服务端配置一致时 ``ok`` 为 true。
 */
export interface MlsAuthVerifyResult {
  status: string;
  ok: boolean;
  write_enabled: boolean;
}

/**
 * Fetch the current auth status from the MLS backend. Sends the cached
 * password (if any) so the response also reflects whether the caller can
 * currently perform writes.
 *
 * 从 MLS 后端获取鉴权状态；若已缓存密码也会一并发送，使响应同时反映当前是否
 * 拥有写权限。
 */
export async function fetchMlsAuthStatus(): Promise<MlsAuthStatus> {
  const response = await mlsClient.get<MlsAuthStatus>("/api/mls/auth/status");
  return response.data;
}

/**
 * Verify a candidate password against the MLS backend. The candidate is sent
 * via the ``X-MLS-Password`` header rather than the request body so it
 * matches the same gating rule the rest of the API uses.
 *
 * 用候选密码请求 MLS 后端校验；密码通过 ``X-MLS-Password`` 头发送，与其他写
 * 端点的鉴权方式一致。
 */
export async function verifyMlsPassword(
  candidate: string,
): Promise<MlsAuthVerifyResult> {
  const response = await mlsClient.post<MlsAuthVerifyResult>(
    "/api/mls/auth/verify",
    null,
    {
      headers: { "X-MLS-Password": candidate },
    },
  );
  return response.data;
}
