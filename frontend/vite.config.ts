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
  },
})
