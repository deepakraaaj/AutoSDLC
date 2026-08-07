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
