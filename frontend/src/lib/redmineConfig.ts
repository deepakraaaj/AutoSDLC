/** Shared Redmine connection details for this browser tab. Credentials deliberately
 * use sessionStorage rather than long-lived localStorage, limiting exposure after the
 * tab/session closes. Server-side encrypted credentials replace this once authentication
 * and per-user ownership are introduced. */
export interface SavedRedmineConfig {
  url: string
  key: string
  project: string
}

const STORAGE_KEY = 'redmine-config'

export function getSavedRedmineConfig(): SavedRedmineConfig {
  try {
    // One-time migration: remove credentials older builds persisted indefinitely.
    localStorage.removeItem(STORAGE_KEY)
    const saved = sessionStorage.getItem(STORAGE_KEY)
    if (!saved) return { url: '', key: '', project: '' }
    const c = JSON.parse(saved)
    return { url: c.url || '', key: c.key || '', project: c.project || '' }
  } catch {
    return { url: '', key: '', project: '' }
  }
}

export function saveRedmineConfig(c: SavedRedmineConfig) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(c))
}
