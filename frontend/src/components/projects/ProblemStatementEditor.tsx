import { useState } from 'react'
import { AlertCircle, Plus, X } from 'lucide-react'
import { ApiError, createKnowledgeEntry, deleteKnowledgeEntry, updateKnowledgeEntry } from '../../api/client'
import type { KnowledgeEntry } from '../../types'
import { useToast } from '../../hooks/useToast'
import styles from './ProblemStatementEditor.module.css'
import kbStyles from './KnowledgeBaseView.module.css'

const OVERVIEW_TITLE = 'Problem Overview'
const IMPACT_TITLE = 'Impact Statement'
const PAIN_POINT_TITLE = 'Pain Point'

/** Problem Statement's own structured editor — replaces the generic
 * title+body "Add entry" form for this one kind with the three concrete
 * fields a problem statement actually has: a narrative Overview, a
 * quantified Impact, and a repeatable list of specific Pain Points. Each
 * field still saves as an ordinary KnowledgeEntry (title fixed to the field
 * name, business_context_kind: 'problem_statement') so citations
 * ("[KB-<id>]"), quality flagging, and generation grounding all keep working
 * unchanged — only the authoring surface is field-shaped instead of
 * freeform, matching how a real BRD's problem section is actually written. */
export function ProblemStatementEditor({
  projectId,
  entries,
  onChanged,
}: {
  projectId: number
  /** Already filtered to sdlc_area === 'Business Context' && business_context_kind === 'problem_statement'. */
  entries: KnowledgeEntry[]
  onChanged: () => void
}) {
  const { showToast } = useToast()
  const [savingOverview, setSavingOverview] = useState(false)
  const [savingImpact, setSavingImpact] = useState(false)
  const [overviewDraft, setOverviewDraft] = useState<string | null>(null)
  const [impactDraft, setImpactDraft] = useState<string | null>(null)
  const [addingPoint, setAddingPoint] = useState(false)

  const overviewEntry = entries.find((e) => e.title === OVERVIEW_TITLE) || null
  const impactEntry = entries.find((e) => e.title === IMPACT_TITLE) || null
  const painPoints = entries.filter((e) => e.title === PAIN_POINT_TITLE)

  async function saveSingleton(
    existing: KnowledgeEntry | null,
    title: string,
    body: string,
    setSaving: (v: boolean) => void,
  ) {
    const trimmed = body.trim()
    if (!trimmed) return
    setSaving(true)
    try {
      if (existing) {
        await updateKnowledgeEntry(projectId, existing.id, { body: trimmed })
      } else {
        await createKnowledgeEntry(projectId, {
          entry_type: 'glossary',
          title,
          sdlc_area: 'Business Context',
          business_context_kind: 'problem_statement',
          body: trimmed,
        })
      }
      onChanged()
    } catch (e) {
      showToast(`Failed to save ${title.toLowerCase()}`, e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function addPainPoint(text: string) {
    const trimmed = text.trim()
    if (!trimmed) return
    setAddingPoint(true)
    try {
      await createKnowledgeEntry(projectId, {
        entry_type: 'glossary',
        title: PAIN_POINT_TITLE,
        sdlc_area: 'Business Context',
        business_context_kind: 'problem_statement',
        body: trimmed,
      })
      onChanged()
    } catch (e) {
      showToast('Failed to add pain point', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setAddingPoint(false)
    }
  }

  async function updatePainPoint(entry: KnowledgeEntry, text: string) {
    const trimmed = text.trim()
    if (!trimmed) return
    try {
      await updateKnowledgeEntry(projectId, entry.id, { body: trimmed })
      onChanged()
    } catch (e) {
      showToast('Failed to update pain point', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    }
  }

  async function removePainPoint(entry: KnowledgeEntry) {
    try {
      await deleteKnowledgeEntry(projectId, entry.id)
      onChanged()
    } catch (e) {
      showToast('Failed to remove pain point', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    }
  }

  return (
    <div className={styles.editor}>
      <div className={kbStyles.formCard}>
        <div className={kbStyles.formField}>
          <label className={kbStyles.formLabel}>{OVERVIEW_TITLE}</label>
          <textarea
            className={kbStyles.textarea}
            value={overviewDraft ?? overviewEntry?.body ?? ''}
            onChange={(e) => setOverviewDraft(e.target.value)}
            onBlur={(e) => {
              setOverviewDraft(null)
              void saveSingleton(overviewEntry, OVERVIEW_TITLE, e.target.value, setSavingOverview)
            }}
            placeholder="Describe the context and the specific problem…"
            rows={3}
            disabled={savingOverview}
          />
        </div>
        <div className={kbStyles.formField}>
          <label className={kbStyles.formLabel}>{IMPACT_TITLE}</label>
          <textarea
            className={kbStyles.textarea}
            value={impactDraft ?? impactEntry?.body ?? ''}
            onChange={(e) => setImpactDraft(e.target.value)}
            onBlur={(e) => {
              setImpactDraft(null)
              void saveSingleton(impactEntry, IMPACT_TITLE, e.target.value, setSavingImpact)
            }}
            placeholder="Why does this matter? Quantify the pain if possible (e.g. Teams waste 30% of time…)"
            rows={2}
            disabled={savingImpact}
          />
        </div>
      </div>

      <div className={styles.painPointsCard}>
        <div className={styles.painPointsHeader}>
          <div className={styles.painPointsTitle}>
            <AlertCircle aria-hidden="true" />
            <span>Specific Pain Points</span>
          </div>
          <button
            type="button"
            className={styles.addPointBtn}
            disabled={addingPoint}
            onClick={() => void addPainPoint('New pain point')}
          >
            <Plus aria-hidden="true" /> Add Point
          </button>
        </div>
        <div className={styles.painPointsList}>
          {painPoints.map((entry) => (
            <PainPointRow key={entry.id} entry={entry} onSave={(text) => void updatePainPoint(entry, text)} onRemove={() => void removePainPoint(entry)} />
          ))}
          {painPoints.length === 0 && (
            <p className={styles.painPointsEmpty}>No pain points yet — add the specific ways this problem shows up.</p>
          )}
        </div>
      </div>
    </div>
  )
}

function PainPointRow({ entry, onSave, onRemove }: { entry: KnowledgeEntry; onSave: (text: string) => void; onRemove: () => void }) {
  const [draft, setDraft] = useState<string | null>(null)

  return (
    <div className={styles.painPointRow}>
      <span className={styles.bullet} aria-hidden="true">•</span>
      <input
        className={styles.painPointInput}
        value={draft ?? entry.body}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={(e) => {
          setDraft(null)
          if (e.target.value.trim() !== entry.body) onSave(e.target.value)
        }}
        placeholder="Type a pain point…"
      />
      <button type="button" className={styles.removeBtn} onClick={onRemove} aria-label="Remove pain point" title="Remove">
        <X aria-hidden="true" />
      </button>
    </div>
  )
}
