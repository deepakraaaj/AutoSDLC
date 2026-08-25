import { useEffect, useState } from 'react'
import { AlertTriangle, Ban, CheckCircle2, ChevronLeft, ChevronRight, Copy, GitBranch, Loader2, PanelRight, RefreshCw, Search, ShieldAlert, XCircle, X } from 'lucide-react'
import { ApiError, getProjectSecurity, triggerRepoSecurityScan } from '../../api/client'
import type { ProjectDetail, ProjectRepoSecurity, ProjectSecurity, SecurityFinding } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { APP_ICONS } from '../icons/appIcons'
import styles from './SecurityView.module.css'
import { AnimatedEmptyVisual } from '../AnimatedEmptyVisual'
import { PrSecurityPanel } from './PrSecurityPanel'

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
  dependency: 'Vulnerable dependency',
  misconfiguration: 'Misconfiguration',
  code: 'Code quality',
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

const DEFAULT_PAGE_SIZE = 20

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

function toolStatusLabel(tool: ProjectRepoSecurity['scan']['tools'][number]): string {
  if (tool.status === 'completed') return `${tool.findings_count} raw detection${tool.findings_count === 1 ? '' : 's'}`
  if (tool.status === 'not_applicable') return 'Not applicable'
  if (tool.status === 'disabled') return 'Disabled'
  if (tool.status === 'unavailable') return 'Unavailable'
  if (tool.status === 'running' || tool.status === 'queued') return 'Running…'
  return 'Failed'
}

/** A scanner card's icon+color is the fast at-a-glance signal (a board of
 * 7 identical wrench icons made every card look the same regardless of
 * whether it ran clean, found something, or never ran at all) — the label
 * text underneath is the detail for whoever actually reads it. */
function toolStatusVisual(tool: ProjectRepoSecurity['scan']['tools'][number]): { Icon: typeof CheckCircle2; tone: string } {
  if (tool.status === 'running' || tool.status === 'queued') return { Icon: Loader2, tone: 'running' }
  if (tool.status === 'not_applicable' || tool.status === 'disabled') return { Icon: Ban, tone: 'muted' }
  if (tool.status === 'unavailable' || tool.status === 'failed') return { Icon: XCircle, tone: 'error' }
  // completed
  return tool.findings_count > 0 ? { Icon: AlertTriangle, tone: 'attention' } : { Icon: CheckCircle2, tone: 'clean' }
}

function remediationPrompt(repo: ProjectRepoSecurity, finding: SecurityFinding): string {
  const location = `${finding.file}${finding.line ? `:${finding.line}` : ''}`
  return [
    '# Security remediation task',
    '',
    `Repository: ${repo.repo_full_name}`,
    `Severity: ${finding.severity.toUpperCase()}`,
    `Category: ${CATEGORY_LABEL[finding.category]}`,
    `Scanner: ${finding.tool || 'security review'}`,
    `Rule / advisory: ${[finding.rule_id, ...(finding.identifiers || [])].filter(Boolean).join(', ') || 'not provided'}`,
    `Location: ${location}`,
    '',
    '## Root cause',
    finding.comment,
    '',
    '## Evidence',
    finding.evidence || `Scanner reported the issue at ${location}. Inspect the surrounding code and dependency path before changing it.`,
    '',
    '## Required fix',
    finding.recommendation || 'Remove the unsafe behavior or upgrade the affected dependency to a non-vulnerable version. Preserve existing product behavior.',
    '',
    '## Verification',
    finding.verification || `Re-run ${finding.tool || 'the security scan'} and add or update a focused regression test. Do not mark complete until this finding is absent or documented as a verified false positive.`,
  ].join('\n')
}

/** One repo's latest security scan — a "Run scan" action when none has run
 * yet, otherwise the finding list grouped loosest-first by nothing but
 * severity (worst first), since VAPT triage reads top-down by risk. */
