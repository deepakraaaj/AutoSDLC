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
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return iso
  }
}

export function totalEstimateHours(tasks: { estimate_hours: string }[]): number {
  return tasks.reduce((sum, t) => {
    const low = parseFloat((t.estimate_hours || '').split('-')[0]?.trim() ?? '')
    return sum + (Number.isFinite(low) ? low : 0)
  }, 0)
}

export function issueLabel(item: { issue_id?: string; ai_id?: string; id?: string }): string {
  return item.issue_id || item.ai_id || item.id || ''
}

export async function copyText(text: string): Promise<void> {
  await navigator.clipboard.writeText(text)
}
