import axios from "axios";

/**
 * Axios 实例，统一管理 MLS API 请求基础配置。
 *
 * baseURL 默认 ``/api``，由 Vite 代理转发到 MLS 后端 (:8100)。
 * 不设置默认 Content-Type，让 axios 对 JSON / FormData 自动协商，
 * 避免 FormData 的 boundary 丢失导致后端 422。
 */
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
  timeout: 3_600_000,
});

export default apiClient;
