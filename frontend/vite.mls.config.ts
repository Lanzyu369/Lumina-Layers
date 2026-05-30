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
  optimizeDeps: {
    include: ["qrcode"],
  },
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
