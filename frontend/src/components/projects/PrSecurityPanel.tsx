import { useEffect, useState } from 'react'
import { ArrowRight, ChevronDown, Copy, GitPullRequest, RefreshCw, ShieldAlert } from 'lucide-react'
import { ApiError, getRepoPrSecurityScan, listProjectPullRequests, triggerRepoPrSecurityScan } from '../../api/client'
import type { PRSecurityFinding, PRSecurityRelation, PRSecurityScanResult, ProjectDetail, ProjectPullRequest } from '../../types'
import { useToast } from '../../hooks/useToast'
import styles from './PrSecurityPanel.module.css'

// Worst-first, and NEW/PR-caused ahead of merely-relevant existing issues —
// same "explain what the PR actually did" priority the plan's UI mock uses.
const RELATION_ORDER: PRSecurityRelation[] = ['EXISTING_NEWLY_EXPOSED', 'DIRECT', 'INDIRECT', 'DEPENDENCY', 'EXISTING_RELEVANT']

const RELATION_LABEL: Record<PRSecurityRelation, string> = {
  EXISTING_NEWLY_EXPOSED: 'Existing vulnerability newly exposed by this PR',
  DIRECT: 'Directly introduced by this PR',
  INDIRECT: 'Reachable from this PR through existing code',
  DEPENDENCY: 'Dependency change',
  EXISTING_RELEVANT: 'Existing issue in the PR’s security-relevant context',
}

function severityBadgeClass(severity: PRSecurityFinding['severity']): string {
  if (severity === 'critical' || severity === 'high') return 'badge badge-danger'
  if (severity === 'medium') return 'badge badge-warning'
  return 'badge badge-neutral'
}

function ExecutionPath({ path }: { path: string[] }) {
  if (path.length < 2) return null
  return (
    <p className={styles.executionPath}>
      {path.map((name, i) => (
        <span key={`${name}-${i}`} style={{ display: 'contents' }}>
          {i > 0 && <span className={styles.arrow}><ArrowRight size={12} aria-hidden="true" /></span>}
          <span>{name}</span>
        </span>
      ))}
    </p>
  )
}

/** Explains WHY an unchanged file appears in the report — the relationship
 * between what the PR changed and where this finding actually lives, not
 * just "finding in unchanged file". */
function RelationExplainer({ finding }: { finding: PRSecurityFinding }) {
  const reason = finding.metadata?.reason
  if (!reason) return null
  return <p className={styles.relationExplainer}>{reason}</p>
}

