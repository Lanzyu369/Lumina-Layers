import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'fs'
import { resolveDevServerConfig } from './devServerConfig'

const pkg = JSON.parse(readFileSync('./package.json', 'utf-8'))

// https://vite.dev/config/
export default defineConfig({
  define: {
    __LUMINA_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [react()],
  // Pre-bundle every external npm dependency the app uses, eagerly. Vite's
  // dep optimizer normally auto-scans entry files for imports, but the
  // discovery order and even the discovered set can vary between starts
  // (especially after the dev-server is restarted while a browser tab is
  // still open with the previous hash). When that happens the browser
  // requests files like ``@dnd-kit_core.js?v=<old hash>`` which no longer
  // exist in the freshly-pre-bundled deps directory — Vite returns 504 or
  // its SPA HTML fallback, the page goes blank.
  //
  // Listing every dep explicitly forces a stable, complete pre-bundle on
  // every cold start: every entry below appears in ``deps/_metadata.json``
  // regardless of scan order, so a refresh after a restart finds the file
  // it expects. This list mirrors what the auto-scanner currently
  // discovers; keep it in sync when adding a new top-level npm dep
  // (everything ``import``ed from a non-relative path that isn't
  // ``./*``/``../*``).
  //
  // 把应用使用的每个外部 npm 依赖都显式登记，强制每次冷启动都稳定地全量预打包。
  // Vite 默认的依赖扫描器在不同启动之间可能产生不同的依赖顺序甚至漏扫，导致
  // 旧浏览器标签按旧 hash 请求的文件在新 deps 目录里不存在，触发 504 / SPA
  // HTML 兜底 → 白屏。把每条 dep 列出可彻底消除这一不确定性。
  optimizeDeps: {
    include: [
      "@dnd-kit/core",
      "@floating-ui/react",
      "@react-three/drei",
      "@react-three/fiber",
      "axios",
      "framer-motion",
      "qrcode",
      "react",
      "react-cropper",
      "react-dom",
      "react-dom/client",
      "react/jsx-dev-runtime",
      "react/jsx-runtime",
      "read-excel-file/browser",
      "three",
      "zustand",
      "zustand/middleware",
      "zustand/react/shallow",
    ],
  },
  // Isolate the converter app's pre-bundle cache from the MLS entry
  // (``vite.mls.config.ts`` writes to ``node_modules/.vite-mls``). They
  // share the same project files but discover different entry trees, so a
  // shared cache dir means restarting one scrambles the other's
  // ``deps/_metadata.json`` and triggers white-screens in the live tab.
  // 把转换器应用的预打包缓存与 MLS 入口隔开（MLS 写到 ``.vite-mls``）；两者共享
  // 工程文件但入口树不同，共用缓存目录会导致一边重启时弄乱另一边的
  // ``deps/_metadata.json``，触发活动标签白屏。
  cacheDir: "node_modules/.vite",
  server: {
    ...resolveDevServerConfig(process.env),
    allowedHosts: ["online.luminastudio.com.cn"],
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
    // Memory cap: bound fork pool to avoid runaway memory when multiple
    // vitest invocations stack up (especially from concurrent agent calls).
    // Default would be `maxForks = CPU count` (~10 workers * ~1GB each).
    // Override via env LUMINA_VITEST_MAX_FORKS if a release sweep needs more.
    pool: "forks",
    maxWorkers: Number(process.env.LUMINA_VITEST_MAX_FORKS ?? 2),
  },
})
