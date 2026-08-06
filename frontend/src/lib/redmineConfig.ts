/** Shared Redmine connection details (URL, API key, selected project), persisted to
 * localStorage. Used by both the Redmine modal and the chat assistant so they read/write
 * the same saved connection instead of each keeping their own copy. */
export interface SavedRedmineConfig {
  url: string
  key: string
  project: string
}

const STORAGE_KEY = 'redmine-config'

export function getSavedRedmineConfig(): SavedRedmineConfig {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) return { url: '', key: '', project: '' }
    const c = JSON.parse(saved)
    return { url: c.url || '', key: c.key || '', project: c.project || '' }
  } catch {
    return { url: '', key: '', project: '' }
  }
}

export function saveRedmineConfig(c: SavedRedmineConfig) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(c))
}
