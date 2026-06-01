import axios from "axios";
import { useSettingsStore, MLS_DEFAULT_BACKEND_URL } from "../stores/settingsStore";
import { getMlsPassword } from "../stores/mlsAuthStore";

/**
 * Axios instance targeting the standalone Material-LUT Studio (MLS) backend.
 * 指向独立 Material-LUT Studio (MLS) 后端的 axios 实例。
 *
 * Route B / 做法一: the converter runs on a separate server from MLS, so the
 * few material-archive helpers the converter still needs at runtime (solver
 * cache status/build/delete and color suggestions) call the MLS backend API
 * directly rather than the main app. The base URL is read from the
 * user-configured ``mlsBackendUrl`` setting (defaults to
 * ``MLS_DEFAULT_BACKEND_URL``, :8100); the MLS endpoints live under
 * ``/api/mls/...``.
 *
 * 转换器与 MLS 部署在不同服务器，转换器运行时仍需的少量耗材档案能力（求解
 * 缓存状态/构建/删除、取色建议）直接调 MLS 后端 API。基地址取用户在设置中配置
 * 的 ``mlsBackendUrl``（默认 ``MLS_DEFAULT_BACKEND_URL``，即 :8100）。
 *
 * Auth: every request is auto-decorated with the cached MLS write password
 * via the ``X-MLS-Password`` header (when present). Read-only requests are
 * unaffected by an empty / wrong password; mutating requests are rejected by
 * the MLS backend with HTTP 401 when the password is missing or wrong.
 *
 * 鉴权：每次请求自动注入缓存的 MLS 写入密码（``X-MLS-Password`` 头）。空 /
 * 错密码不影响只读请求；写请求由 MLS 后端在缺失或错误时返回 401。
 */
const mlsClient = axios.create({ timeout: 3_600_000 });

mlsClient.interceptors.request.use((config) => {
  const base = (useSettingsStore.getState().mlsBackendUrl || MLS_DEFAULT_BACKEND_URL).replace(/\/+$/, "");
  config.baseURL = base;
  const password = getMlsPassword();
  if (password) {
    config.headers = config.headers ?? {};
    // axios v1 headers object is AxiosHeaders or plain dict; setting either way
    // works because AxiosHeaders.set is invoked under the hood.
    // axios v1 的 headers 既可能是 AxiosHeaders 也可能是普通对象，直接赋值兼容。
    (config.headers as Record<string, string>)["X-MLS-Password"] = password;
  }
  return config;
});

export default mlsClient;