function RepoSecurityCard({ projectId, repo, onScanTriggered }: { projectId: number; repo: ProjectRepoSecurity; onScanTriggered: () => void }) {
  const [triggering, setTriggering] = useState(false)
  const [query, setQuery] = useState('')
  const [severity, setSeverity] = useState('all')
  const [tool, setTool] = useState('all')
  const [category, setCategory] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  // Scanner Coverage as a collapsible right rail, same PanelRight
  // toggle/pattern as QualityRail beside the backlog. Unlike QualityRail's
  // toggle (which only existed on one tab, stranding other views with no
  // way to close or reopen it), this button lives right here in the repo
  // card itself — always present, so it never goes unreachable.
  const [scannerRailOpen, setScannerRailOpen] = useState(true)
  const { showToast } = useToast()
  const { scan } = repo
  const canRunScan = scan.status !== 'queued' && scan.status !== 'running'
  const orderedFindings = [...scan.findings].sort((a, b) => {
    const rank = { critical: 0, high: 1, medium: 2, low: 3 }
    return rank[a.severity] - rank[b.severity]
  })
  const tools = [...new Set(orderedFindings.flatMap((finding) => (finding.tool || '').split(', ')).filter(Boolean))].sort()
  const categories = [...new Set(orderedFindings.map((finding) => finding.category))].sort()
  const normalizedQuery = query.trim().toLowerCase()
  const filteredFindings = orderedFindings.filter((finding) => {
    const searchable = [finding.file, finding.comment, finding.recommendation, finding.evidence, finding.rule_id, ...(finding.identifiers || [])].filter(Boolean).join(' ').toLowerCase()
    return (severity === 'all' || finding.severity === severity)
      && (tool === 'all' || (finding.tool || '').split(', ').includes(tool))
      && (category === 'all' || finding.category === category)
      && (!normalizedQuery || searchable.includes(normalizedQuery))
  })
  const pageCount = Math.max(1, Math.ceil(filteredFindings.length / pageSize))
  const safePage = Math.min(page, pageCount)
  const pageStart = (safePage - 1) * pageSize
  const visibleFindings = filteredFindings.slice(pageStart, pageStart + pageSize)
  const filtersActive = query !== '' || severity !== 'all' || tool !== 'all' || category !== 'all'

  useEffect(() => {
    setPage(1)
  }, [query, severity, tool, category, pageSize])

  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  async function copyText(value: string, title: string) {
    try {
      await navigator.clipboard.writeText(value)
      showToast(title, 'Ready to paste into your developer or coding agent.', 'info')
    } catch {
      showToast('Copy failed', 'Your browser blocked clipboard access.', 'error')
    }
  }

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
          {scan.tools.length > 0 && (
            <button
              type="button"
              className={`${styles.iconBtn} ${scannerRailOpen ? styles.iconBtnPressed : ''}`}
              onClick={() => setScannerRailOpen((v) => !v)}
              aria-label={scannerRailOpen ? 'Hide scanner coverage panel' : 'Show scanner coverage panel'}
              aria-pressed={scannerRailOpen}
              title={scannerRailOpen ? 'Hide scanner coverage panel' : 'Show scanner coverage panel'}
            >
              <PanelRight aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {scan.error && <div className={styles.repoError}>{scan.error}</div>}

      {scan.status === 'succeeded' && scan.tools.length === 0 && (
        <div className={styles.legacyNotice}>
          This result predates deterministic VAPT scanners. Re-run to inspect the repository with Semgrep, Gitleaks, Trivy, and OSV-Scanner.
        </div>
      )}

      <div className={styles.repoLayout}>
        <div className={styles.repoMain}>
      {scan.tools.some((tool) => ['unavailable', 'disabled', 'failed'].includes(tool.status)) && (
        <div className={styles.repoError} role="status">
          Incomplete scan: some deterministic scanners could not run. A zero-finding result below is not a clean VAPT verdict.
        </div>
      )}
      {scan.snapshot_files > 0 && <p className={styles.scannedAt}>Evidence snapshot: {scan.snapshot_files} files{scan.duration_seconds != null ? ` · ${scan.duration_seconds}s` : ''}{scan.scanner_commit ? ` · ${scan.scanner_commit.slice(0, 12)}` : ''}</p>}

      {scan.status === 'succeeded' && orderedFindings.length === 0 && scan.tools.length > 0 && scan.tools.every((tool) => tool.status === 'completed') && (
        <p className={styles.repoEmpty}>No security issues found.</p>
      )}

      {orderedFindings.length > 0 && (
        <div className={styles.triageSection}>
          <div className={styles.triageHeading}>
            <div><strong>Remediation queue</strong><span>{filteredFindings.length} of {orderedFindings.length} unique findings</span></div>
            <button className="btn btn-secondary btn-sm" disabled={filteredFindings.length === 0} onClick={() => void copyText(filteredFindings.map((finding) => remediationPrompt(repo, finding)).join('\n\n---\n\n'), 'Findings copied')}><Copy aria-hidden="true" /> Copy filtered for agent</button>
          </div>
          <div className={styles.filters} aria-label="Finding filters">
            <label className={styles.search}><Search aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search file, advisory, root cause…" aria-label="Search findings" /></label>
            <select value={severity} onChange={(event) => setSeverity(event.target.value)} aria-label="Filter by severity"><option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
            <select value={tool} onChange={(event) => setTool(event.target.value)} aria-label="Filter by scanner"><option value="all">All scanners</option>{tools.map((value) => <option key={value} value={value}>{value}</option>)}</select>
            <select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="Filter by category"><option value="all">All categories</option>{categories.map((value) => <option key={value} value={value}>{CATEGORY_LABEL[value]}</option>)}</select>
            {filtersActive && <button className="btn btn-ghost btn-sm" onClick={() => { setQuery(''); setSeverity('all'); setTool('all'); setCategory('all') }}><X aria-hidden="true" /> Clear</button>}
          </div>
        <div className={styles.findingList}>
          {visibleFindings.map((finding, i) => (
            <article key={finding.fingerprint || `${finding.file}-${finding.line}-${i}`} className={styles.finding}>
              <div className={styles.findingTop}>
                <span className={severityBadgeClass(finding.severity)}>{finding.severity}</span>
                <span className={styles.category}>{CATEGORY_LABEL[finding.category]}</span>
                {finding.tool && <span className={styles.category}>{finding.tool}</span>}
                {/* Several advisories against the same package are bundled into
                    this one card (see app/api/projects.py's _security_summary) —
                    surface the real count so it doesn't read as a single issue. */}
                {(finding.advisory_count ?? 1) > 1 && <span className={styles.category}>{finding.advisory_count} advisories</span>}
                <span className={styles.location}>{finding.file}{finding.line ? `:${finding.line}` : ''}</span>
                <button className={`btn btn-ghost btn-sm ${styles.copyFinding}`} onClick={() => void copyText(remediationPrompt(repo, finding), 'Remediation task copied')}><Copy aria-hidden="true" /> Copy for agent</button>
              </div>
              {(finding.rule_id || (finding.identifiers || []).length > 0) && <p className={styles.advisory}><strong>Rule / advisory:</strong> {[finding.rule_id, ...(finding.identifiers || [])].filter(Boolean).join(', ')}</p>}
              <div className={styles.detailBlock}><strong>Root cause</strong><p>{finding.comment}</p></div>
              {finding.evidence && <div className={styles.detailBlock}><strong>Evidence</strong><code>{finding.evidence}</code></div>}
              {finding.recommendation && <div className={styles.detailBlock}><strong>Required fix</strong><p>{finding.recommendation}</p></div>}
              {finding.verification && <div className={styles.detailBlock}><strong>Verification</strong><p>{finding.verification}</p></div>}
            </article>
          ))}
          {filteredFindings.length === 0 && <p className={styles.repoEmpty}>No findings match these filters.</p>}
        </div>
        {filteredFindings.length > 0 && (
          <nav className={styles.pagination} aria-label="Security findings pagination">
            <span>Showing {pageStart + 1}–{Math.min(pageStart + pageSize, filteredFindings.length)} of {filteredFindings.length}</span>
            <label>Rows per page <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))} aria-label="Rows per page"><option value="10">10</option><option value="20">20</option><option value="50">50</option></select></label>
            <div className={styles.pageControls}>
              <button className="btn btn-secondary btn-sm" disabled={safePage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))} aria-label="Previous findings page"><ChevronLeft aria-hidden="true" /></button>
              <span>Page <strong>{safePage}</strong> of {pageCount}</span>
              <button className="btn btn-secondary btn-sm" disabled={safePage === pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))} aria-label="Next findings page"><ChevronRight aria-hidden="true" /></button>
            </div>
          </nav>
        )}
        </div>
      )}
        </div>

        {scannerRailOpen && scan.tools.length > 0 && (
          <aside className={styles.scannerRail} aria-label="Scanner coverage">
            <div className={styles.sectionTitle}><strong>Scanner coverage</strong><span>Counts are scanner-specific raw detections and may overlap. The remediation list is deduplicated.</span></div>
            <div className={styles.toolStrip}>
              {scan.tools.map((tool) => {
                const { Icon, tone } = toolStatusVisual(tool)
                return (
                  <div key={tool.name} className={`${styles.toolCard} ${styles[`tool-${tone}`]}`} title={tool.error || TOOL_HELP[tool.name] || tool.name}>
                    <Icon aria-hidden="true" className={tone === 'running' ? styles.spin : ''} />
                    <div><strong>{tool.name}</strong><span>{toolStatusLabel(tool)}</span></div>
                    {tool.error && <p>{tool.error}</p>}
                  </div>
                )
              })}
            </div>
          </aside>
        )}
      </div>
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
          <AnimatedEmptyVisual variant="security" />
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
          <AnimatedEmptyVisual variant="security" />
          <APP_ICONS.security aria-hidden="true" />
          <p>No repo has been scanned yet</p>
          <p className="text-muted">Run a scan on a repo below to check it for exploitable security issues.</p>
        </div>
      )}

      {data.repos.map((repo) => (
        <RepoSecurityCard key={repo.repo_id} projectId={project.id} repo={repo} onScanTriggered={() => void load()} />
      ))}

      <PrSecurityPanel project={project} />

      <p className={styles.footnote}>
        <ShieldAlert aria-hidden="true" /> Source scanners provide the evidence; AI explains and correlates it. ZAP runtime testing is not enabled yet.
      </p>
    </section>
  )
}
