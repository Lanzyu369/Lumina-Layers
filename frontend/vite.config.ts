/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
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
    poolOptions: {
      forks: {
        maxForks: Number(process.env.LUMINA_VITEST_MAX_FORKS ?? 2),
        minForks: 1,
      },
    },
  },
})
