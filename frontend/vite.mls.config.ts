/// <reference types="vite/client" />
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "fs";

const pkg = JSON.parse(readFileSync("./package.json", "utf-8"));

/**
 * Serve ``mls.html`` at the root path during dev.
 * 开发期把根路径 ``/`` 重写到 ``mls.html``。
 *
 * The ``frontend/`` project has two entry HTMLs (``index.html`` for the
 * converter, ``mls.html`` for MLS). Vite's dev server resolves ``/`` to
 * ``index.html`` by default, so without this rewrite opening the MLS base URL
 * (``http://localhost:5180/``) would load the converter. This middleware makes
 * ``/`` serve the MLS entry instead.
 * ``frontend/`` 有两个入口 HTML；Vite 默认把 ``/`` 解析为 ``index.html``，
 * 故需此中间件把根路径改服务 ``mls.html``，否则打开 MLS 基地址会加载转换器。
 */
function serveMlsAtRoot(): Plugin {
  return {
    name: "mls-serve-at-root",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url === "/" || req.url === "/index.html") {
          req.url = "/mls.html";
        }
        next();
      });
    },
  };
}

/**
 * Vite config for the standalone Material-LUT Studio (MLS) frontend.
 * 独立 Material-LUT Studio (MLS) 前端的 Vite 配置。
 *
 * Route B / option A: MLS is a SECOND entry inside the ``frontend/`` project so
 * it shares the whole dependency + component tree with the converter app (zero
 * duplication), yet runs on its own port (:5180) and proxies ``/api`` to the
 * MLS backend (:8100). The entry HTML is ``mls.html`` -> ``src/mls/mls-main.tsx``.
 *
 * 选项 A：MLS 是 ``frontend/`` 项目内的第二个入口，与转换器应用共享整套依赖与
 * 组件树（零重复），但运行在独立端口（:5180），并把 ``/api`` 代理到 MLS 后端
 * （:8100）。入口为 ``mls.html`` → ``src/mls/mls-main.tsx``。
 */
export default defineConfig({
  define: {
    __LUMINA_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [serveMlsAtRoot(), react()],
  // See ``vite.config.ts`` — the MLS entry shares the converter app's whole
  // panel + dependency tree, so it pre-bundles the same set. Listing every
  // dep explicitly avoids the white-screen-after-restart issue caused by
  // Vite's auto-scanner producing different sets between cold starts.
  // 详见 ``vite.config.ts``。MLS 入口与转换器共享整套面板与依赖，预打包同一份。
  // 显式登记可避免冷启动时扫描结果不稳定导致的重启白屏问题。
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
  // Isolate the MLS pre-bundle cache from the converter entry. They share
  // the same project files but the dev servers run independently and would
  // otherwise stomp on each other's ``deps/_metadata.json`` whenever one
  // restarts.
  // 与转换器入口的预打包缓存隔离。两者共享工程文件，但开发服务器独立运行；
  // 共用缓存会让一方重启弄乱另一方的 ``deps/_metadata.json``。
  cacheDir: "node_modules/.vite-mls",
  server: {
    port: 5180,
    strictPort: false,
    proxy: {
      "/api": {
        target: "http://localhost:8100",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist-mls",
    rollupOptions: {
      input: "mls.html",
    },
  },
});
