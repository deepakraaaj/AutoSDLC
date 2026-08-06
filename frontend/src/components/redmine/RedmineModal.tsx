import { useEffect, useState } from 'react'
import {
  ApiError,
  createRedmineProject,
  listRedmineProjects,
  pushToRedmine,
} from '../../api/client'
import { getSavedRedmineConfig as getSavedConfig, saveRedmineConfig as saveConfig } from '../../lib/redmineConfig'
import type { GenerationOutput, RedmineDefaults, RedmineProjectOption, RedminePushResult } from '../../types'
import { Modal } from '../Modal'
import styles from './RedmineModal.module.css'

function browserIssueUrl(configuredUrl: string, issueId?: number): string {
  if (!issueId) return '#'
  // The API runs inside Docker and needs host.docker.internal, while links are
  // opened by the host browser, where localhost is the correct local address.
  const browserBase = configuredUrl
    .replace('://host.docker.internal', '://localhost')
    .replace(/\/$/, '')
  return `${browserBase}/issues/${issueId}`
}

type StatusKind = 'idle' | 'loading' | 'success' | 'error'
const STATUS_CHIP: Record<StatusKind, string> = {
  idle: 'Waiting',
  loading: 'Connecting',
  success: 'Ready',
  error: 'Needs attention',
}

export interface RedmineScope {
  epicId: string
  label: string
}

