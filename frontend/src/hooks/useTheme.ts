import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'autosdlc-theme'

/** index.html has an inline script that sets documentElement's data-theme
 * attribute before first paint (avoids a flash of the wrong theme) — this
 * just reads whatever it already decided, then keeps it in sync on toggle. */
function getInitialTheme(): Theme {
  const attr = document.documentElement.dataset.theme
  if (attr === 'light' || attr === 'dark') return attr
  // Light is the default: dark is opt-in, either explicitly or by system setting.
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // localStorage can throw in locked-down environments (private mode,
      // storage quota) — theme still works for the session, just doesn't persist.
    }
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, toggle }
}
