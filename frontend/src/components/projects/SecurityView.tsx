import { useEffect, useState } from 'react'
import { GitBranch, RefreshCw, ShieldAlert } from 'lucide-react'
import { ApiError, getProjectSecurity, triggerRepoSecurityScan } from '../../api/client'
import type { ProjectDetail, ProjectRepoSecurity, ProjectSecurity, SecurityFinding } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { APP_ICONS } from '../icons/appIcons'
import styles from './SecurityView.module.css'

const SCAN_LABEL: Record<ProjectRepoSecurity['scan']['status'], string> = {
  not_scanned: 'Not scanned',
  queued: 'Scan queued',
  running: 'Scanning…',
  succeeded: 'Scanned',
  failed: 'Scan failed',
  cancelled: 'Scan cancelled',
}

const CATEGORY_LABEL: Record<SecurityFinding['category'], string> = {
  injection: 'Injection',
  auth: 'Auth / access control',
  secrets: 'Secrets',
  ssrf: 'SSRF',
  deserialization: 'Insecure deserialization',
  'path-traversal': 'Path traversal',
  crypto: 'Crypto',
  xxe: 'XXE',
  'input-validation': 'Input validation',
  'data-exposure': 'Data exposure',
  other: 'Other',
}

function severityBadgeClass(severity: SecurityFinding['severity']): string {
  if (severity === 'critical' || severity === 'high') return 'badge badge-danger'
  if (severity === 'medium') return 'badge badge-warning'
  return 'badge badge-neutral'
}

function scanBadgeClass(scan: ProjectRepoSecurity['scan']): string {
  if (scan.status === 'failed') return 'badge badge-danger'
  if (scan.status === 'queued' || scan.status === 'running') return 'badge badge-info'
  if (scan.status === 'succeeded') {
    const { critical, high, medium } = scan.severity_counts
    return critical > 0 || high > 0 ? 'badge badge-danger' : medium > 0 ? 'badge badge-warning' : 'badge badge-success'
  }
  return 'badge badge-neutral'
}

/** One repo's latest security scan — a "Run scan" action when none has run
 * yet, otherwise the finding list grouped loosest-first by nothing but
 * severity (worst first), since VAPT triage reads top-down by risk. */
function RepoSecurityCard({ projectId, repo, onScanTriggered }: { projectId: number; repo: ProjectRepoSecurity; onScanTriggered: () => void }) {
  const [triggering, setTriggering] = useState(false)
  const { showToast } = useToast()
  const { scan } = repo
  const canRunScan = scan.status !== 'queued' && scan.status !== 'running'
  const orderedFindings = [...scan.findings].sort((a, b) => {
    const rank = { critical: 0, high: 1, medium: 2, low: 3 }
    return rank[a.severity] - rank[b.severity]
  })

  async function runScan() {
    setTriggering(true)
    try {
      await triggerRepoSecurityScan(projectId, repo.repo_id)
      showToast('Scan started', `Scanning ${repo.label} for security issues…`, 'info')
      onScanTriggered()
    } catch (e) {
      showToast('Failed to start scan', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div className={styles.repoSection}>
      <div className={styles.repoHeading}>
        <GitBranch aria-hidden="true" />
        <strong>{repo.label}</strong>
        <span>{repo.repo_full_name}</span>
        <div className={styles.repoHeadingActions}>
          <span className={scanBadgeClass(scan)}>{SCAN_LABEL[scan.status]}</span>
          {scan.scanned_at && <span className={styles.scannedAt}>as of {new Date(scan.scanned_at).toLocaleString()}</span>}
          <button className="btn btn-ghost btn-sm" disabled={!canRunScan || triggering} onClick={() => void runScan()}>
            {triggering ? <span className="btn-spinner" /> : <RefreshCw aria-hidden="true" />}
            {scan.status === 'not_scanned' ? 'Run scan' : 'Re-run scan'}
          </button>
        </div>
      </div>

      {scan.status === 'failed' && scan.error && <div className={styles.repoError}>{scan.error}</div>}

      {scan.status === 'succeeded' && orderedFindings.length === 0 && (
        <p className={styles.repoEmpty}>No security issues found.</p>
      )}

      {orderedFindings.length > 0 && (
        <div className={styles.findingList}>
          {orderedFindings.map((finding, i) => (
            <article key={i} className={styles.finding}>
              <div className={styles.findingTop}>
                <span className={severityBadgeClass(finding.severity)}>{finding.severity}</span>
                <span className={styles.category}>{CATEGORY_LABEL[finding.category]}</span>
                <span className={styles.location}>{finding.file}{finding.line ? `:${finding.line}` : ''}</span>
              </div>
              <p className={styles.comment}>{finding.comment}</p>
              {finding.recommendation && <p className={styles.recommendation}><strong>Fix:</strong> {finding.recommendation}</p>}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

export function SecurityView({ project }: { project: ProjectDetail }) {
  const [data, setData] = useState<ProjectSecurity | null>(null)
  const { showToast } = useToast()

  async function load() {
    try {
      setData(await getProjectSecurity(project.id))
    } catch (e) {
      showToast('Failed to load security scans', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  if (project.repos.length === 0) {
    return (
      <section className={styles.page}>
        <header className={styles.header}>
          <div><h2>Security / VAPT</h2><p>AI-driven vulnerability scan across this project's repos.</p></div>
        </header>
        <div className={`card ${styles.emptyState}`}>
          <p>No repos linked to {project.name} yet</p>
          <p className="text-muted">Link a Bitbucket repo in Project settings to scan it for security issues.</p>
        </div>
      </section>
    )
  }

  if (data === null) {
    return (
      <section className={styles.page} aria-busy="true">
        <header className={styles.header}>
          <div><h2>Security / VAPT</h2><p>AI-driven vulnerability scan across this project's repos.</p></div>
        </header>
        <SkeletonList rows={3} />
      </section>
    )
  }

  const everUnscanned = data.repos.every((r) => r.scan.status === 'not_scanned')

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <div><h2>Security / VAPT</h2><p>AI-driven vulnerability scan across this project's repos.</p></div>
        <button className="btn btn-secondary btn-sm" onClick={() => void load()}>
          <RefreshCw aria-hidden="true" /> Refresh
        </button>
      </header>

      {everUnscanned && (
        <div className={`card ${styles.emptyState}`}>
          <APP_ICONS.security aria-hidden="true" />
          <p>No repo has been scanned yet</p>
          <p className="text-muted">Run a scan on a repo below to check it for exploitable security issues.</p>
        </div>
      )}

      {data.repos.map((repo) => (
        <RepoSecurityCard key={repo.repo_id} projectId={project.id} repo={repo} onScanTriggered={() => void load()} />
      ))}

      <p className={styles.footnote}>
        <ShieldAlert aria-hidden="true" /> LLM-based scan — a first pass, not a substitute for a real penetration test or dependency/CVE scanner.
      </p>
    </section>
  )
}
