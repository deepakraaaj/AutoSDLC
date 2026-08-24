import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import styles from './Modal.module.css'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

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
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    // Whatever was focused when this opened — usually the button that opened it.
    // Focus goes back there on close, so keyboard users aren't dumped at the top
    // of the document with no idea where they were.
    const previouslyFocused = document.activeElement as HTMLElement | null

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !closeDisabled) {
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      // Keep Tab inside the dialog. Without this, tabbing walks out of the modal
      // and into the page behind it, which is still visible under the overlay but
      // not meant to be reachable — a screen-reader user can end up operating the
      // page they think they've covered up.
      const focusable = Array.from(contentRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || !contentRef.current?.contains(active))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKey)
    // Move focus in on open, preferring the first real control over the close
    // button so the dialog opens where the work is.
    const target =
      contentRef.current?.querySelector<HTMLElement>(
        'input:not([disabled]), textarea:not([disabled]), select:not([disabled])',
      ) ?? contentRef.current
    target?.focus()

    return () => {
      document.removeEventListener('keydown', onKey)
      previouslyFocused?.focus?.()
    }
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
      <div
        className={styles.content}
        onClick={(e) => e.stopPropagation()}
        ref={contentRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
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
