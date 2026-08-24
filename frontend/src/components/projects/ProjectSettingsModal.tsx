import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import { Skeleton, SkeletonList } from '../Skeleton'
import {
  addProjectRepo,
  ApiError,
  deleteProject,
  deleteProjectRepo,
  getProject,
  getProjectSettings,
  updateProject,
  updateProjectRepo,
  updateProjectSettings,
} from '../../api/client'
import type { ProjectDetail, ProjectSettings } from '../../types'
import { useToast } from '../../hooks/useToast'
import { formatDate } from '../../lib/format'
import styles from './ProjectSettingsModal.module.css'

type SectionId = 'general' | 'repositories' | 'instructions' | 'delete-project'

/** Bitbucket Cloud's web URL is deterministic from workspace + repo slug —
 * no separate stored field needed. (Self-hosted Bitbucket Server/Data Center
 * uses a different URL shape entirely, but this app only targets Cloud;
 * see bitbucket/client.py's DEFAULT_BASE_URL.) */
function bitbucketRepoUrl(workspace: string, repoSlug: string): string {
  return `https://bitbucket.org/${workspace}/${repoSlug}`
}

/** Pulls {workspace, repoSlug} out of anything someone would reasonably
 * paste from Bitbucket's "Clone" button or address bar:
 *   git@bitbucket.org:workspace/repo.git   (SSH)
 *   ssh://git@bitbucket.org/workspace/repo.git
 *   https://bitbucket.org/workspace/repo.git
 *   https://bitbucket.org/workspace/repo
 *   workspace/repo                          (already the short form)
 * Returns null if none of those match. */
function parseBitbucketRepoUrl(input: string): { workspace: string; repoSlug: string } | null {
  const trimmed = input.trim()
  const patterns = [
    /^git@bitbucket\.org:([^/]+)\/([^/]+?)(\.git)?$/,
    /^ssh:\/\/git@bitbucket\.org\/([^/]+)\/([^/]+?)(\.git)?$/,
    /^https?:\/\/(?:[^@/]+@)?bitbucket\.org\/([^/]+)\/([^/]+?)(\.git)?\/?$/,
    /^([^/\s]+)\/([^/\s]+?)(\.git)?$/,
  ]
  for (const pattern of patterns) {
    const match = trimmed.match(pattern)
    if (match) return { workspace: match[1], repoSlug: match[2] }
  }
  return null
}

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'repositories', label: 'Linked Repos' },
  { id: 'instructions', label: 'Instructions' },
  { id: 'delete-project', label: 'Delete Project' },
]

export function ProjectSettingsModal({
  open,
  projectId,
  onClose,
  onDeleted,
}: {
  open: boolean
  projectId: number | null
  onClose: () => void
  onDeleted: () => void
}) {
  const [section, setSection] = useState<SectionId>('general')
  const [detail, setDetail] = useState<ProjectDetail | null>(null)
  const [settings, setSettings] = useState<ProjectSettings | null>(null)
  const { showToast } = useToast()

  async function load() {
    if (projectId == null) return
    try {
      const [d, s] = await Promise.all([getProject(projectId), getProjectSettings(projectId)])
      setDetail(d)
      setSettings(s)
    } catch (e) {
      showToast('Failed to load project', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    }
  }

  useEffect(() => {
    if (open && projectId != null) {
      setSection('general')
      void load()
    } else {
      setDetail(null)
      setSettings(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, projectId])

  if (!open || projectId == null) return null

  return (
    <Modal open={open} onClose={onClose} title="Project Settings" subheader={detail?.name}>
      {!detail || !settings ? (
        <div style={{ padding: 'var(--space-4)' }} aria-busy="true">
          <Skeleton width="40%" height={20} />
          <div style={{ height: 'var(--space-4)' }} />
          <SkeletonList rows={2} />
        </div>
      ) : (
        <div className={styles.container}>
          <nav className={styles.nav} aria-label="Project settings sections">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`${styles.navItem} ${section === s.id ? styles.navItemActive : ''}`}
                onClick={() => setSection(s.id)}
              >
                {s.label}
              </button>
            ))}
          </nav>

          <div className={styles.content}>
            {section === 'general' && <GeneralSection detail={detail} onChanged={load} />}
            {section === 'repositories' && <RepositoriesSection detail={detail} onChanged={load} />}
            {section === 'instructions' && <InstructionsSection projectId={projectId} settings={settings} onChanged={load} />}
            {section === 'delete-project' && <DeleteProjectSection projectId={projectId} onDeleted={onDeleted} />}
          </div>
        </div>
      )}
    </Modal>
  )
}

