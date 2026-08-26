import { useEffect, useState } from 'react'
import { ExternalLink, RefreshCw, Zap } from 'lucide-react'
import { ApiError, getUsageLog, getUsageSummary } from '../../api/client'
import type { UsageKind, UsageLogEntry, UsageSummary } from '../../types'
import { useToast } from '../../hooks/useToast'
import { formatDuration, formatRelative } from '../../lib/format'
import { SkeletonList } from '../Skeleton'
import styles from './UsageTab.module.css'

const KIND_LABEL: Record<string, string> = {
  generation: 'Backlog generation',
  bitbucket_review: 'PR code review',
  security_scan: 'Security scan',
  wiki: 'Wiki generation',
  repo_brief: 'Brief from repository',
}

function kindLabel(kind: string): string {
  return KIND_LABEL[kind] || kind
}

function formatCost(cost: number): string {
  if (cost <= 0) return '$0.00'
  return cost < 0.01 ? '<$0.01' : `$${cost.toFixed(4)}`
}

/** ref_id's shape depends on kind (see record_token_usage's call sites):
 * a plain generation id ("42"), a "repo/pr#id" for reviews, a repo full
 * name for scans, a project or "project/repo" id for wiki. Rendered as-is
 * rather than parsed apart — it's a label here, not a link target, except
 * where a real cross-reference is cheap to build. */
function refLabel(entry: UsageLogEntry): string {
  if (!entry.ref_id) return '—'
  if (entry.kind === 'generation') return `Generation #${entry.ref_id}`
  return entry.ref_id
}

function UsageCard({ label, icon: Icon, calls, tokens, cost }: { label: string; icon: typeof Zap; calls: number; tokens: number; cost: number }) {
  return (
    <div className={styles.card}>
      <span className={styles.cardIcon} aria-hidden="true"><Icon /></span>
      <div>
        <strong>{tokens.toLocaleString()}</strong>
        <span>{label} · {calls} call{calls === 1 ? '' : 's'} · {formatCost(cost)}</span>
      </div>
    </div>
  )
}

export function UsageTab() {
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [entries, setEntries] = useState<UsageLogEntry[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const { showToast } = useToast()

  async function load() {
    setLoadError(null)
    try {
      const [s, log] = await Promise.all([getUsageSummary(), getUsageLog(100)])
      setSummary(s)
      setEntries(log.entries)
    } catch (e) {
      const message = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Unknown error'
      setLoadError(message)
      showToast('Failed to load usage', message, 'error')
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loadError && (summary === null || entries === null)) {
    return (
      <section className={styles.page}>
        <div className={`card ${styles.emptyState}`}>
          <p>Usage could not be loaded</p>
          <p className="text-muted">{loadError}</p>
          <button className="btn btn-secondary btn-sm" onClick={() => void load()}>
            <RefreshCw aria-hidden="true" /> Retry
          </button>
        </div>
      </section>
    )
  }

  if (summary === null || entries === null) {
    return (
      <section className={styles.page} aria-busy="true">
        <SkeletonList rows={4} />
      </section>
    )
  }

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <p>Real usage from each provider's own response — never an estimate. Only calls that went through a tracked provider are logged; a provider that doesn't report usage contributes nothing here.</p>
        <button className="btn btn-secondary btn-sm" onClick={() => void load()}>
          <RefreshCw aria-hidden="true" /> Refresh
        </button>
      </header>

      <div className={styles.cards}>
        <UsageCard label="Today" icon={Zap} calls={summary.today.ai_calls} tokens={summary.today.total_tokens} cost={summary.today.cost_usd} />
        <UsageCard label="Last 7 days" icon={Zap} calls={summary.week.ai_calls} tokens={summary.week.total_tokens} cost={summary.week.cost_usd} />
        <UsageCard label="Last 30 days" icon={Zap} calls={summary.month.ai_calls} tokens={summary.month.total_tokens} cost={summary.month.cost_usd} />
        <UsageCard label="All time" icon={Zap} calls={summary.all_time.ai_calls} tokens={summary.all_time.total_tokens} cost={summary.all_time.cost_usd} />
      </div>

      <div className={styles.tableSection}>
        <div className={styles.tableHeading}>
          <h3>Recent calls</h3>
          <span>{entries.length} of {summary.all_time.ai_calls} total</span>
        </div>
        {entries.length === 0 ? (
          <div className={`card ${styles.emptyState}`}>
            <p>No AI usage logged yet</p>
            <p className="text-muted">Generate a backlog, run a code review, or scan a repo — every call through a tracked provider shows up here.</p>
          </div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Type</th>
                  <th>Reference</th>
                  <th>Provider</th>
                  <th className={styles.numCol}>Prompt</th>
                  <th className={styles.numCol}>Completion</th>
                  <th className={styles.numCol}>Total</th>
                  <th className={styles.numCol}>Cost</th>
                  <th className={styles.numCol}>Time</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td className={styles.whenCell}>{formatRelative(entry.created_at) || entry.created_at}</td>
                    <td><span className="badge badge-neutral">{kindLabel(entry.kind as UsageKind)}</span></td>
                    <td className={styles.refCell}>{refLabel(entry)}</td>
                    <td className={styles.providerCell}>{entry.provider || '—'}</td>
                    <td className={styles.numCol}>{entry.prompt_tokens.toLocaleString()}</td>
                    <td className={styles.numCol}>{entry.completion_tokens.toLocaleString()}</td>
                    <td className={styles.numCol}><strong>{entry.total_tokens.toLocaleString()}</strong></td>
                    <td className={styles.numCol}>{formatCost(entry.cost_usd)}</td>
                    <td className={styles.numCol}>{entry.duration_seconds == null ? '—' : formatDuration(entry.duration_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {entries.length >= 100 && (
          <p className={styles.moreNote}><ExternalLink aria-hidden="true" /> Showing the most recent 100 calls.</p>
        )}
      </div>
    </section>
  )
}