export function RedmineModal({
  open,
  onClose,
  output,
  genId,
  scope = null,
  onPushed,
}: {
  open: boolean
  onClose: () => void
  output: GenerationOutput | null
  genId: number | null
  /** When set, pushes just this epic and everything under it instead of
   * the whole backlog — used from an epic/story/task detail view. Requires
   * genId (a scoped push always reads the epic branch from the saved
   * generation, not the raw client-side output). */
  scope?: RedmineScope | null
  onPushed: (result: RedminePushResult) => void
}) {
  const [url, setUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [projectOptions, setProjectOptions] = useState<RedmineProjectOption[]>([])
  const [defaults, setDefaults] = useState<RedmineDefaults | null>(null)
  const [selectedProject, setSelectedProject] = useState('')
  const [selectedEpicId, setSelectedEpicId] = useState('')
  const [status, setStatus] = useState<{ kind: StatusKind; title: string; message: string }>({
    kind: 'idle',
    title: 'Add Redmine details',
    message: 'Enter URL and API key to load projects.',
  })
  const [projectStatus, setProjectStatus] = useState<{ text: string; tone: '' | 'warn' | 'error' }>({
    text: '',
    tone: '',
  })
  const [loadingProjects, setLoadingProjects] = useState(false)
  const [creating, setCreating] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [createPanelOpen, setCreatePanelOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newIdentifier, setNewIdentifier] = useState('')
  const [newParent, setNewParent] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [result, setResult] = useState<RedminePushResult | null>(null)

  useEffect(() => {
    if (!open) return
    const saved = getSavedConfig()
    setUrl(saved.url)
    setApiKey(saved.key)
    setSelectedProject(saved.project)
    setSelectedEpicId(scope?.epicId || '')
    setProjectOptions([])
    setDefaults(null)
    setProjectStatus({ text: '', tone: '' })
    setCreatePanelOpen(false)
    setResult(null)
    if (saved.url && saved.key) {
      setStatus({ kind: 'loading', title: 'Connecting', message: 'Loading saved projects...' })
      void loadProjects(saved.url, saved.key, saved.project)
    } else {
      setStatus({ kind: 'idle', title: 'Add Redmine details', message: 'Enter URL and API key to load projects.' })
    }
    // Only re-run when the modal opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scope])

  async function loadProjects(u: string, k: string, preselect = '') {
    if (!u || !k) {
      setProjectStatus({ text: 'Enter Redmine URL and API key.', tone: 'warn' })
      setProjectOptions([])
      setDefaults(null)
      setStatus({ kind: 'idle', title: 'Add Redmine details', message: 'Enter URL and API key to load projects.' })
      return
    }
    setLoadingProjects(true)
    setProjectStatus({ text: 'Loading projects…', tone: '' })
    setStatus({ kind: 'loading', title: 'Connecting', message: 'Loading projects...' })
    try {
      const data = await listRedmineProjects(u, k)
      const options = data.project_options || []
      setProjectOptions(options)
      setDefaults(data.defaults || null)
      const saved = getSavedConfig()
      const desired = preselect || (options.some((o) => o.value === saved.project) ? saved.project : '')
      setSelectedProject(desired)
      saveConfig({ url: u.trim(), key: k.trim(), project: desired })
      const count = options.length
      const noun = count === 1 ? 'project' : 'projects'
      setProjectStatus({ text: count ? `Loaded ${count} projects.` : 'No projects returned.', tone: '' })
      const selectedLabel = options.find((o) => o.value === desired)?.label
      setStatus({
        kind: 'success',
        title: 'Connected',
        message: count
          ? desired && selectedLabel
            ? `${count} ${noun} loaded. Connection saved in this browser. Ready to push into ${selectedLabel}.`
            : `${count} ${noun} loaded. Connection saved in this browser. Choose a project.`
          : 'No projects returned.',
      })
    } catch (e) {
      setProjectOptions([])
      setDefaults(null)
      const message = e instanceof ApiError ? e.message : 'Failed to load projects'
      setProjectStatus({ text: `Failed to load projects: ${message}`, tone: 'error' })
      setStatus({ kind: 'error', title: 'Connection failed', message })
    } finally {
      setLoadingProjects(false)
    }
  }

  function handleCredentialsBlur() {
    setProjectOptions([])
    setDefaults(null)
    if (url.trim() && apiKey.trim()) {
      setProjectStatus({ text: 'Credentials updated. Connect again.', tone: 'warn' })
      setStatus({ kind: 'idle', title: 'Details updated', message: 'Click Connect to refresh projects.' })
    } else {
      setProjectStatus({ text: 'Enter Redmine URL and API key.', tone: 'warn' })
      setStatus({ kind: 'idle', title: 'Add Redmine details', message: 'Enter URL and API key to load projects.' })
    }
  }

  function handleProjectSelect(value: string) {
    setSelectedProject(value)
    if (url.trim() && apiKey.trim()) {
      saveConfig({ url: url.trim(), key: apiKey.trim(), project: value })
    }
    const label = projectOptions.find((o) => o.value === value)?.label
    if (value && label && !loadingProjects && !creating && !pushing) {
      setStatus({ kind: 'success', title: 'Project selected', message: `Ready to push into ${label}.` })
    }
  }

  async function handleCreateProject() {
    if (!url.trim() || !apiKey.trim()) {
      setProjectStatus({ text: 'Enter the Redmine URL and API key.', tone: 'error' })
      setStatus({ kind: 'idle', title: 'Connection required', message: 'Add URL and API key before creating a project.' })
      return
    }
    if (!newName.trim()) {
      setProjectStatus({ text: 'Project name is required.', tone: 'error' })
      setStatus({ kind: 'idle', title: 'Name required', message: 'Enter a project name before creating one.' })
      return
    }
    setCreating(true)
    setStatus({ kind: 'loading', title: 'Creating project', message: `Creating ${newName} and refreshing projects...` })
    try {
      const res = await createRedmineProject({
        redmine_url: url.trim(),
        redmine_api_key: apiKey.trim(),
        name: newName.trim(),
        identifier: newIdentifier.trim() || null,
        description: newDescription.trim(),
        parent_project_ref: newParent.trim() || null,
      })
      const created = res.project || {}
      const selection = String(created.identifier || newIdentifier || '')
      saveConfig({ url: url.trim(), key: apiKey.trim(), project: selection })
      setCreatePanelOpen(false)
      setNewName('')
      setNewIdentifier('')
      setNewParent('')
      setNewDescription('')
      await loadProjects(url.trim(), apiKey.trim(), selection)
      setProjectStatus({ text: `Created ${created.name || newName}.`, tone: '' })
      setStatus({ kind: 'success', title: 'Project created', message: `${created.name || newName} is selected.` })
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Failed to create project'
      setProjectStatus({ text: `Failed to create project: ${message}`, tone: 'error' })
      setStatus({ kind: 'error', title: 'Project creation failed', message })
    } finally {
      setCreating(false)
    }
  }

  async function handlePush() {
    if (!url.trim() || !apiKey.trim() || !selectedProject.trim()) {
      setProjectStatus({ text: 'Select a Redmine project or create one first.', tone: 'error' })
      setStatus({ kind: 'idle', title: 'Project required', message: 'Select or create a project before pushing.' })
      return
    }
    saveConfig({ url: url.trim(), key: apiKey.trim(), project: selectedProject.trim() })
    if (!output) {
      setStatus({ kind: 'error', title: 'Nothing to push', message: 'Generate stories and tasks first.' })
      return
    }
    const selectedEpic = output.epics.find((epic) => epic.id === selectedEpicId)
    const chosenEpicId = scope?.epicId || selectedEpic?.id || ''
    const chosenEpicLabel = scope?.label || selectedEpic?.title || ''
    if (chosenEpicId && !genId) {
      // Scoping only works against a saved generation (the backend resolves
      // the epic branch server-side) — silently falling back to a full,
      // unscoped push here would push everything instead of just this epic.
      setStatus({ kind: 'error', title: 'Cannot push yet', message: 'This generation needs to finish saving before you can push a single epic.' })
      return
    }
    setPushing(true)
    setStatus({
      kind: 'loading',
      title: chosenEpicId ? `Pushing "${chosenEpicLabel}"` : 'Pushing backlog',
      message: 'Creating issues...',
    })
    try {
      const res = await pushToRedmine({
        ...(genId ? { generation_id: genId } : { output }),
        ...(chosenEpicId ? { epic_id: chosenEpicId } : {}),
        redmine_url: url.trim(),
        redmine_api_key: apiKey.trim(),
        redmine_project_id: selectedProject.trim(),
      })
      const label = projectOptions.find((o) => o.value === selectedProject)?.label || 'the selected project'
      const createdCount = (res.created_issues || []).filter((i) => !i.error && i.status === 'created').length
      const skippedCount = (res.skipped_issues || []).length
      setStatus({
        kind: 'success',
        title: chosenEpicId ? `"${chosenEpicLabel}" pushed` : 'Backlog pushed',
        message: `Created ${createdCount} issue${createdCount === 1 ? '' : 's'} in ${label}${skippedCount ? `; skipped ${skippedCount} already synced` : ''}.`,
      })
      setResult(res)
      onPushed(res)
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Push failed'
      setProjectStatus({ text: `Push failed: ${message}`, tone: 'error' })
      setStatus({ kind: 'error', title: 'Push failed', message })
    } finally {
      setPushing(false)
    }
  }

  const busy = loadingProjects || creating || pushing
  const hasCreds = Boolean(url.trim() && apiKey.trim())
  const hasProjectOptions = projectOptions.length > 0
  const trustPassed = output?.validation?.trust_level === 'trusted'
  const failedTrustChecks = output?.validation?.checks.filter((check) => !check.passed) || []

  if (result) {
    return (
      <Modal open={open} onClose={() => setResult(null)} title="Created issues">
        <div className={styles.resultContent}>
          {(result.warnings || []).length > 0 && (
            <div className={styles.warningBlock}>
              {result.warnings!.map((w, i) => (
                <div key={i}>⚠ {w}</div>
              ))}
            </div>
          )}
          {result.created_issues.map((issue, i) =>
            issue.error ? (
              <div key={i} className={styles.errorLine}>
                ❌ {issue.type || 'Issue'}: {issue.error}
              </div>
            ) : (
              <div key={i} className={styles.okLine}>
                ✓ <strong>{issue.type}</strong> ({issue.display_id || issue.ai_id || issue.db_id}) →{' '}
                <a href={browserIssueUrl(url, issue.redmine_id)} target="_blank" rel="noreferrer">
                  View Issue #{issue.redmine_id} in Redmine ↗
                </a>
                {issue.redmine_priority_name ? ` · Priority: ${issue.redmine_priority_name}` : ''}
              </div>
            ),
          )}
          {(result.skipped_issues || []).map((issue, i) => (
            <div key={`skipped-${i}`} className={styles.okLine}>
              ↷ <strong>{issue.type}</strong> ({issue.ai_id}) — already synced as{' '}
              <a href={browserIssueUrl(url, issue.redmine_id)} target="_blank" rel="noreferrer">
                View Issue #{issue.redmine_id} in Redmine ↗
              </a>
            </div>
          ))}
        </div>
        <div className={styles.actions}>
          <button className="btn btn-primary btn-block" onClick={() => setResult(null)}>
            Done
          </button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Redmine"
      subheader={
        scope
          ? `Connect a workspace, pick a project, push "${scope.label}" and everything under it.`
          : 'Connect a workspace, pick a project, push the backlog.'
      }
      closeDisabled={pushing}
    >
      <div className={`${styles.statusCard} ${styles[status.kind]}`}>
        <div className={styles.statusChip}>{STATUS_CHIP[status.kind]}</div>
        <div className={styles.statusCopy}>
          <strong>{status.title}</strong>
          <p>{status.message}</p>
        </div>
        {status.kind === 'loading' && <div className={styles.spinner} aria-hidden="true" />}
      </div>

      <div className={`${styles.trustGate} ${trustPassed ? styles.trustPassed : styles.trustBlocked}`}>
        <div>
          <strong>{trustPassed ? '✓ Automated Trust Gate passed' : '⛔ Automated Trust Gate blocked sync'}</strong>
          <p>
            {trustPassed
              ? 'Coverage, story quality, task quality, gaps, and input quality passed independent validation.'
              : 'This backlog is not safe to publish automatically yet.'}
          </p>
        </div>
        {!trustPassed && failedTrustChecks.length > 0 && (
          <ul>
            {failedTrustChecks.map((check) => (
              <li key={check.label}>{check.label}: {check.value} (needs {check.threshold})</li>
            ))}
          </ul>
        )}
      </div>

      <div className={styles.grid}>
        <div>
          <label className="field-label">Redmine URL</label>
          <input
            className="text-input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onBlur={handleCredentialsBlur}
            placeholder="https://your-redmine.example.com"
          />
        </div>
        <div>
          <label className="field-label">API Key</label>
          <input
            className="text-input"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            onBlur={handleCredentialsBlur}
            placeholder="Your Redmine API key"
          />
        </div>
      </div>

      <div className={styles.toolbar}>
        <button
          className="btn btn-primary"
          disabled={busy || !hasCreds}
          onClick={() => void loadProjects(url.trim(), apiKey.trim())}
        >
          {loadingProjects && <span className="btn-spinner" />}
          {loadingProjects ? 'Connecting...' : 'Connect'}
        </button>
        <div className="field-hint" style={{ margin: 0 }}>
          We verify the connection before push is enabled.
        </div>
      </div>

      <div style={{ marginBottom: 'var(--space-4)' }}>
        <label className="field-label">Redmine Project</label>
        <select
          className="select"
          value={selectedProject}
          onChange={(e) => handleProjectSelect(e.target.value)}
          disabled={busy || !hasProjectOptions}
        >
          <option value="">{hasProjectOptions ? 'Select a project' : hasCreds ? 'Connect to load' : 'Enter credentials'}</option>
          {projectOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {projectStatus.text && (
          <div className={`field-hint ${projectStatus.tone ? `tone-${projectStatus.tone === 'warn' ? 'warn' : 'error'}` : ''}`}>
            {projectStatus.text}
          </div>
        )}
        {defaults && <DefaultsStatus defaults={defaults} />}
      </div>

      <div style={{ marginBottom: 'var(--space-4)' }}>
        <label className="field-label">What should be synced?</label>
        {scope ? (
          <div className="field-hint">This epic only: <strong>{scope.label}</strong>, including all its stories and tasks.</div>
        ) : (
          <>
            <select
              className="select"
              value={selectedEpicId}
              onChange={(e) => setSelectedEpicId(e.target.value)}
              disabled={busy}
            >
              <option value="">Entire backlog — all epics, stories, and tasks</option>
              {output?.epics.map((epic) => (
                <option key={epic.id} value={epic.id}>
                  Epic only — {epic.id}: {epic.title}
                </option>
              ))}
            </select>
            <div className="field-hint">
              Choose one epic for a focused sync, or the entire backlog when you are ready to publish everything.
            </div>
          </>
        )}
      </div>

      {!createPanelOpen ? (
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => {
            setCreatePanelOpen(true)
            if (selectedProject) setNewParent(selectedProject)
          }}
          style={{ marginBottom: 'var(--space-4)' }}
        >
          + New project
        </button>
      ) : (
        <div className={styles.createPanel}>
          <h4>Create project</h4>
          <div className={styles.grid}>
            <div>
              <label className="field-label">Project name</label>
              <input className="text-input" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Customer Portal" />
            </div>
            <div>
              <label className="field-label">Project identifier</label>
              <input
                className="text-input"
                value={newIdentifier}
                onChange={(e) => setNewIdentifier(e.target.value)}
                placeholder="customer-portal"
              />
            </div>
            <div>
              <label className="field-label">Parent project</label>
              <select className="select" value={newParent} onChange={(e) => setNewParent(e.target.value)}>
                <option value="">Root project</option>
                {projectOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="field-label">Description</label>
              <input
                className="text-input"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                placeholder="Delivery project"
              />
            </div>
          </div>
          <div className="field-hint">Adds Epic, Story, and Task trackers.</div>
          <div className={styles.actions}>
            <button className="btn btn-primary" disabled={busy || !hasCreds} onClick={() => void handleCreateProject()}>
              {creating && <span className="btn-spinner" />}
              {creating ? 'Creating project...' : 'Create'}
            </button>
            <button className="btn btn-secondary" onClick={() => setCreatePanelOpen(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className={styles.actions}>
        <button
          className="btn btn-primary"
          disabled={busy || !hasCreds || !selectedProject.trim() || !output || !trustPassed}
          onClick={() => void handlePush()}
        >
          {pushing && <span className="btn-spinner" />}
          {pushing
            ? 'Pushing to Redmine...'
            : scope
              ? `Sync epic: ${scope.label}`
              : selectedEpicId
                ? `Sync epic: ${output?.epics.find((epic) => epic.id === selectedEpicId)?.title || selectedEpicId}`
                : trustPassed
                  ? 'Sync entire backlog'
                  : 'Sync blocked by Trust Gate'}
        </button>
        <button className="btn btn-secondary" disabled={pushing} onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}

function DefaultsStatus({ defaults }: { defaults: RedmineDefaults }) {
  const missingTrackers = defaults.missing_trackers || []
  const missingTrackerDefaults = defaults.missing_tracker_defaults || []
  const missingFields = defaults.missing_custom_fields || []
  const messages: string[] = []
  if (missingTrackers.length) messages.push(`Missing trackers: ${missingTrackers.join(', ')}`)
  if (missingTrackerDefaults.length) messages.push(`Trackers missing default status: ${missingTrackerDefaults.join(', ')}`)
  if (missingFields.length) messages.push(`Missing custom fields: ${missingFields.join(', ')}`)

  return (
    <div className={`field-hint ${messages.length ? 'tone-warn' : ''}`}>
      {messages.length ? messages.join(' | ') : 'Trackers and fields are ready.'}
    </div>
  )
}