function GeneralSection({ detail, onChanged }: { detail: ProjectDetail; onChanged: () => void }) {
  const [name, setName] = useState(detail.name)
  const [savingName, setSavingName] = useState(false)
  const { showToast } = useToast()

  async function saveName() {
    if (!name.trim()) return
    setSavingName(true)
    try {
      await updateProject(detail.id, { name: name.trim() })
      onChanged()
      showToast('Saved', '', 'info')
    } catch (e) {
      showToast('Failed to save', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setSavingName(false)
    }
  }

  return (
    <>
      <h3>General</h3>
      <p className="field-hint">Rename this project.</p>
      <div className={styles.grid}>
        <div className={styles.card}>
          <label className="field-label">Name</label>
          <div className={styles.inlineRow}>
            <input className="text-input" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn btn-secondary btn-sm" disabled={savingName || !name.trim()} onClick={() => void saveName()}>
              {savingName ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function RepositoriesSection({ detail, onChanged }: { detail: ProjectDetail; onChanged: () => void }) {
  const [repoUrl, setRepoUrl] = useState('')
  const [label, setLabel] = useState('')
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editRepoUrl, setEditRepoUrl] = useState('')
  const [editLabel, setEditLabel] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const { showToast } = useToast()

  const verifiedCount = detail.repos.filter((r) => r.verified_at).length

  async function handleAdd() {
    const parsed = parseBitbucketRepoUrl(repoUrl)
    if (!parsed) {
      showToast('Not a recognized repo URL', 'Paste the SSH or HTTPS clone URL from Bitbucket, e.g. git@bitbucket.org:workspace/repo.git', 'error')
      return
    }
    setAdding(true)
    try {
      const repo = await addProjectRepo(detail.id, { workspace: parsed.workspace, repo_slug: parsed.repoSlug, label: label.trim() })
      setRepoUrl('')
      setLabel('')
      onChanged()
      if (repo.verification.attempted) {
        showToast(
          repo.verification.ok ? 'Repo linked and verified' : 'Repo linked, not verified',
          repo.verification.ok ? '' : repo.verification.error || 'Could not confirm access — still linked.',
          repo.verification.ok ? 'info' : 'warning',
        )
      }
    } catch (e) {
      showToast('Failed to add repo', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setAdding(false)
    }
  }

  async function handleDelete(repoId: number) {
    if (pendingDeleteId !== repoId) {
      setPendingDeleteId(repoId)
      return
    }
    setDeletingId(repoId)
    try {
      await deleteProjectRepo(detail.id, repoId)
      setPendingDeleteId(null)
      onChanged()
    } catch (e) {
      showToast('Failed to remove repo', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setDeletingId(null)
    }
  }

  function startEdit(repo: ProjectDetail['repos'][number]) {
    setEditingId(repo.id)
    setEditRepoUrl(bitbucketRepoUrl(repo.workspace, repo.repo_slug))
    setEditLabel(repo.label || '')
  }

  function cancelEdit() {
    setEditingId(null)
  }

  async function handleSaveEdit(repoId: number) {
    const parsed = parseBitbucketRepoUrl(editRepoUrl)
    if (!parsed) {
      showToast('Not a recognized repo URL', 'Paste the SSH or HTTPS clone URL from Bitbucket, e.g. git@bitbucket.org:workspace/repo.git', 'error')
      return
    }
    setSavingEdit(true)
    try {
      await updateProjectRepo(detail.id, repoId, {
        workspace: parsed.workspace,
        repo_slug: parsed.repoSlug,
        label: editLabel.trim(),
      })
      setEditingId(null)
      onChanged()
      showToast('Repo updated', 'Verification will be re-checked next time you push.', 'info')
    } catch (e) {
      showToast('Failed to update repo', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setSavingEdit(false)
    }
  }

  return (
    <>
      <h3>Linked Repos</h3>
      <p className="field-hint">
        Which Bitbucket repos this project reads context from and pushes/reviews against. Entirely optional — leave this
        empty and pushes fall back to the server's default repo. Paste the repo's clone URL (SSH or HTTPS) from
        Bitbucket's "Clone" button.
      </p>
      {detail.repos.length > 0 && (
        <p className="field-hint" style={{ marginBottom: 'var(--space-3)' }}>
          {detail.repos.length} linked, {verifiedCount} confirmed reachable.
        </p>
      )}

      {detail.repos.length > 0 && (
        <div className={styles.repoTable}>
          {detail.repos.map((repo) =>
            editingId === repo.id ? (
              <div key={repo.id} className={`${styles.repoRow} ${styles.repoRowEditing}`}>
                <input
                  className="text-input"
                  value={editRepoUrl}
                  onChange={(e) => setEditRepoUrl(e.target.value)}
                  placeholder="git@bitbucket.org:workspace/repo.git"
                  disabled={savingEdit}
                />
                <input
                  className="text-input"
                  value={editLabel}
                  onChange={(e) => setEditLabel(e.target.value)}
                  placeholder="label (e.g. frontend)"
                  disabled={savingEdit}
                />
                <button
                  className="btn btn-primary btn-sm"
                  disabled={savingEdit || !editRepoUrl.trim()}
                  onClick={() => void handleSaveEdit(repo.id)}
                >
                  {savingEdit ? 'Saving…' : 'Save'}
                </button>
                <button className="btn btn-ghost btn-sm" disabled={savingEdit} onClick={cancelEdit}>
                  Cancel
                </button>
              </div>
            ) : (
              <div key={repo.id} className={styles.repoRow}>
                <span className={`${styles.dot} ${repo.verified_at ? styles.dotOk : styles.dotUnknown}`} title={repo.verified_at ? `Verified ${formatDate(repo.verified_at)}` : 'Not verified'} />
                <a
                  className={styles.repoName}
                  href={bitbucketRepoUrl(repo.workspace, repo.repo_slug)}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Open in Bitbucket"
                >
                  {repo.label ? `${repo.label}: ` : ''}
                  {repo.workspace}/{repo.repo_slug}
                </a>
                <button className="btn btn-ghost btn-sm" onClick={() => startEdit(repo)}>
                  Edit
                </button>
                <button
                  className={`btn btn-sm ${pendingDeleteId === repo.id ? 'btn-danger' : 'btn-ghost'}`}
                  disabled={deletingId !== null}
                  onClick={() => void handleDelete(repo.id)}
                  onBlur={() => {
                    if (deletingId !== repo.id) setPendingDeleteId(null)
                  }}
                >
                  {deletingId === repo.id ? 'Removing…' : pendingDeleteId === repo.id ? 'Confirm remove?' : 'Remove'}
                </button>
              </div>
            ),
          )}
        </div>
      )}

      <div className={styles.addRow}>
        <input
          className="text-input"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          placeholder="git@bitbucket.org:workspace/repo.git"
          disabled={adding}
        />
        <input className="text-input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="label (e.g. frontend)" disabled={adding} />
        <button className="btn btn-primary btn-sm" disabled={adding || !repoUrl.trim()} onClick={() => void handleAdd()}>
          {adding ? 'Adding & verifying…' : '+ Add repository'}
        </button>
      </div>
    </>
  )
}

function InstructionsSection({ projectId, settings, onChanged }: { projectId: number; settings: ProjectSettings; onChanged: () => void }) {
  const [instructions, setInstructions] = useState(settings.custom_instructions || '')
  const [saving, setSaving] = useState(false)
  const { showToast } = useToast()

  async function handleSave() {
    setSaving(true)
    try {
      await updateProjectSettings(projectId, { custom_instructions: instructions.trim() || null })
      onChanged()
      showToast('Saved', '', 'info')
    } catch (e) {
      showToast('Failed to save', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <h3>Instructions</h3>
      <p className="field-hint">
        Applied when regenerating stories, tasks, or test cases for this project.
      </p>
      <textarea
        className={styles.textarea}
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        placeholder="e.g. Use snake_case for API field names. Every story needs a mobile-specific acceptance criterion."
        rows={5}
      />
      <button className="btn btn-primary btn-sm" disabled={saving} onClick={() => void handleSave()}>
        {saving ? 'Saving…' : 'Save instructions'}
      </button>
    </>
  )
}

function DeleteProjectSection({ projectId, onDeleted }: { projectId: number; onDeleted: () => void }) {
  const [armed, setArmed] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const { showToast } = useToast()

  async function handleDelete() {
    if (!armed) {
      setArmed(true)
      return
    }
    setDeleting(true)
    try {
      await deleteProject(projectId)
      showToast('Project deleted', 'Backlogs generated under it are untouched.', 'info')
      onDeleted()
    } catch (e) {
      showToast('Failed to delete project', e instanceof ApiError ? e.message : 'Unknown error', 'error')
      setDeleting(false)
    }
  }

  return (
    <>
      <h3>Delete Project</h3>
      <div className={styles.dangerCard}>
        <div>
          <strong>This can't be undone</strong>
          <p className="field-hint">
            Deletes the project along with its repo links and settings. Backlogs already generated under it stick around.
          </p>
        </div>
        <button
          className={`btn btn-sm ${armed ? 'btn-danger' : 'btn-secondary'}`}
          disabled={deleting}
          onClick={() => void handleDelete()}
          onBlur={() => setArmed(false)}
        >
          {deleting ? 'Deleting…' : armed ? 'Confirm delete?' : 'Delete project'}
        </button>
      </div>
    </>
  )
}
