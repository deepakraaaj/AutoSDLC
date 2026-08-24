export function scoreTone(value: number): 'success' | 'warning' | 'danger' {
  if (value >= 75) return 'success'
  if (value >= 50) return 'warning'
  return 'danger'
}

export function priorityTone(value: string | null | undefined): string {
  const p = String(value || '').trim().toLowerCase()
  if (p === 'critical' || p === 'immediate') return 'critical'
  if (p === 'high' || p === 'urgent') return 'high'
  if (p === 'medium' || p === 'normal') return 'medium'
  if (p === 'low') return 'low'
  return 'external'
}

export function confidenceTone(c: string | null | undefined): 'success' | 'warning' | 'danger' {
  if (c === 'high') return 'success'
  if (c === 'medium') return 'warning'
  return 'danger'
}

export function formatDate(iso: string): string {
  // Older database rows were saved with datetime.utcnow().isoformat(), so
  // they contain UTC clock time but no timezone suffix. Treat those as UTC;
  // current rows already include an explicit +00:00 offset.
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso)
  const parsed = new Date(hasTimezone ? iso : `${iso}Z`)
  if (Number.isNaN(parsed.getTime())) return iso
  return parsed.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

/** "3h ago", "2d ago", "5mo ago". List rows are ordered newest-first, so how long
 * ago is the useful fact; the exact timestamp stays available as a `title`. */
export function formatRelative(iso: string): string {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso)
  const parsed = new Date(hasTimezone ? iso : `${iso}Z`)
  if (Number.isNaN(parsed.getTime())) return ''
  const seconds = Math.max(0, (Date.now() - parsed.getTime()) / 1000)
  const units: [number, string][] = [
    [60, 's'],
    [3600, 'm'],
    [86400, 'h'],
    [86400 * 30, 'd'],
    [86400 * 365, 'mo'],
    [Infinity, 'y'],
  ]
  const divisors = [1, 60, 3600, 86400, 86400 * 30, 86400 * 365]
  for (let i = 0; i < units.length; i += 1) {
    if (seconds < units[i][0]) {
      const value = Math.floor(seconds / divisors[i])
      return i === 0 ? 'just now' : `${value}${units[i][1]} ago`
    }
  }
  return ''
}

export function totalEstimateHours(tasks: { estimate_hours: string }[]): number {
  return tasks.reduce((sum, t) => {
    const low = parseFloat((t.estimate_hours || '').split('-')[0]?.trim() ?? '')
    return sum + (Number.isFinite(low) ? low : 0)
  }, 0)
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const total = Math.max(0, Math.round(seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  if (m === 0) return `${s}s`
  return `${m}m ${s.toString().padStart(2, '0')}s`
}

export function issueLabel(item: { issue_id?: string; ai_id?: string; id?: string }): string {
  return item.issue_id || item.ai_id || item.id || ''
}

export async function copyText(text: string): Promise<void> {
  await navigator.clipboard.writeText(text)
}

/** Plain-text rendering of a backlog, for the Scorecard's "copy" action. Lived
 * inside OutputView until the quality panels moved out to QualityRail; it is
 * formatting, not view state, so it belongs here rather than in either of them. */
export function backlogToPlainText(output: {
  stories: { id: string; title: string; as_a: string; i_want: string; so_that: string; acceptance_criteria: string[] }[]
  tasks: { id: string; title: string; estimate_hours: string; description: string; definition_of_done: string }[]
}): string {
  const lines: string[] = []
  output.stories.forEach((s) => {
    lines.push(`[${s.id}] ${s.title}`)
    lines.push(`As a ${s.as_a}, I want to ${s.i_want}, so that ${s.so_that}.`)
    s.acceptance_criteria.forEach((ac) => lines.push(`  ✓ ${ac}`))
    lines.push('')
  })
  output.tasks.forEach((t) => {
    lines.push(`[${t.id}] ${t.title} (${t.estimate_hours} hrs)`)
    lines.push(`  ${t.description}`)
    lines.push(`  Done: ${t.definition_of_done}`)
    lines.push('')
  })
  return lines.join('\n')
}
