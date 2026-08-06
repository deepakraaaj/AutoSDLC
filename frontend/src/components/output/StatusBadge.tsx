import { useEffect, useRef, useState } from 'react'
import styles from './StatusBadge.module.css'

/** Interactive when a dbId is present (persists via the API on change);
 * otherwise a plain read-only badge — honest about what will and won't
 * actually save, instead of looking editable and silently not persisting. */
export function StatusBadge({
  status,
  options,
  onChange,
}: {
  status: string
  options: string[]
  onChange: (next: string) => void | Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [open])

  return (
    <div className={styles.wrap} ref={ref}>
      <button
        type="button"
        className={`badge badge-status status-${status} ${styles.trigger}`}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
      >
        {status} ▾
      </button>
      {open && (
        <div className={styles.dropdown} onClick={(e) => e.stopPropagation()}>
          {options.map((opt) => (
            <div
              key={opt}
              className={styles.item}
              onClick={() => {
                setOpen(false)
                void onChange(opt)
              }}
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function StaticStatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-status status-${status} ${styles.static}`}>{status}</span>
}
