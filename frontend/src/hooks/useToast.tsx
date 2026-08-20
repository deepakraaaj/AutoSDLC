/* oxlint-disable react/only-export-components -- context provider and hook share one public module */
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import type { ToastSeverity } from '../types'
import styles from './useToast.module.css'

interface ToastItem {
  id: number
  title: string
  message: string
  severity: ToastSeverity
}

interface ToastContextValue {
  showToast: (title: string, message: string, severity?: ToastSeverity) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const AUTO_DISMISS_MS: Record<ToastSeverity, number> = {
  info: 3000,
  warning: 6000,
  error: 8000,
  critical: 0,
}

const ICONS: Record<ToastSeverity, string> = {
  info: 'ℹ',
  warning: '⚠',
  error: '✕',
  critical: '⚠',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(0)

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const showToast = useCallback(
    (title: string, message: string, severity: ToastSeverity = 'info') => {
      const id = nextId.current++
      setToasts((prev) => [...prev, { id, title, message, severity }])
      const delay = AUTO_DISMISS_MS[severity]
      if (delay > 0) {
        setTimeout(() => dismiss(id), delay)
      }
    },
    [dismiss],
  )

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className={styles.container} role="region" aria-label="Notifications">
        {toasts.map((t) => (
          <div key={t.id} className={`${styles.toast} ${styles[t.severity]}`} role="status">
            <div className={styles.icon} aria-hidden="true">
              {ICONS[t.severity]}
            </div>
            <div className={styles.content}>
              <div className={styles.title}>{t.title}</div>
              <div className={styles.message}>{t.message}</div>
            </div>
            <button
              className={styles.close}
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}
