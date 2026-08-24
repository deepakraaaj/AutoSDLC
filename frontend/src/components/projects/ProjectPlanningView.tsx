import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, Plus, Save, Trash2 } from 'lucide-react'
import { ApiError, createProjectSprint, deleteProjectSprint, listProjectSprints, updateProjectSprint } from '../../api/client'
import type { GenerationOutput, Hierarchy, ProjectDetail, SprintPlan, SprintPlanInput, SprintStatus } from '../../types'
import { phaseContent } from '../../lib/phases'
import { useToast } from '../../hooks/useToast'
import { Modal } from '../Modal'
import styles from './ProjectPlanningView.module.css'

const hours = (value: string) => Number.parseFloat(value) || 0
function blank(): SprintPlanInput {
  const start = new Date(), end = new Date(); end.setDate(end.getDate() + 13)
  return { name: '', objective: '', start_date: start.toISOString().slice(0, 10), end_date: end.toISOString().slice(0, 10), capacity_hours: 80, story_ids: [], status: 'draft' }
}

export function ProjectPlanningView({ project, output, hierarchy, onOpenStoryHierarchy }: { project: ProjectDetail; output: GenerationOutput; hierarchy: Hierarchy | null; onOpenStoryHierarchy: (storyId: string) => void }) {
  const content = phaseContent(output, hierarchy)
  const [sprints, setSprints] = useState<SprintPlan[] | null>(null)
  const [activeId, setActiveId] = useState<number | 'new'>('new')
  const [form, setForm] = useState<SprintPlanInput>(blank)
  const [saving, setSaving] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDuration, setNewDuration] = useState(14)
  const [newCapacity, setNewCapacity] = useState(80)
  const [scopeView, setScopeView] = useState<'selected' | 'all'>('all')
  const [expandedStoryId, setExpandedStoryId] = useState<string | null>(null)
  const [deleteArmed, setDeleteArmed] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const { showToast } = useToast()
  const rows = useMemo(() => content.stories.map(({ epic, story }) => ({ epic, story, estimate: story.tasks.reduce((n, t) => n + hours(t.estimateHours), 0), deps: story.tasks.reduce((n, t) => n + t.dependencies.length, 0) })), [content.stories])
  const selected = rows.filter(({ story }) => form.story_ids.includes(story.id))
  const scopeHours = selected.reduce((n, row) => n + row.estimate, 0)
  const dependencies = selected.reduce((n, row) => n + row.deps, 0)
  const unassigned = selected.reduce((n, row) => n + row.story.tasks.filter((t) => !t.assignee).length, 0)
  const overCapacity = form.capacity_hours > 0 && scopeHours > form.capacity_hours

  function choose(s: SprintPlan) {
    setActiveId(s.id); setForm({ name: s.name, objective: s.objective, start_date: s.start_date, end_date: s.end_date, capacity_hours: s.capacity_hours, story_ids: s.story_ids, status: s.status }); setScopeView('selected')
  }
  async function load(preferred?: number) {
    const data = await listProjectSprints(project.id); setSprints(data.sprints)
    const target = data.sprints.find((s) => s.id === preferred) ?? data.sprints[0]; if (target) choose(target)
  }
  useEffect(() => { void load().catch((e) => showToast('Planning failed to load', e instanceof ApiError ? e.message : 'Unknown error', 'error'))
    // Loading is keyed to the selected project; callbacks deliberately use the current render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])
  const toggle = (id: string) => setForm((f) => ({ ...f, story_ids: f.story_ids.includes(id) ? f.story_ids.filter((x) => x !== id) : [...f.story_ids, id] }))

  function continueNewSprint() {
    if (!newName.trim()) return
    const next = blank()
    const end = new Date(`${next.start_date}T00:00:00`)
    end.setDate(end.getDate() + newDuration - 1)
    setActiveId('new')
    setForm({ ...next, name: newName.trim(), end_date: end.toISOString().slice(0, 10), capacity_hours: newCapacity })
    setScopeView('all')
    setNewOpen(false)
  }

  async function save() {
    if (!form.name.trim()) return showToast('Sprint name required', 'Give the plan a clear name.', 'warning')
    if (form.end_date < form.start_date) return showToast('Invalid dates', 'End date must follow start date.', 'warning')
    if (!form.story_ids.length) return showToast('No scope selected', 'Select at least one story.', 'warning')
    setSaving(true)
    try {
      const payload = { ...form, name: form.name.trim(), objective: form.objective.trim() }
      const saved = activeId === 'new' ? await createProjectSprint(project.id, payload) : await updateProjectSprint(project.id, activeId, payload)
      await load(saved.id); showToast('Sprint plan saved', `${saved.story_ids.length} stories committed to ${saved.name}.`, 'info')
    } catch (e) { showToast('Failed to save sprint', e instanceof ApiError ? e.message : 'Unknown error', 'error') } finally { setSaving(false) }
  }

  async function removeSprint() {
    if (activeId === 'new') return
    if (!deleteArmed) { setDeleteArmed(true); return }
    setDeleting(true)
    try {
      await deleteProjectSprint(project.id, activeId)
      setActiveId('new'); setForm(blank()); setScopeView('all'); setDeleteArmed(false)
      const data = await listProjectSprints(project.id); setSprints(data.sprints)
      if (data.sprints[0]) choose(data.sprints[0])
      showToast('Sprint deleted', 'The saved sprint plan was removed.', 'info')
    } catch (e) { showToast('Failed to delete sprint', e instanceof ApiError ? e.message : 'Unknown error', 'error') } finally { setDeleting(false) }
  }

  return <section className={styles.simplePage}>
    <header className={styles.simpleHeader}>
      <div><h2>Sprint planning</h2><p>Pick a sprint, choose its stories, and save.</p></div>
      <div className={styles.sprintPicker}>
        <button className="btn btn-primary btn-sm" onClick={() => { setNewName(`Sprint ${(sprints?.length ?? 0) + 1}`); setNewOpen(true) }}><Plus /> New sprint</button>
      </div>
    </header>

    <nav className={styles.savedSprints} aria-label="Saved sprints">
      <div><strong>Saved sprints</strong><span>{sprints?.length ?? 0}</span></div>
      <div className={styles.savedSprintList}>
        {sprints === null ? <span className={styles.savedEmpty}>Loading…</span> : sprints.length === 0 ? <span className={styles.savedEmpty}>No saved sprints yet</span> : sprints.map((sprint) => (
          <button key={sprint.id} className={activeId === sprint.id ? styles.savedSprintActive : ''} onClick={() => choose(sprint)}>
            <span>{sprint.name}</span><small>{sprint.start_date} → {sprint.end_date}</small><em>{sprint.status}</em>
          </button>
        ))}
      </div>
    </nav>

    {form.name && <div className={styles.currentSprint}><div><strong>{form.name}</strong><span>{form.start_date} → {form.end_date}</span></div><div className={styles.currentSprintActions}><span>{form.capacity_hours}h capacity</span>{activeId !== 'new' && <button className={`${styles.deleteSprint} ${deleteArmed ? styles.deleteSprintArmed : ''}`} disabled={deleting} onClick={() => void removeSprint()} onBlur={() => { if (!deleting) setDeleteArmed(false) }}><Trash2 aria-hidden="true" />{deleting ? 'Deleting…' : deleteArmed ? 'Confirm delete?' : 'Delete sprint'}</button>}</div></div>}

    <details className={styles.advanced}>
      <summary>Edit sprint settings</summary>
      <div className={styles.settingsGrid}><label className="field-label">Name<input className="text-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label className="field-label">Status<select className="select" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as SprintStatus })}><option value="draft">Draft</option><option value="approved">Approved</option><option value="active">Active</option><option value="completed">Completed</option></select></label><label className="field-label">Starts<input className="text-input" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></label><label className="field-label">Ends<input className="text-input" type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></label><label className="field-label">Capacity<input className="text-input" type="number" min="0" value={form.capacity_hours} onChange={(e) => setForm({ ...form, capacity_hours: Number(e.target.value) })} /></label><label className={`field-label ${styles.objectiveField}`}>Objective<textarea className="text-input" rows={2} value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} placeholder="Optional sprint outcome" /></label></div>
    </details>

    <div className={styles.scopeHeader}><div><h3>Sprint stories</h3><p>{form.story_ids.length} selected from {rows.length} available</p></div><div className={styles.scopeActions}><div className={styles.scopeToggle}><button className={scopeView === 'selected' ? styles.scopeToggleActive : ''} onClick={() => setScopeView('selected')}>Selected ({form.story_ids.length})</button><button className={scopeView === 'all' ? styles.scopeToggleActive : ''} onClick={() => setScopeView('all')}>All stories</button></div><button className={styles.clearButton} disabled={!form.story_ids.length} onClick={() => setForm({ ...form, story_ids: [] })}>Clear</button></div></div>
    <div className={styles.simpleStoryList}>{(scopeView === 'selected' ? rows.filter(({ story }) => form.story_ids.includes(story.id)) : rows).map(({ epic, story, estimate, deps }) => {
      const checked = form.story_ids.includes(story.id)
      const expanded = expandedStoryId === story.id
      return <article key={story.key} className={`${styles.storyCard} ${checked ? styles.storySelected : ''}`}>
        <div className={styles.storyRow}>
          <button className={styles.check} onClick={() => toggle(story.id)} aria-label={checked ? `Remove ${story.title} from sprint` : `Add ${story.title} to sprint`} aria-pressed={checked}>{checked && <Check/>}</button>
          <button className={styles.storyCopy} onClick={() => setExpandedStoryId(expanded ? null : story.id)} onDoubleClick={() => onOpenStoryHierarchy(story.id)} aria-expanded={expanded} title="Click to preview · Double-click to open in Hierarchy">
            <small>{epic.id} · {story.id}</small><strong>{story.title}</strong><span>{Math.round(estimate)}h · {story.tasks.length} tasks{deps ? ` · ${deps} dependencies` : ''}</span>
          </button>
          <span className={`badge badge-${story.priority === 'high' || story.priority === 'critical' ? 'warning' : 'neutral'}`}>{story.priority}</span>
        </div>
        {expanded && <div className={styles.storyHierarchy}>
          <div className={styles.hierarchyLabel}><span>{epic.id}</span><span>→</span><strong>{story.id}</strong></div>
          {story.tasks.length === 0 ? <p>No implementation tasks yet.</p> : story.tasks.map((task) => <div key={task.key} className={styles.taskNode}><span className={styles.taskLine}/><div><small>{task.id}</small><strong>{task.title}</strong><span>{task.estimateHours} · {task.status}{task.assignee ? ` · ${task.assignee}` : ' · Unassigned'}</span></div></div>)}
        </div>}
      </article>
    })}</div>
    {scopeView === 'selected' && form.story_ids.length === 0 && <div className={styles.noScope}><strong>No stories selected</strong><span>Switch to All stories to add work to this sprint.</span><button className="btn btn-secondary btn-sm" onClick={() => setScopeView('all')}>Browse backlog</button></div>}

    <footer className={styles.saveBar}>
      <div className={styles.compactSummary}><span><strong>{form.story_ids.length}</strong> stories</span><span className={overCapacity ? styles.over : ''}><strong>{Math.round(scopeHours)}h</strong> / {form.capacity_hours}h</span>{unassigned > 0 && <span>{unassigned} unassigned</span>}{dependencies > 0 && <span>{dependencies} dependencies</span>}</div>
      {overCapacity && <span className={styles.capacityWarning}><AlertTriangle /> Over by {Math.ceil(scopeHours - form.capacity_hours)}h</span>}
      <button className="btn btn-primary" disabled={saving} onClick={() => void save()}>{saving ? <span className="btn-spinner"/> : <Save/>}{saving ? 'Saving…' : 'Save sprint'}</button>
    </footer>
    <Modal open={newOpen} onClose={() => setNewOpen(false)} title="New sprint" subheader="Set the basics, then choose the work.">
      <div className={styles.newSprintForm}>
        <label className="field-label">Sprint name<input className="text-input" autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} /></label>
        <label className="field-label">Duration<select className="select" value={newDuration} onChange={(e) => setNewDuration(Number(e.target.value))}><option value={7}>1 week</option><option value={14}>2 weeks</option><option value={21}>3 weeks</option><option value={28}>4 weeks</option></select></label>
        <label className="field-label">Team capacity<input className="text-input" type="number" min="0" value={newCapacity} onChange={(e) => setNewCapacity(Number(e.target.value))} /><span className="field-hint">Total available hours for this sprint.</span></label>
        <div className={styles.newSprintActions}><button className="btn btn-ghost" onClick={() => setNewOpen(false)}>Cancel</button><button className="btn btn-primary" disabled={!newName.trim()} onClick={continueNewSprint}>Continue to scope</button></div>
      </div>
    </Modal>
  </section>
}
