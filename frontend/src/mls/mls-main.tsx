import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";
import MlsApp from "./MlsApp.tsx";
import { installGlobalClientLogCapture } from "../utils/clientLog.ts";
import { enableApiClientMlsPasswordHeader } from "../api/client.ts";

installGlobalClientLogCapture();
// MLS shares ``apiClient`` (same `/api` axios instance) with the converter
// app, so flip the auth flag here so the cached MLS write password is
// auto-attached to every request the restored panels issue.
// MLS 与转换器共用同一份 apiClient，此处启用密码自动注入，确保被复用面板发出的
// 每次请求都会带上缓存的写入密码。
enableApiClientMlsPasswordHeader();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MlsApp />
  </StrictMode>,
);