function PrFindingCard({ finding }: { finding: PRSecurityFinding }) {
  const location = `${finding.file ?? '?'}${finding.start_line ? `:${finding.start_line}` : ''}`
  return (
    <article className="card">
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span className={severityBadgeClass(finding.severity)}>{finding.severity}</span>
        <span className="badge badge-neutral">{finding.relation_confidence} confidence</span>
        {finding.metadata?.baseline_state && finding.metadata.baseline_state !== 'UNKNOWN' && (
          <span className="badge badge-neutral">baseline: {finding.metadata.baseline_state}</span>
        )}
        <span style={{ color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono, monospace)', fontSize: 'var(--text-xs)' }}>{location}</span>
      </div>
      <strong style={{ display: 'block', marginBottom: 6 }}>{finding.title || finding.description || 'Security finding'}</strong>
      {finding.symbol && <p style={{ margin: '0 0 8px', color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>Changed: <code>{finding.symbol}</code></p>}
      <ExecutionPath path={finding.affected_path} />
      <RelationExplainer finding={finding} />
      {finding.remediation && (
        <p style={{ margin: '8px 0 0', color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}><strong>Recommendation: </strong>{finding.remediation}</p>
      )}
    </article>
  )
}

/** Plain-English "what did this PR do" — the piece a manager/PM actually
 * needs, independent of whether any security finding was reported. Always
 * present once a scan succeeds (falls back to a deterministic summary
 * server-side when the AI review didn't run). */
function ChangeSummaryCard({ result }: { result: PRSecurityScanResult }) {
  const { showToast } = useToast()

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(result.summary || '')
      showToast('Summary copied', 'Ready to paste for your manager or team.', 'info')
    } catch {
      showToast('Copy failed', 'Your browser blocked clipboard access.', 'error')
    }
  }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <strong style={{ fontSize: 'var(--text-sm)', textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--text-secondary)' }}>What this PR changes</strong>
        <button className="btn btn-ghost btn-sm" onClick={() => void copySummary()}><Copy aria-hidden="true" /> Copy</button>
      </div>
      <p style={{ margin: 0, color: 'var(--text-primary)', fontSize: 'var(--text-sm)', lineHeight: 1.55 }}>{result.summary}</p>
      {result.summary_source === 'fallback' && (
        <p style={{ margin: 0, color: 'var(--text-tertiary)', fontSize: 'var(--text-xs)' }}>
          Auto-generated from the changed files (the AI review didn’t complete for this scan).
        </p>
      )}
    </div>
  )
}

/** Exported so PullRequestsView.tsx can render a PR's security-impact
 * result inline in its own card (right next to the regular AI review),
 * rather than sending the user to a different tab to see it. */
export function PrSecurityResultView({ result }: { result: PRSecurityScanResult }) {
  // Declared before the early returns below (queued/running/failed states
  // don't have a stat grid to toggle) — a hook can't be called
  // conditionally, so this has to run on every render regardless of status.
  const [openDetail, setOpenDetail] = useState<'changed_symbols' | 'affected_files' | null>(null)

  if (result.status === 'queued' || result.status === 'running') {
    return (
      <div className={styles.stagesList} role="status">
        <span className="badge badge-info">{result.status === 'queued' ? 'Queued…' : 'Analyzing…'}</span>
        {(result.stages || []).map((stage, i) => (
          <span key={i}>{stage.stage}{stage.status ? `: ${stage.status}` : ''}</span>
        ))}
      </div>
    )
  }
  if (result.status === 'failed') {
    return <div className="card" role="alert" style={{ color: 'var(--danger)' }}>{result.error || 'PR security analysis failed.'}</div>
  }
  if (result.status !== 'succeeded') return null

  const findings = result.findings || []
  const byRelation = new Map<PRSecurityRelation, PRSecurityFinding[]>()
  for (const finding of findings) {
    const list = byRelation.get(finding.relation_to_pr) || []
    list.push(finding)
    byRelation.set(finding.relation_to_pr, list)
  }

  return (
    <div className={styles.panel}>
      {result.summary && <ChangeSummaryCard result={result} />}

      <div className={styles.summaryGrid}>
        <div className={styles.statTile} title="Files this PR's diff actually adds, modifies, or deletes.">
          <strong>{result.changed_files ?? 0}</strong><span>Changed files</span>
        </div>
        <button
          type="button"
          className={`${styles.statTile} ${styles.statTileClickable}`}
          aria-expanded={openDetail === 'changed_symbols'}
          onClick={() => setOpenDetail((v) => (v === 'changed_symbols' ? null : 'changed_symbols'))}
          title="'Symbol' = a named function, method, class, or component — not a line of text. This counts how many of those the PR actually touched. Click to see which ones."
        >
          <strong>{result.changed_symbols ?? 0}</strong>
          <span>Changed symbols <ChevronDown aria-hidden="true" size={12} className={openDetail === 'changed_symbols' ? styles.chevronOpen : ''} /></span>
        </button>
        <button
          type="button"
          className={`${styles.statTile} ${styles.statTileClickable}`}
          aria-expanded={openDetail === 'affected_files'}
          onClick={() => setOpenDetail((v) => (v === 'affected_files' ? null : 'affected_files'))}
          title="Files outside this PR's diff that call, get called by, or inherit from what changed — where the change could ripple to beyond the files it directly touched. Click to see which ones."
        >
          {/* The count here is downstream-only (seed:false) — files reached
              by traversal, not the PR's own changed files. affected_files
              itself is a superset (changed + downstream) and was showing
              the same number as "Changed files" whenever nothing was
              actually reached, reading as a second, empty-handed stat
              instead of the "0 ripple" it actually meant. */}
          <strong>{(result.affected_files_detail || []).filter((f) => !f.seed).length}</strong>
          <span>Affected files <ChevronDown aria-hidden="true" size={12} className={openDetail === 'affected_files' ? styles.chevronOpen : ''} /></span>
        </button>
        <div className={styles.statTile} title="Security findings this analysis judged relevant to what the PR actually changed — not every finding in the whole repository.">
          <strong>{findings.length}</strong><span>PR-relevant findings</span>
        </div>
      </div>

      {openDetail === 'changed_symbols' && (
        <div className={styles.detailPanel}>
          {(result.changed_symbols_detail || []).length === 0 ? (
            <p className={styles.detailEmpty}>No detail available for this scan (older scans predate this breakdown — re-run to see it).</p>
          ) : (
            <ul className={styles.detailList}>
              {(result.changed_symbols_detail || []).map((seed, i) => (
                <li key={i}>
                  <span className="badge badge-neutral">{seed.change_status}</span>
                  <code>{seed.symbol || seed.file}</code>
                  {seed.symbol && <span className={styles.detailPath}>{seed.file}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {openDetail === 'affected_files' && (
        <div className={styles.detailPanel}>
          {(result.affected_files_detail || []).length === 0 ? (
            <p className={styles.detailEmpty}>No detail available for this scan (older scans predate this breakdown — re-run to see it).</p>
          ) : (result.affected_files_detail || []).every((f) => f.seed) ? (
            <p className={styles.detailEmpty}>
              {(result.affected_files_detail || []).length === 1 ? 'This is the one file' : 'These are the only files'} the PR changed. No other file in the repo calls, gets called by, or inherits from what changed, so there's no further impact to show.
            </p>
          ) : (
            <ul className={styles.detailList}>
              {(result.affected_files_detail || []).map((f) => (
                <li key={f.path}>
                  <span className={`badge ${f.seed ? 'badge-neutral' : 'badge-info'}`}>{f.seed ? 'Changed by this PR' : 'Depends on the change'}</span>
                  <code>{f.path}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {result.context_truncated && (
        <p className={styles.truncationNotice}>
          Analysis context was truncated to fit configured limits ({(result.truncation_reasons || []).join('; ') || 'size limits reached'}).
          Results below may be incomplete.
        </p>
      )}
      {result.llm_review_status === 'failed' && (
        <p className={styles.truncationNotice}>
          The AI security review did not complete for this scan — findings below are from deterministic scanners only.
        </p>
      )}

      <p style={{ margin: 0, color: 'var(--text-tertiary)', fontSize: 'var(--text-xs)' }}>
        Baseline: {result.baseline?.source === 'NONE' ? 'no reliable baseline scan available' : `${result.baseline?.source?.toLowerCase().replace(/_/g, ' ')} (${result.baseline?.confidence?.toLowerCase()} confidence)`}
      </p>

      {findings.length === 0 && (
        <p style={{ margin: 0, padding: 'var(--space-4)', textAlign: 'center', color: 'var(--text-tertiary)', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
          No PR-relevant security findings. Unrelated repository findings (if any) are not shown here — see the Full Repository Scan above.
        </p>
      )}

      {RELATION_ORDER.filter((relation) => byRelation.has(relation)).map((relation) => (
        <div key={relation} className={styles.relationGroup}>
          <div className={styles.relationGroupHeading}>
            <ShieldAlert size={14} aria-hidden="true" />
            <h4>{RELATION_LABEL[relation]} ({byRelation.get(relation)!.length})</h4>
          </div>
          {byRelation.get(relation)!.map((finding) => <PrFindingCard key={finding.id} finding={finding} />)}
        </div>
      ))}
    </div>
  )
}

export function PrSecurityPanel({ project }: { project: ProjectDetail }) {
  const [pullRequests, setPullRequests] = useState<{ repoId: number; label: string; pr: ProjectPullRequest }[]>([])
  const [selected, setSelected] = useState<string>('')
  const [triggering, setTriggering] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [result, setResult] = useState<PRSecurityScanResult | null>(null)
  const { showToast } = useToast()

  useEffect(() => {
    let cancelled = false
    listProjectPullRequests(project.id).then((data) => {
      if (cancelled) return
      const flattened = data.repos.flatMap((repo) =>
        repo.pull_requests.filter((pr) => pr.state === 'OPEN').map((pr) => ({ repoId: repo.repo_id, label: repo.label, pr })),
      )
      setPullRequests(flattened)
      if (flattened.length > 0) setSelected(`${flattened[0].repoId}:${flattened[0].pr.id}`)
    }).catch(() => {
      // Best-effort — the picker just stays empty; the rest of the Security
      // page (Full Repository Scan) is unaffected.
    })
    return () => { cancelled = true }
  }, [project.id])

  useEffect(() => {
    if (!jobId) return
    const [repoIdStr] = selected.split(':')
    const repoId = Number(repoIdStr)
    let cancelled = false
    async function poll() {
      try {
        const data = await getRepoPrSecurityScan(project.id, repoId, jobId!)
        if (cancelled) return
        setResult(data)
        if (data.status === 'queued' || data.status === 'running') {
          setTimeout(poll, 3000)
        }
      } catch {
        // transient — next manual action can re-trigger
      }
    }
    void poll()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  async function runScan() {
    if (!selected) return
    const [repoIdStr, prIdStr] = selected.split(':')
    const repoId = Number(repoIdStr)
    setTriggering(true)
    setResult(null)
    try {
      const job = await triggerRepoPrSecurityScan(project.id, repoId, prIdStr)
      setJobId(job.job_id)
      showToast('PR analysis started', `Analyzing PR #${prIdStr} for security impact…`, 'info')
    } catch (e) {
      showToast('Failed to start PR analysis', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setTriggering(false)
    }
  }

  if (pullRequests.length === 0) return null

  const selectedEntry = pullRequests.find((item) => `${item.repoId}:${item.pr.id}` === selected)

  return (
    <div className={`card ${styles.panel}`}>
      <div className={styles.panelHeading}>
        <div>
          <h3>Pull Request Impact Analysis</h3>
          <p>Understands what changed, traces its effect across the repository, and explains the security consequences — not just a scan of changed lines.</p>
        </div>
      </div>
      <div className={styles.controls}>
        <GitPullRequest aria-hidden="true" />
        <select value={selected} onChange={(e) => setSelected(e.target.value)} aria-label="Select pull request">
          {pullRequests.map(({ repoId, label, pr }) => (
            <option key={`${repoId}:${pr.id}`} value={`${repoId}:${pr.id}`}>
              [{label}] #{pr.id} — {pr.title}
            </option>
          ))}
        </select>
        <button className="btn btn-primary btn-sm" disabled={!selected || triggering} onClick={() => void runScan()}>
          {triggering ? <span className="btn-spinner" /> : <RefreshCw aria-hidden="true" />}
          Analyze PR Security Impact
        </button>
      </div>
      {selectedEntry && !result && <p style={{ margin: 0, color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>PR #{selectedEntry.pr.id} — {selectedEntry.pr.title}</p>}
      {result && <PrSecurityResultView result={result} />}
    </div>
  )
}
