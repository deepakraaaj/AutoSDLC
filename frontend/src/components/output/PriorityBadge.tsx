import { useEffect, useState } from 'react'
import { priorityTone } from '../../lib/format'
import type { Priority } from '../../types'
import styles from './StatusBadge.module.css'

/** The four values PriorityUpdateRequest accepts (app/schemas/models.py) — anything
 * else is a 422 from the API, so the dropdown must not offer it. */
const PRIORITY_OPTIONS: Priority[] = ['critical', 'high', 'medium', 'low']

/** Interactive when an `onChange` is supplied (the caller passes one only when the
 * row has a dbId to persist against), otherwise a plain read-only badge — the same
 * bargain StatusBadge makes, so a badge never looks editable while silently failing
 * to save.
 *
 * Note the display can be a Redmine priority name while the value being *edited* is
 * always the local/generated priority, so the dropdown ticks the local one and
 * PrioritySourceNote keeps showing it alongside. Without that tick, picking "high"
 * on a badge reading "Urgent" would look like it did nothing. */
export function PriorityBadge({
  priority,
  redmineName,
  onChange,
}: {
  priority: string
  redmineName?: string | null
  onChange?: (next: Priority) => void | Promise<void>
}) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [open])

  const display = redmineName || priority
  if (!display) return null
  const tone = priorityTone(display)
  const title = redmineName
    ? `Redmine priority: ${redmineName}${priority ? ` | Generated priority: ${priority}` : ''}`
    : `Generated priority: ${priority}`

  if (!onChange) {
    return (
      <span className={`badge badge-priority badge-priority-${tone}`} title={title}>
        {display}
      </span>
    )
  }

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={`badge badge-priority badge-priority-${tone} ${styles.trigger}`}
        title={title}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
      >
        {display} ▾
      </button>
      {open && (
        <div className={styles.dropdown} onClick={(e) => e.stopPropagation()}>
          {PRIORITY_OPTIONS.map((opt) => (
            <div
              key={opt}
              className={styles.item}
              onClick={() => {
                setOpen(false)
                if (opt !== priority) void onChange(opt)
              }}
            >
              {opt}
              {opt === priority ? ' ✓' : ''}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function PrioritySourceNote({ priority, redmineName }: { priority: string; redmineName?: string | null }) {
  if (!redmineName || !priority) return null
  if (priorityTone(redmineName) === priorityTone(priority)) return null
  return (
    <span className="text-faint" style={{ fontSize: 'var(--text-xs)', whiteSpace: 'nowrap' }} title="Generated priority">
      AI {priority}
    </span>
  )
}
