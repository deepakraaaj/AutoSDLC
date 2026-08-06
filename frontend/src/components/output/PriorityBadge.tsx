import { priorityTone } from '../../lib/format'

export function PriorityBadge({
  priority,
  redmineName,
}: {
  priority: string
  redmineName?: string | null
}) {
  const display = redmineName || priority
  if (!display) return null
  const tone = priorityTone(display)
  const title = redmineName
    ? `Redmine priority: ${redmineName}${priority ? ` | Generated priority: ${priority}` : ''}`
    : `Generated priority: ${priority}`

  return (
    <span className={`badge badge-priority badge-priority-${tone}`} title={title}>
      {display}
    </span>
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
