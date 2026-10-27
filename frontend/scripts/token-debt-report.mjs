import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"

const SRC_ROOT = join(process.cwd(), "src")

const colorPattern = /(?:bg-white|text-black|#[0-9a-fA-F]{3,8}\b|rgba?\s*\()/g
const textPattern = /<[^>]+>\s*([A-Za-z\u4E00-\u9FFF][^<]*)\s*<\//g

function walk(dir) {
  const files = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const stat = statSync(full)
    if (stat.isDirectory()) {
      if (["__tests__", "i18n", "theme"].includes(entry)) continue
      files.push(...walk(full))
      continue
    }
    if (/\.(ts|tsx)$/.test(entry)) files.push(full)
  }
  return files
}

const files = walk(SRC_ROOT)
let colorHits = 0
let textHits = 0

for (const file of files) {
  const content = readFileSync(file, "utf8")
  colorHits += [...content.matchAll(colorPattern)].length
  textHits += [...content.matchAll(textPattern)].length
}

console.log("[token-debt] raw-color-hits=", colorHits)
console.log("[token-debt] hardcoded-text-hits=", textHits)

