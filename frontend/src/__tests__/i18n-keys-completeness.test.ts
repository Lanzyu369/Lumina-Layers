import { describe, it, expect } from "vitest"
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative } from "node:path"
import { translations } from "../i18n/translations"

const SRC_ROOT = join(process.cwd(), "src")

function collectSourceFiles(dir: string): string[] {
  const items = readdirSync(dir)
  const result: string[] = []

  for (const item of items) {
    const fullPath = join(dir, item)
    const stat = statSync(fullPath)
    if (stat.isDirectory()) {
      if (item === "__tests__" || item === "i18n" || item === "theme") {
        continue
      }
      result.push(...collectSourceFiles(fullPath))
      continue
    }

    if (!/\.(ts|tsx)$/.test(item)) continue
    if (item.endsWith(".test.ts") || item.endsWith(".test.tsx")) continue
    if (item.endsWith(".property.test.ts") || item.endsWith(".property.test.tsx")) continue

    result.push(fullPath)
  }

  return result
}

describe("i18n key completeness", () => {
  it("all literal t(\"...\") and tRuntime(\"...\") keys referenced in source exist in translations", () => {
    const keyRegex = /\b(?:t|tRuntime)\(\s*["'`]([^"'`]+)["'`]\s*[,)]/g
    const knownKeys = new Set(Object.keys(translations))
    const missing: Array<{ key: string; file: string }> = []

    for (const filePath of collectSourceFiles(SRC_ROOT)) {
      const text = readFileSync(filePath, "utf8")
      const matches = text.matchAll(keyRegex)

      for (const match of matches) {
        const key = match[1]
        if (key.includes("${")) {
          continue
        }
        if (!knownKeys.has(key)) {
          missing.push({ key, file: relative(SRC_ROOT, filePath) })
        }
      }
    }

    expect(missing).toEqual([])
  })
})

