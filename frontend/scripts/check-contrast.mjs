/*
 * Checks the colour pairs the UI actually renders against WCAG AA.
 *
 * The palette drifted once already: --text-tertiary sat at #6b7280 on
 * --bg-surface #11151b, about 4.0:1, and it carries taglines, hints, counts and
 * the provider status line — i.e. a lot of the small text in the app. Nothing
 * catches that by eye, so it is checked here instead.
 *
 * Run: node scripts/check-contrast.mjs   (wired into `npm run build`)
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const TOKENS = fileURLToPath(new URL('../src/styles/tokens.css', import.meta.url))

/** AA: 4.5 for body text, 3.0 for large text (18.66px bold / 24px) and for
 * non-text boundaries like borders and focus rings. */
const AA_TEXT = 4.5
const AA_LARGE = 3.0

/** [foreground, background, minimum, what it is] */
const PAIRS = [
  ['--text-primary', '--bg-canvas', AA_TEXT, 'body text on the page'],
  ['--text-primary', '--bg-surface', AA_TEXT, 'body text on a panel'],
  ['--text-secondary', '--bg-surface', AA_TEXT, 'secondary text on a panel'],
  ['--text-secondary', '--bg-canvas', AA_TEXT, 'secondary text on the page'],
  ['--text-tertiary', '--bg-surface', AA_TEXT, 'hints, counts, status line'],
  ['--text-tertiary', '--bg-canvas', AA_TEXT, 'hints on the page'],
  ['--text-tertiary', '--bg-surface-raised', AA_TEXT, 'hints on a raised panel'],
  ['--accent', '--bg-surface', AA_TEXT, 'links and accent text on a panel'],
  ['--accent', '--bg-canvas', AA_TEXT, 'links and accent text on the page'],
  ['--text-on-accent', '--accent', AA_TEXT, 'primary button label'],
  ['--success', '--bg-surface', AA_LARGE, 'success indicator'],
  ['--warning', '--bg-surface', AA_LARGE, 'warning indicator'],
  ['--danger', '--bg-surface', AA_LARGE, 'danger indicator'],
  ['--info', '--bg-surface', AA_LARGE, 'info indicator'],
  ['--border-default', '--bg-surface', 1.4, 'panel border visibility'],
]

function parseThemes(css) {
  // Two blocks: the base one (also tagged [data-theme='dark'] or ['light'])
  // and the explicit override for the other theme. Match on the selector text
  // rather than order so a reordering of the file doesn't silently swap them.
  const blocks = [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)]
  const themes = { light: {}, dark: {} }
  for (const [, selector, body] of blocks) {
    if (!selector.includes(':root')) continue
    const targets = []
    if (selector.includes("data-theme='dark'")) targets.push('dark')
    if (selector.includes("data-theme='light'")) targets.push('light')
    // A bare `:root` (or a `:root` grouped with one theme) also seeds whichever
    // theme is the default, plus the shared non-colour tokens at the end.
    if (targets.length === 0) targets.push('light', 'dark')
    for (const [, name, value] of body.matchAll(/(--[a-zA-Z0-9-]+)\s*:\s*([^;]+);/g)) {
      for (const t of targets) if (!(name in themes[t]) || targets.length === 1) themes[t][name] = value.trim()
    }
  }
  return themes
}

function toRgb(value) {
  const hex = /^#([0-9a-f]{6})$/i.exec(value)
  if (hex) {
    const n = parseInt(hex[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const short = /^#([0-9a-f]{3})$/i.exec(value)
  if (short) {
    const [r, g, b] = short[1].split('')
    return [parseInt(r + r, 16), parseInt(g + g, 16), parseInt(b + b, 16)]
  }
  return null // rgba()/gradients/color-mix — not a flat colour, nothing to check
}

function luminance([r, g, b]) {
  const channel = (c) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

function ratio(fg, bg) {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x)
  return (a + 0.05) / (b + 0.05)
}

const themes = parseThemes(readFileSync(TOKENS, 'utf8'))
const failures = []
let checked = 0

for (const theme of ['light', 'dark']) {
  for (const [fgName, bgName, min, label] of PAIRS) {
    const fg = toRgb(themes[theme][fgName] ?? '')
    const bg = toRgb(themes[theme][bgName] ?? '')
    if (!fg || !bg) continue
    checked += 1
    const r = ratio(fg, bg)
    if (r < min) {
      failures.push(
        `  ${theme.padEnd(5)} ${fgName} on ${bgName}  ${r.toFixed(2)}:1  (needs ${min}:1) — ${label}`,
      )
    }
  }
}

if (failures.length > 0) {
  console.error(`\nContrast below target in ${failures.length} pair(s):\n`)
  console.error(failures.join('\n'))
  console.error('\nAdjust the token in src/styles/tokens.css.\n')
  process.exit(1)
}

console.log(`check-contrast: ${checked} colour pairs checked, all at or above target.`)
