import { useEffect, useState } from 'react'
import { GitBranch, RefreshCw, ShieldAlert, Wrench } from 'lucide-react'
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

const TOOL_HELP: Record<string, string> = {
  semgrep: 'Scans source code for insecure patterns and security bugs.',
  gitleaks: 'Searches files for leaked passwords, API keys, and tokens.',
  trivy: 'Checks dependencies, secrets, and infrastructure misconfiguration.',
  'osv-scanner': 'Checks dependencies against the OSV vulnerability database.',
  eslint: 'Checks JavaScript/TypeScript with approved security rules.',
  'npm-audit': 'Checks npm dependencies for known advisories.',
  'pip-audit': 'Checks Python dependencies for known vulnerabilities.',
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

      {scan.error && <div className={styles.repoError}>{scan.error}</div>}

      {scan.status === 'succeeded' && scan.tools.length === 0 && (
        <div className={styles.legacyNotice}>
          This result predates deterministic VAPT scanners. Re-run to inspect the repository with Semgrep, Gitleaks, Trivy, and OSV-Scanner.
        </div>
      )}

      {scan.tools.length > 0 && (
        <div className={styles.toolStrip} aria-label="Security scanner results">
          {scan.tools.map((tool) => (
            <span key={tool.name} className={tool.status === 'completed' ? 'badge badge-success' : tool.status === 'unavailable' ? 'badge badge-neutral' : 'badge badge-warning'} title={`${TOOL_HELP[tool.name] || tool.name}\nStatus: ${tool.status}`}>
              <Wrench aria-hidden="true" /> {tool.name}: {tool.status === 'completed' ? `${tool.findings_count} finding${tool.findings_count === 1 ? '' : 's'}` : tool.status}
            </span>
          ))}
        </div>
      )}
      {scan.tools.some((tool) => tool.status === 'unavailable' || tool.status === 'failed') && (
        <div className={styles.repoError} role="status">
          Incomplete scan: some deterministic scanners could not run. A zero-finding result below is not a clean VAPT verdict.
        </div>
      )}
      {scan.snapshot_files > 0 && <p className={styles.scannedAt}>Evidence snapshot: {scan.snapshot_files} files{scan.duration_seconds != null ? ` · ${scan.duration_seconds}s` : ''}{scan.scanner_commit ? ` · ${scan.scanner_commit.slice(0, 12)}` : ''}</p>}

      {scan.status === 'succeeded' && orderedFindings.length === 0 && scan.tools.length > 0 && scan.tools.every((tool) => tool.status === 'completed') && (
        <p className={styles.repoEmpty}>No security issues found.</p>
      )}

      {orderedFindings.length > 0 && (
        <div className={styles.findingList}>
          {orderedFindings.map((finding, i) => (
            <article key={i} className={styles.finding}>
              <div className={styles.findingTop}>
                <span className={severityBadgeClass(finding.severity)}>{finding.severity}</span>
                <span className={styles.category}>{CATEGORY_LABEL[finding.category]}</span>
                {finding.tool && <span className={styles.category}>{finding.tool}</span>}
                <span className={styles.location}>{finding.file}{finding.line ? `:${finding.line}` : ''}</span>
              </div>
              <p className={styles.comment}>{finding.comment}</p>
              {finding.recommendation && <p className={styles.recommendation}><strong>Fix:</strong> {finding.recommendation}</p>}
              {finding.evidence && <p className={styles.recommendation}><strong>Evidence:</strong> {finding.evidence}</p>}
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

  // Same fix as PullRequestsView's poll: nothing was re-fetching after
  // triggering a scan, so "Scanning…" only updated on a manual Refresh.
  // Self-reschedules while any repo's scan is still queued/running, stops
  // once everything's settled.
  useEffect(() => {
    if (!data) return
    const hasPending = data.repos.some((r) => r.scan.status === 'queued' || r.scan.status === 'running')
    if (!hasPending) return
    const timer = setTimeout(() => void load(), 3000)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  if (project.repos.length === 0) {
    return (
      <section className={styles.page}>
        <header className={styles.header}>
          <div><h2>Security / VAPT</h2><p>Deterministic scanners plus AI-assisted analysis across this project's repos.</p></div>
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
          <div><h2>Security / VAPT</h2><p>Deterministic scanners plus AI-assisted analysis across this project's repos.</p></div>
        </header>
        <SkeletonList rows={3} />
      </section>
    )
  }

  const everUnscanned = data.repos.every((r) => r.scan.status === 'not_scanned')

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <div><h2>Security / VAPT</h2><p>Deterministic scanners plus AI-assisted analysis across this project's repos.</p></div>
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
        <ShieldAlert aria-hidden="true" /> Source scanners provide the evidence; AI explains and correlates it. ZAP runtime testing is not enabled yet.
      </p>
    </section>
  )
}
