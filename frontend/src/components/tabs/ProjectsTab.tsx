import { useEffect, useState } from 'react'
import { AlertCircle, FolderKanban, GitBranch, Layers3, Plus, Settings } from 'lucide-react'
import { ApiError, createProject, listProjects } from '../../api/client'
import type { ProjectListItem } from '../../types'
import { useToast } from '../../hooks/useToast'
import { formatDate, formatRelative } from '../../lib/format'
import { SkeletonList } from '../Skeleton'
import styles from './ProjectsTab.module.css'

/** Which project is open lives in the URL (/app/projects/:id), not in local state —
 * opening one used to have no address, so it could not be shared, reloaded, opened in
 * a second tab, or backed out of with the browser's own Back button. */
export function ProjectsTab({
  onOpenProject,
  onOpenSettings,
}: {
  onOpenProject: (projectId: number) => void
  onOpenSettings?: (projectId: number) => void
}) {
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [creating, setCreating] = useState(false)
  const { showToast } = useToast()

  async function load() {
    try {
      const data = await listProjects()
      setProjects(data.projects)
    } catch {
      setProjects([])
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function handleCreate() {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const project = await createProject(newName.trim(), newDescription.trim())
      setNewName('')
      setNewDescription('')
      await load()
      onOpenProject(project.id)
    } catch (e) {
      showToast('Failed to create project', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setCreating(false)
    }
  }

  const totals = projects?.reduce(
    (sum, project) => ({
      backlogs: sum.backlogs + project.generation_count,
      repos: sum.repos + project.repo_count,
      needsSetup: sum.needsSetup + (project.repo_count === 0 ? 1 : 0),
    }),
    { backlogs: 0, repos: 0, needsSetup: 0 },
  )

  return (
    <div className={styles.workspace}>
      {projects !== null && (
        <section className={styles.summary} aria-label="Workspace summary">
          <div className={styles.summaryIntro}>
            <span className={styles.eyebrow}>Manager workspace</span>
            <h2>Everything moving across your products</h2>
            <p>Open a project to review its backlog, quality, repository context, and delivery details.</p>
          </div>
          <div className={styles.metrics}>
            <div className={styles.metric}>
              <span className={styles.metricIcon}><FolderKanban aria-hidden="true" /></span>
              <div><strong>{projects.length}</strong><span>Projects</span></div>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricIcon}><Layers3 aria-hidden="true" /></span>
              <div><strong>{totals?.backlogs ?? 0}</strong><span>Backlogs</span></div>
            </div>
            <div className={styles.metric}>
              <span className={styles.metricIcon}><GitBranch aria-hidden="true" /></span>
              <div><strong>{totals?.repos ?? 0}</strong><span>Linked repos</span></div>
            </div>
            <div className={`${styles.metric} ${totals?.needsSetup ? styles.metricAttention : ''}`}>
              <span className={styles.metricIcon}><AlertCircle aria-hidden="true" /></span>
              <div><strong>{totals?.needsSetup ?? 0}</strong><span>Need repo setup</span></div>
            </div>
          </div>
        </section>
      )}

      <section className={`card ${styles.createPanel}`}>
        <div className={styles.createCopy}>
          <h3>Create a project</h3>
          <p className="field-hint">Start with the product context. A repository can be linked later.</p>
        </div>
        <div className={styles.createRow}>
          <input
            className="text-input"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Project name"
            aria-label="Project name"
            disabled={creating}
          />
          <input
            className="text-input"
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
            placeholder="Description (optional)"
            aria-label="Project description"
            disabled={creating}
          />
          <button className="btn btn-primary" disabled={creating || !newName.trim()} onClick={() => void handleCreate()}>
            {creating ? <span className="btn-spinner" /> : <Plus aria-hidden="true" />}
            {creating ? 'Creating…' : 'New project'}
          </button>
        </div>
      </section>

      <div className={styles.sectionHeading}>
        <div>
          <h2>Your projects</h2>
          <p>Choose a product workspace to continue planning and delivery.</p>
        </div>
      </div>

      {projects === null ? (
        <div className="card"><SkeletonList /></div>
      ) : projects.length === 0 ? (
        <div className={`card ${styles.emptyState}`}>
          <FolderKanban aria-hidden="true" />
          <strong>No projects yet</strong>
          <p className="text-muted">Create your first project above. Repositories are optional.</p>
        </div>
      ) : (
        <div className={styles.list}>
          {projects.map((project) => (
            <div
              key={project.id}
              className={styles.item}
              onClick={() => onOpenProject(project.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onOpenProject(project.id)
                }
              }}
            >
              <div className={styles.cardTop}>
                <div className={styles.topBadges}>
                  {project.ticket_prefix ? (
                    <span className={styles.ticketPrefix}>{project.ticket_prefix}</span>
                  ) : (
                    <span className="badge badge-neutral">No prefix</span>
                  )}
                </div>
                <span className={styles.date} title={formatDate(project.created_at)}>
                  {formatRelative(project.created_at)}
                </span>
              </div>
              <div className={styles.name}>{project.name}</div>
              <div className={styles.cardBottom}>
                <div className={styles.score}>
                  {project.generation_count} backlog{project.generation_count === 1 ? '' : 's'} · {project.repo_count} repo
                  {project.repo_count === 1 ? '' : 's'}
                </div>
                <button
                  type="button"
                  className={styles.settingsBtn}
                  title="Configure project settings"
                  onClick={(e) => {
                    e.stopPropagation()
                    onOpenSettings?.(project.id)
                  }}
                >
                  <Settings aria-hidden="true" />
                  <span>Settings</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
