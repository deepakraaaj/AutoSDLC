import { useEffect, type ReactNode } from 'react'
import styles from './Modal.module.css'

export function Modal({
  open,
  onClose,
  title,
  subheader,
  children,
  closeDisabled = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  subheader?: string
  children: ReactNode
  closeDisabled?: boolean
}) {
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !closeDisabled) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose, closeDisabled])

  if (!open) return null

  return (
    <div className={styles.overlay} onClick={() => !closeDisabled && onClose()}>
      <div className={styles.content} onClick={(e) => e.stopPropagation()}>
        <button className={styles.close} onClick={onClose} disabled={closeDisabled} aria-label="Close">
          ✕
        </button>
        <div className={styles.header}>{title}</div>
        {subheader && <div className={styles.subheader}>{subheader}</div>}
        {children}
      </div>
    </div>
  )
}
