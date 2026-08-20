import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
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

  // Ported straight to <body> instead of rendering in place. Every modal caller
  // (ProviderModal, RedmineModal, DetailModal, CreateItemModal, EpicProgressMap) is
  // mounted somewhere inside the normal component tree, and this overlay's
  // z-index: 1000 only ranks it *within* whatever stacking context its nearest
  // positioned ancestor happens to establish — it doesn't let it escape and compete
  // above unrelated content elsewhere on the page. That bit Sidebar's own modals
  // specifically: Sidebar is `position: sticky`, so its z-index:1000 modal was capped
  // inside Sidebar's own stacking context, and anything else on the page that later
  // gained its own positioning (e.g. a sticky card in the main content column) could
  // out-paint the whole Sidebar subtree — modal included — by DOM order. A portal
  // sidesteps the whole class of bug: this is never nested inside anything else's
  // stacking context to be trapped in, no matter what else on the page becomes
  // positioned in the future.
  return createPortal(
    <div className={styles.overlay} onClick={() => !closeDisabled && onClose()}>
      <div className={styles.content} onClick={(e) => e.stopPropagation()}>
        <button className={styles.close} onClick={onClose} disabled={closeDisabled} aria-label="Close">
          ✕
        </button>
        <div className={styles.header}>{title}</div>
        {subheader && <div className={styles.subheader}>{subheader}</div>}
        {children}
      </div>
    </div>,
    document.body,
  )
}
