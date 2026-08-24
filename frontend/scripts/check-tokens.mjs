/*
 * Fails the build if any CSS references a custom property that nothing ever
 * declares. An undefined var() is invalid at computed-value time, which drops
 * the *whole* declaration silently — `padding: var(--space-7) 32px 64px` with
 * no --space-7 doesn't fall back to 32px, it removes the padding entirely.
 * That is exactly how the backlog page ended up flush against the viewport
 * edge and the Scorecard's fix-progress bar ended up with no fill colour, and
 * nothing in tsc, vite, or oxlint says a word about it.
 *
 * Run: node scripts/check-tokens.mjs   (wired into `npm run build`)
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('../src', import.meta.url))

/** Properties consumed from outside our stylesheets, so a declaration is not
 * expected: browser-defined, or set inline from JS via a style prop. */
const EXTERNALLY_DEFINED = new Set([
  '--nav-count', // Sidebar.tsx sets this per-render from NAV.length
])

function cssFiles(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) return cssFiles(path)
    return path.endsWith('.css') ? [path] : []
  })
}

const files = cssFiles(SRC)
const declared = new Set(EXTERNALLY_DEFINED)
/** name -> "file:line" of every var() that reads it, for the error message. */
const referenced = new Map()

for (const file of files) {
  const lines = readFileSync(file, 'utf8').split('\n')
  lines.forEach((line, index) => {
    // A declaration: `--x: value`. Anything before a ':' that isn't inside a
    // var() call — var(--x, fallback) has a comma, not a colon, so no overlap.
    for (const match of line.matchAll(/(^|[;{])\s*(--[a-zA-Z0-9-]+)\s*:/g)) {
      declared.add(match[2])
    }
    for (const match of line.matchAll(/var\(\s*(--[a-zA-Z0-9-]+)/g)) {
      const name = match[1]
      if (!referenced.has(name)) {
        referenced.set(name, `${relative(SRC, file)}:${index + 1}`)
      }
    }
  })
}

const undefinedTokens = [...referenced.keys()].filter((name) => !declared.has(name)).sort()

if (undefinedTokens.length > 0) {
  console.error(`\nUndefined CSS custom ${undefinedTokens.length === 1 ? 'property' : 'properties'}:\n`)
  for (const name of undefinedTokens) {
    console.error(`  ${name}  — first used at src/${referenced.get(name)}`)
  }
  console.error(
    '\nDeclare it in src/styles/tokens.css, or fix the name. An undefined var()\n' +
      'silently voids the entire declaration that contains it.\n',
  )
  process.exit(1)
}

console.log(`check-tokens: ${referenced.size} custom properties referenced, all declared.`)
