import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../hooks/useTheme'
import styles from './ThemeToggle.module.css'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isLight = theme === 'light'

  return (
    <button
      type="button"
      className={styles.toggle}
      onClick={toggle}
      aria-label={isLight ? 'Switch to dark theme' : 'Switch to light theme'}
      title={isLight ? 'Switch to dark theme' : 'Switch to light theme'}
    >
      {isLight ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </button>
  )
}
