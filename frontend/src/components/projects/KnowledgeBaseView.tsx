import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ClipboardCopy,
  FileUp,
  GitBranch,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  UploadCloud,
} from 'lucide-react'
import {
  ApiError,
  checkKnowledgeQuality,
  createKnowledgeEntry,
  deleteKnowledgeEntry,
  extractKnowledgeFromFile,
  extractKnowledgeFromRepos,
  listKnowledgeEntries,
  updateKnowledgeEntry,
} from '../../api/client'
import { BUSINESS_CONTEXT_KIND_LABELS, BUSINESS_CONTEXT_KINDS, SDLC_AREAS } from '../../types'
import type { BusinessContextKind, KnowledgeCandidate, KnowledgeEntry, KnowledgeEntryType, KnowledgeExtractResult, ProjectDetail } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { APP_ICONS } from '../icons/appIcons'
import { AnimatedEmptyVisual } from '../AnimatedEmptyVisual'
import { copyText, formatRelative } from '../../lib/format'
import { KNOWLEDGE_BASE_EXTRACTION_PROMPT } from '../../lib/knowledgeBasePrompt'
import { AREA_ICONS, areaColorVars } from '../../lib/sdlcAreaStyle'
import { BUSINESS_CONTEXT_KIND_BADGE_CLASS, BUSINESS_CONTEXT_KIND_BODY_PLACEHOLDER, TYPE_BADGE_CLASS, TYPE_LABELS, TYPE_ORDER } from '../../lib/knowledgeEntryStyle'
import styles from './KnowledgeBaseView.module.css'

function isSupportedTemplateFile(file: File | null | undefined): boolean {
  return !!file && /\.(md|docx)$/i.test(file.name || '')
}

const TYPE_FILTERS: { id: 'all' | KnowledgeEntryType; label: string }[] = [
  { id: 'all', label: 'All' },
  ...TYPE_ORDER.map((t) => ({ id: t, label: TYPE_LABELS[t] })),
]

export function AreaIcon({ area }: { area: string }) {
  const Icon = AREA_ICONS[area as keyof typeof AREA_ICONS] || APP_ICONS.knowledgeBase
  return <Icon aria-hidden="true" />
}

function matchesSearch(entry: KnowledgeEntry, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return entry.title.toLowerCase().includes(q) || entry.body.toLowerCase().includes(q)
}

const OTHER_AREA = 'Other'

/** Groups staged candidates by sdlc_area in the canonical 15-area pipeline
 * order (app/services/knowledge_base.py's SDLC_AREAS), with an untagged
 * "Other" bucket last — never alphabetical, so the review screen reads in
 * the order a project actually gets built: discovery, requirements,
 * architecture, ... production. An area with zero candidates is omitted
 * entirely rather than shown empty. Returns [area, indices][] — indices
 * into the flat `candidates` array, since edits/drops mutate that array by
 * index and a grouped copy would need re-syncing on every keystroke. */
function groupCandidatesByArea(candidates: KnowledgeCandidate[]): [string, number[]][] {
  const byArea = new Map<string, number[]>()
  candidates.forEach((c, i) => {
    const area = c.sdlc_area && (SDLC_AREAS as readonly string[]).includes(c.sdlc_area) ? c.sdlc_area : OTHER_AREA
    const bucket = byArea.get(area)
    if (bucket) bucket.push(i)
    else byArea.set(area, [i])
  })
  const ordered: [string, number[]][] = []
  for (const area of [...SDLC_AREAS, OTHER_AREA]) {
    const indices = byArea.get(area)
    if (indices) ordered.push([area, indices])
  }
  return ordered
}

/** Same grouping/ordering as groupCandidatesByArea, for the permanent saved
 * list — the main Knowledge Base view (a project's whole documentation) is
 * where this grouping matters most, not just the one-time review screen. */
function groupEntriesByArea(entries: KnowledgeEntry[]): [string, KnowledgeEntry[]][] {
  const byArea = new Map<string, KnowledgeEntry[]>()
  entries.forEach((e) => {
    const area = e.sdlc_area && (SDLC_AREAS as readonly string[]).includes(e.sdlc_area) ? e.sdlc_area : OTHER_AREA
    const bucket = byArea.get(area)
    if (bucket) bucket.push(e)
    else byArea.set(area, [e])
  })
  const ordered: [string, KnowledgeEntry[]][] = []
  for (const area of [...SDLC_AREAS, OTHER_AREA]) {
    const list = byArea.get(area)
    if (list) ordered.push([area, list])
  }
  return ordered
}

/** Inline add/edit form — shared shape for both "new entry" and "editing an
 * existing card", same as PullRequestsView's card-becomes-a-form pattern in
 * ProjectSettingsModal, just promoted to its own broad page here instead of
 * living only inside Settings. */
const BUSINESS_CONTEXT_AREA = 'Business Context'

export function EntryForm({
  initial,
  initialArea,
  initialBusinessContextKind,
  lockBusinessContextKind,
  submitLabel,
  busy,
  onCancel,
  onSubmit,
}: {
  initial?: KnowledgeEntry
  /** Pre-selects the SDLC area for a brand-new entry (e.g. the dedicated
   * per-area page defaults "Add entry" to the area you're already viewing).
   * Ignored when `initial` is set — an edit always starts from the entry's
   * own saved area. */
  initialArea?: string | null
  /** Pre-selects Business Context's kind for a brand-new entry (the
   * dedicated per-kind page defaults "Add entry" to the kind you're already
   * viewing). Ignored when `initial` is set. */
  initialBusinessContextKind?: BusinessContextKind | null
  /** Locks the kind selector to `initialBusinessContextKind` — the
   * per-kind page's whole point is "everything here is this one kind", so
   * there's no reason to let a new entry silently pick a different one. */
  lockBusinessContextKind?: boolean
  submitLabel: string
  busy: boolean
  onCancel?: () => void
  onSubmit: (fields: { entry_type: KnowledgeEntryType; title: string; sdlc_area: string | null; business_context_kind: BusinessContextKind | null; body: string }) => void
}) {
  const [entryType, setEntryType] = useState<KnowledgeEntryType>(initial?.entry_type || 'glossary')
  const [title, setTitle] = useState(initial?.title || '')
  const [sdlcArea, setSdlcArea] = useState<string | null>(initial ? initial.sdlc_area ?? null : initialArea ?? null)
  const [businessContextKind, setBusinessContextKind] = useState<BusinessContextKind | null>(
    initial ? initial.business_context_kind ?? null : initialBusinessContextKind ?? null,
  )
  const [body, setBody] = useState(initial?.body || '')
  const isBusinessContext = sdlcArea === BUSINESS_CONTEXT_AREA
  // Named individually, not just a flat boolean — so the form can tell the
  // user exactly what's missing instead of leaving "Add entry" disabled
  // with no explanation (a real UX bug: a title/body that only LOOKS filled
  // in because the placeholder text is visible is indistinguishable from an
  // actually-empty field without this).
  const missingTitle = title.trim().length === 0
  const missingBody = body.trim().length === 0
  const missingKind = isBusinessContext && businessContextKind == null
  const valid = !missingTitle && !missingBody && !missingKind

  return (
    <div className={styles.formCard}>
      <div className={styles.formGrid}>
        <div className={styles.formField}>
          <label className={styles.formLabel}>{isBusinessContext ? 'Kind' : 'Type'}</label>
          {/* Business Context replaces the generic glossary/rule/decision/
              constraint selector with its own 7 kinds — see
              BUSINESS_CONTEXT_KINDS' module docstring for why that area
              alone gets this. */}
          {isBusinessContext ? (
            <select
              className={styles.select}
              value={businessContextKind || ''}
              onChange={(e) => setBusinessContextKind((e.target.value || null) as BusinessContextKind | null)}
              disabled={busy || lockBusinessContextKind}
              title={lockBusinessContextKind ? 'This page is scoped to one kind — change it from the all-kinds Business Context view instead' : undefined}
            >
              <option value="" disabled>Choose a kind…</option>
              {BUSINESS_CONTEXT_KINDS.map((k) => (
                <option key={k} value={k}>{BUSINESS_CONTEXT_KIND_LABELS[k]}</option>
              ))}
            </select>
          ) : (
            <select className={styles.select} value={entryType} onChange={(e) => setEntryType(e.target.value as KnowledgeEntryType)} disabled={busy}>
              {TYPE_ORDER.map((t) => (
                <option key={t} value={t}>{TYPE_LABELS[t]}</option>
              ))}
            </select>
          )}
        </div>
        <div className={styles.formField}>
          <label className={styles.formLabel}>SDLC area</label>
          <select
            className={styles.select}
            value={sdlcArea || ''}
            onChange={(e) => {
              const next = e.target.value || null
              setSdlcArea(next)
              if (next !== BUSINESS_CONTEXT_AREA) setBusinessContextKind(null)
            }}
            disabled={busy || lockBusinessContextKind}
            title={lockBusinessContextKind ? 'This page is scoped to Business Context — change it from the all-areas Knowledge Base view instead' : undefined}
          >
            <option value="">No area (Other)</option>
            {SDLC_AREAS.map((area) => (
              <option key={area} value={area}>{area}</option>
            ))}
          </select>
        </div>
      </div>

      <div className={styles.formField}>
        <label className={styles.formLabel}>Title</label>
        <input className="text-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Refund window" disabled={busy} />
      </div>

      {missingKind && (
        <div className={styles.gapNotice}>
          <AlertTriangle aria-hidden="true" />
          <span>Choose a kind above before you can save.</span>
        </div>
      )}

      <div className={styles.formField}>
        <label className={styles.formLabel}>{isBusinessContext && businessContextKind ? BUSINESS_CONTEXT_KIND_LABELS[businessContextKind] : 'The fact'}</label>
        <textarea
          className={styles.textarea}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={
            isBusinessContext
              ? (businessContextKind ? BUSINESS_CONTEXT_KIND_BODY_PLACEHOLDER[businessContextKind] : 'Choose a kind above, then describe the fact here.')
              : 'e.g. Refunds are only valid within 14 days of delivery, not 30.'
          }
          rows={3}
          disabled={busy}
        />
      </div>

      {!valid && !busy && (missingTitle || missingBody) && (
        <p className={styles.formHint}>
          Still need: {[missingTitle && 'a title', missingBody && 'the fact itself'].filter(Boolean).join(' and ')}.
        </p>
      )}
      <div className={styles.formActions}>
        <button
          className="btn btn-primary btn-sm"
          disabled={busy || !valid}
          title={!valid && !busy ? 'Fill in every required field above first' : undefined}
          onClick={() => onSubmit({
            entry_type: entryType, title: title.trim(), sdlc_area: sdlcArea,
            business_context_kind: isBusinessContext ? businessContextKind : null, body: body.trim(),
          })}
        >
          {busy ? 'Saving…' : submitLabel}
        </button>
        {onCancel && (
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}

/** One staged candidate from an uploaded template — editable in place
 * (title/type/body), droppable, with a visible reason when
 * parse_knowledge_markdown flagged it as too thin/placeholder-y to actually
 * ground a claim. Nothing here is saved until the user hits "Save reviewed
 * entries" below — this is the review step, not the write. */
function StagedCandidateCard({
  candidate,
  onChange,
  onDrop,
}: {
  candidate: KnowledgeCandidate
  onChange: (next: KnowledgeCandidate) => void
  onDrop: () => void
}) {
  const isBusinessContext = candidate.sdlc_area === BUSINESS_CONTEXT_AREA
  return (
    <article className={`${styles.card} ${candidate.needs_info ? styles.cardNeedsInfo : ''}`}>
      <div className={styles.formRow}>
        {isBusinessContext ? (
          <select
            className={styles.select}
            value={candidate.business_context_kind || ''}
            onChange={(e) => onChange({ ...candidate, business_context_kind: (e.target.value || null) as BusinessContextKind | null })}
          >
            <option value="" disabled>Choose a kind…</option>
            {BUSINESS_CONTEXT_KINDS.map((k) => (
              <option key={k} value={k}>{BUSINESS_CONTEXT_KIND_LABELS[k]}</option>
            ))}
          </select>
        ) : (
          <select
            className={styles.select}
            value={candidate.entry_type}
            onChange={(e) => onChange({ ...candidate, entry_type: e.target.value as KnowledgeEntryType })}
          >
            {TYPE_ORDER.map((t) => (
              <option key={t} value={t}>{TYPE_LABELS[t]}</option>
            ))}
          </select>
        )}
        <input
          className="text-input"
          value={candidate.title}
          onChange={(e) => onChange({ ...candidate, title: e.target.value })}
          placeholder="Title"
        />
        <button className="btn btn-ghost btn-sm" onClick={onDrop} title="Drop this candidate">
          <Trash2 aria-hidden="true" />
        </button>
      </div>
      <select
        className={styles.areaSelect}
        value={candidate.sdlc_area || ''}
        onChange={(e) => {
          const next = e.target.value || null
          onChange({ ...candidate, sdlc_area: next, business_context_kind: next === BUSINESS_CONTEXT_AREA ? candidate.business_context_kind : null })
        }}
        title="SDLC area — move this candidate to a different group"
      >
        <option value="">No area (Other)</option>
        {SDLC_AREAS.map((area) => (
          <option key={area} value={area}>{area}</option>
        ))}
      </select>
      {isBusinessContext && !candidate.business_context_kind && (
        <div className={styles.gapNotice}>
          <AlertTriangle aria-hidden="true" />
          <span>Choose which Business Context kind this fact is before saving.</span>
        </div>
      )}
      {candidate.needs_info && (
        <div className={styles.gapNotice}>
          <AlertTriangle aria-hidden="true" />
          <span>{candidate.reason || 'Needs more detail before this can ground anything.'}</span>
        </div>
      )}
      <textarea
        className={styles.textarea}
        value={candidate.body}
        onChange={(e) => onChange({ ...candidate, body: e.target.value })}
        placeholder="Add detail so this can actually ground a claim."
        rows={3}
      />
    </article>
  )
}

/** Upload a .md/.docx knowledge-base template, review what got parsed out of
 * it (app/services/knowledge_base.py's parse_knowledge_markdown — heading-
 * split, deterministic, no LLM call so extraction itself can't hallucinate),
 * fix up anything flagged as needing more info, drop what doesn't belong,
 * then save the reviewed set as real entries in one batch. Mirrors
 * UploadTab.tsx's drag-and-drop zone and WikiClarificationForm.tsx's
 * flag-then-fill-in-then-submit shape. */
function TemplateUploadPanel({
  projectId,
  hasRepos,
  autoStartRepoExtraction,
  onSaved,
}: {
  projectId: number
  hasRepos: boolean
  /** Skip the "click Generate from repo" step — used when the empty state's
   * own "Generate from repo" button opened this panel, so that click reads
   * as "start now", not "show me the option to start". */
  autoStartRepoExtraction?: boolean
  onSaved: () => void
}) {
  const [dragOver, setDragOver] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [extractingFromRepo, setExtractingFromRepo] = useState(false)
  const [candidates, setCandidates] = useState<KnowledgeCandidate[] | null>(null)
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const { showToast } = useToast()

  function reportGaps(result: KnowledgeExtractResult) {
    setCandidates(result.candidates)
    if (result.gap_count > 0) {
      showToast(
        `${result.gap_count} candidate${result.gap_count === 1 ? '' : 's'} need${result.gap_count === 1 ? 's' : ''} more info`,
        'Flagged below — fill in the missing detail before saving, or drop them.',
        'warning',
      )
    }
    if (result.repo_errors && result.repo_errors.length > 0) {
      showToast('Some repos could not be read', result.repo_errors.join(' · '), 'warning')
    }
  }

  async function handleFile(file: File | null | undefined) {
    if (!isSupportedTemplateFile(file)) {
      showToast('Unsupported file', 'Use a .md or .docx template.', 'error')
      return
    }
    setExtracting(true)
    try {
      reportGaps(await extractKnowledgeFromFile(projectId, file!))
    } catch (e) {
      showToast('Failed to read file', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setExtracting(false)
    }
  }

  async function handleGenerateFromRepo() {
    setExtractingFromRepo(true)
    try {
      const result = await extractKnowledgeFromRepos(projectId)
      reportGaps(result)
      if (result.candidates.length === 0 && (!result.repo_errors || result.repo_errors.length === 0)) {
        showToast('Nothing extracted', 'The linked repos didn\'t yield any groundable facts.', 'warning')
      }
    } catch (e) {
      showToast('Failed to read repositories', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setExtractingFromRepo(false)
    }
  }

  useEffect(() => {
    if (autoStartRepoExtraction && hasRepos) void handleGenerateFromRepo()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function updateCandidate(index: number, next: KnowledgeCandidate) {
    setCandidates((prev) => (prev ? prev.map((c, i) => (i === index ? next : c)) : prev))
  }

  function dropCandidate(index: number) {
    setCandidates((prev) => (prev ? prev.filter((_, i) => i !== index) : prev))
  }

  async function handleSaveAll() {
    if (!candidates || candidates.length === 0) return
    setSaving(true)
    try {
      for (const c of candidates) {
        await createKnowledgeEntry(projectId, {
          entry_type: c.entry_type, title: c.title.trim() || 'Untitled', sdlc_area: c.sdlc_area,
          business_context_kind: c.business_context_kind, body: c.body.trim(),
        })
      }
      showToast('Saved', `${candidates.length} entr${candidates.length === 1 ? 'y' : 'ies'} added.`, 'info')
      setCandidates(null)
      onSaved()
    } catch (e) {
      showToast('Failed to save some entries', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setSaving(false)
    }
  }

  if (candidates !== null) {
    const gapCount = candidates.filter((c) => c.needs_info).length
    const savable = candidates.every((c) => c.title.trim() && c.body.trim() && (c.sdlc_area !== BUSINESS_CONTEXT_AREA || c.business_context_kind))
    const grouped = groupCandidatesByArea(candidates)
    return (
      <div className={styles.reviewPanel}>
        <div className={styles.reviewHeader}>
          <div>
            <strong>Review {candidates.length} candidate{candidates.length === 1 ? '' : 's'}</strong>
            {grouped.length > 0 && (
              <span className={styles.areaCountBadge}>across {grouped.length} area{grouped.length === 1 ? '' : 's'}</span>
            )}
            {gapCount > 0 && (
              <span className={styles.gapCountBadge}>
                <AlertTriangle aria-hidden="true" /> {gapCount} need{gapCount === 1 ? 's' : ''} more info
              </span>
            )}
          </div>
          <div className={styles.formRow}>
            <button className="btn btn-primary btn-sm" disabled={saving || !savable || candidates.length === 0} onClick={() => void handleSaveAll()}>
              {saving ? 'Saving…' : `Save ${candidates.length} entr${candidates.length === 1 ? 'y' : 'ies'}`}
            </button>
            <button className="btn btn-ghost btn-sm" disabled={saving} onClick={() => setCandidates(null)}>
              Cancel
            </button>
          </div>
        </div>
        {candidates.length === 0 ? (
          <p className="text-muted">All candidates were dropped — upload again or add entries manually below.</p>
        ) : (
          grouped.map(([area, indices]) => {
            const areaGapCount = indices.filter((i) => candidates[i].needs_info).length
            return (
              <div key={area} className={styles.areaGroup}>
                <div className={styles.areaGroupHeader}>
                  <span className={styles.areaGroupIcon} style={areaColorVars(area)}><AreaIcon area={area} /></span>
                  <span className={styles.areaGroupName}>{area}</span>
                  <span className={styles.areaGroupCount}>{indices.length}</span>
                  {areaGapCount > 0 && (
                    <span className={styles.gapCountBadge}>
                      <AlertTriangle aria-hidden="true" /> {areaGapCount}
                    </span>
                  )}
                </div>
                <div className={styles.grid}>
                  {indices.map((i) => (
                    <StagedCandidateCard key={i} candidate={candidates[i]} onChange={(next) => updateCandidate(i, next)} onDrop={() => dropCandidate(i)} />
                  ))}
                </div>
              </div>
            )
          })
        )}
      </div>
    )
  }

  return (
    <div className={styles.uploadPanel}>
      {hasRepos && (
        <div className={styles.repoExtractCard}>
          <GitBranch aria-hidden="true" />
          <div>
            <strong>Generate straight from this project's linked repos</strong>
            <p className="text-muted">
              No document to upload? Mine the actual frontend/backend code for glossary terms, business rules,
              decisions, and constraints — grounded in real code citations, not a guess — so nobody has to go
              ask whoever wrote it.
            </p>
          </div>
          <button className="btn btn-primary btn-sm" disabled={extractingFromRepo} onClick={() => void handleGenerateFromRepo()}>
            {extractingFromRepo ? 'Reading repos…' : 'Generate from repo'}
          </button>
        </div>
      )}

      <div
        className={`${styles.uploadZone} ${dragOver ? styles.uploadZoneDragOver : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          void handleFile(e.dataTransfer.files[0])
        }}
      >
        <UploadCloud aria-hidden="true" />
        <p>
          <strong>{extracting ? 'Reading file…' : 'Or upload a knowledge base template'}</strong>
        </p>
        <p className="text-muted">
          .md or .docx — split into candidate entries by heading. Thin or placeholder sections (TODO/TBD) get
          flagged so you can fill them in before saving.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".md,.docx"
          className={styles.hiddenInput}
          disabled={extracting}
          onChange={(e) => void handleFile(e.target.files?.[0])}
        />
      </div>
      <p className={styles.uploadHint}>
        Don't have a template yet? For an enterprise-scale project, hand-typing entries one at a time isn't
        realistic — copy this prompt into any AI tool along with your existing docs (Confluence, PRDs, ADRs,
        onboarding notes) and it returns a ready-to-upload file.
      </p>
      <CopyPromptButton />
    </div>
  )
}

function CopyPromptButton() {
  const [copied, setCopied] = useState(false)
  const { showToast } = useToast()

  async function handleCopy() {
    try {
      await copyText(KNOWLEDGE_BASE_EXTRACTION_PROMPT)
      setCopied(true)
      showToast('Prompt copied', 'Paste it into any AI tool along with your source docs.', 'info')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      showToast('Copy failed', 'Your browser blocked clipboard access.', 'error')
    }
  }

  return (
    <button className="btn btn-secondary btn-sm" onClick={() => void handleCopy()}>
      <ClipboardCopy aria-hidden="true" /> {copied ? 'Copied!' : 'Copy extraction prompt'}
    </button>
  )
}

export function EntryCard({ entry, flagReason, onChanged }: { entry: KnowledgeEntry; flagReason: string | null; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [pendingDelete, setPendingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const { showToast } = useToast()

  async function handleSaveEdit(fields: { entry_type: KnowledgeEntryType; title: string; sdlc_area: string | null; business_context_kind: BusinessContextKind | null; body: string }) {
    setSaving(true)
    try {
      await updateKnowledgeEntry(entry.project_id, entry.id, fields)
      setEditing(false)
      onChanged()
    } catch (e) {
      showToast('Failed to update entry', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!pendingDelete) {
      setPendingDelete(true)
      return
    }
    setDeleting(true)
    try {
      await deleteKnowledgeEntry(entry.project_id, entry.id)
      onChanged()
    } catch (e) {
      showToast('Failed to remove entry', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setDeleting(false)
      setPendingDelete(false)
    }
  }

  if (editing) {
    return (
      <EntryForm
        initial={entry}
        submitLabel="Save"
        busy={saving}
        onCancel={() => setEditing(false)}
        onSubmit={(fields) => void handleSaveEdit(fields)}
      />
    )
  }

  return (
    <article className={`${styles.card} ${flagReason ? styles.cardNeedsInfo : ''}`}>
      <div className={styles.cardTop}>
        {entry.business_context_kind ? (
          <span className={BUSINESS_CONTEXT_KIND_BADGE_CLASS[entry.business_context_kind]}>{BUSINESS_CONTEXT_KIND_LABELS[entry.business_context_kind]}</span>
        ) : (
          <span className={TYPE_BADGE_CLASS[entry.entry_type]}>{TYPE_LABELS[entry.entry_type]}</span>
        )}
        <span className={styles.cardTitle}>{entry.title}</span>
        <span className={styles.citationTag} title="Cited by this handle in wiki evidence">[KB-{entry.id}]</span>
      </div>
      {flagReason && (
        <div className={styles.gapNotice}>
          <AlertTriangle aria-hidden="true" />
          <span>{flagReason}</span>
        </div>
      )}
      <p className={styles.cardBody}>{entry.body}</p>
      <div className={styles.cardMeta}>
        <span>Updated {formatRelative(entry.updated_at) || new Date(entry.updated_at).toLocaleDateString()}</span>
        <div className={styles.cardActions}>
          <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)} title="Edit">
            <Pencil aria-hidden="true" />
          </button>
          <button
            className={`btn btn-sm ${pendingDelete ? 'btn-danger' : 'btn-ghost'}`}
            disabled={deleting}
            onClick={() => void handleDelete()}
            onBlur={() => {
              if (!deleting) setPendingDelete(false)
            }}
            title={pendingDelete ? 'Confirm remove?' : 'Remove'}
          >
            <Trash2 aria-hidden="true" />
          </button>
        </div>
      </div>
    </article>
  )
}

/** Broad, browsable view of a project's whole knowledge base — same
 * dashboard-tab shape as PullRequestsView/SecurityView: a type filter, a
 * search box, and a card grid, reachable from the sidebar's project areas
 * (Overview / Planning / Backlog / Pull Requests / Security / Knowledge Base)
 * instead of only being editable buried inside Project Settings. Settings
 * still has its own compact Knowledge Base section for quick edits mid-setup;
 * this is the first-class destination for actually using it day to day. */
export function KnowledgeBaseView({ project }: { project: ProjectDetail }) {
  const [entries, setEntries] = useState<KnowledgeEntry[] | null>(null)
  const [typeFilter, setTypeFilter] = useState<'all' | KnowledgeEntryType>('all')
  const [query, setQuery] = useState('')
  const [adding, setAdding] = useState(false)
  const [showAddForm, setShowAddForm] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [autoStartRepo, setAutoStartRepo] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [flaggedEntries, setFlaggedEntries] = useState<Map<number, string>>(new Map())
  const { showToast } = useToast()

  // Quality-checks automatically, every load — see KnowledgeAreaView.tsx's
  // load() for why this isn't a separate manual button: check_body_quality
  // is cheap (no LLM call), and an entry saved before the check existed or
  // was tightened must never sit here silently unreadable, unflagged, until
  // someone happens to click a button that finds it.
  async function load() {
    setRefreshing(true)
    try {
      const [all, quality] = await Promise.all([listKnowledgeEntries(project.id), checkKnowledgeQuality(project.id)])
      setEntries(all)
      setFlaggedEntries(new Map(quality.flagged.map((f) => [f.id, f.reason])))
    } catch (e) {
      showToast('Failed to load knowledge base', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  async function handleAdd(fields: { entry_type: KnowledgeEntryType; title: string; sdlc_area: string | null; business_context_kind: BusinessContextKind | null; body: string }) {
    setAdding(true)
    try {
      await createKnowledgeEntry(project.id, fields)
      setShowAddForm(false)
      await load()
    } catch (e) {
      showToast('Failed to add entry', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setAdding(false)
    }
  }

  if (entries === null) {
    return (
      <section className={styles.page} aria-busy="true">
        <header className={styles.header}>
          <div>
            <h2>Knowledge base</h2>
            <p>{project.name}'s single source of truth — every business rule, decision, and constraint the AI must never guess at.</p>
          </div>
        </header>
        <SkeletonList rows={3} />
      </section>
    )
  }

  const totalAll = entries.length
  const visible = entries
    .filter((e) => typeFilter === 'all' || e.entry_type === typeFilter)
    .filter((e) => matchesSearch(e, query))

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <div>
          <h2>
            Knowledge base
            {flaggedEntries.size > 0 && (
              <span className={styles.headerFlagBadge} title={`${flaggedEntries.size} entr${flaggedEntries.size === 1 ? 'y needs' : 'ies need'} a rewrite`}>
                <AlertTriangle aria-hidden="true" /> {flaggedEntries.size}
              </span>
            )}
          </h2>
          <p className={styles.headerLede}>
            This is the project's documentation — not a side note. Everything here comes from your real BRDs,
            SOPs, ADRs, security/compliance docs, runbooks, and decision logs, and it's what stands between the
            AI and a guess: every backlog item and wiki page is grounded in it, and a wiki claim can cite an
            entry here as its source exactly the way it cites a line of code.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
          <button className="btn btn-secondary btn-sm" disabled={refreshing} onClick={() => void load()}>
            <RefreshCw aria-hidden="true" /> {refreshing ? 'Checking…' : 'Refresh'}
          </button>
          <button
            className={`btn btn-sm ${showUpload ? 'btn-secondary' : 'btn-ghost'}`}
            onClick={() => {
              setShowUpload((v) => !v)
              setShowAddForm(false)
              setAutoStartRepo(false)
            }}
          >
            <FileUp aria-hidden="true" /> Upload template
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => {
              setShowAddForm((v) => !v)
              setShowUpload(false)
            }}
          >
            <Plus aria-hidden="true" /> Add entry
          </button>
        </div>
      </header>

      {showUpload && (
        <TemplateUploadPanel
          projectId={project.id}
          hasRepos={project.repos.length > 0}
          autoStartRepoExtraction={autoStartRepo}
          onSaved={() => { setShowUpload(false); void load() }}
        />
      )}

      {showAddForm && (
        <EntryForm submitLabel="Add entry" busy={adding} onCancel={() => setShowAddForm(false)} onSubmit={(fields) => void handleAdd(fields)} />
      )}

      {totalAll > 0 && (
        <div className={styles.toolbar}>
          <div className={styles.typeTabs} role="tablist" aria-label="Filter by entry type">
            {TYPE_FILTERS.map((f) => (
              <button
                key={f.id}
                role="tab"
                aria-selected={typeFilter === f.id}
                className={typeFilter === f.id ? styles.typeTabActive : ''}
                onClick={() => setTypeFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <label className={styles.searchBox}>
            <Search aria-hidden="true" />
            <input
              type="search"
              placeholder="Search title or body…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search knowledge base"
            />
          </label>
        </div>
      )}

      {totalAll === 0 && !showUpload && (
        <div className={`card ${styles.emptyState}`}>
          <AnimatedEmptyVisual variant="connections" />
          <APP_ICONS.knowledgeBase aria-hidden="true" />
          <p>This project has no documented knowledge yet</p>
          <p className="text-muted">
            BRDs, SOPs, ADRs, security/compliance docs, runbooks, decision logs — anything that answers "what's
            the actual business rule here" belongs in this project's knowledge base.
            {project.repos.length > 0
              ? ' This project has linked repos — generate straight from the real code instead of hand-typing.'
              : ' For a real enterprise project, hand-typing that isn\'t realistic: upload what you already have, or copy the extraction prompt and point an AI tool at it.'}
          </p>
          <div className={styles.emptyStateActions}>
            {project.repos.length > 0 && (
              <button
                className="btn btn-primary btn-sm"
                onClick={() => {
                  setAutoStartRepo(true)
                  setShowUpload(true)
                }}
              >
                <GitBranch aria-hidden="true" /> Generate from repo
              </button>
            )}
            <button
              className={`btn btn-sm ${project.repos.length > 0 ? 'btn-secondary' : 'btn-primary'}`}
              onClick={() => {
                setAutoStartRepo(false)
                setShowUpload(true)
              }}
            >
              <FileUp aria-hidden="true" /> Upload a template
            </button>
          </div>
        </div>
      )}

      {totalAll > 0 && visible.length === 0 && (
        <div className={`card ${styles.emptyState}`}>
          <p>{query.trim() ? 'No entries match your search' : `No ${TYPE_FILTERS.find((f) => f.id === typeFilter)?.label.toLowerCase()} entries`}</p>
          <p className="text-muted">{query.trim() ? 'Try a different search term.' : 'Try a different filter above.'}</p>
        </div>
      )}

      {visible.length > 0 && groupEntriesByArea(visible).map(([area, areaEntries]) => (
        <div key={area} className={styles.areaGroup}>
          <div className={styles.areaGroupHeader}>
            <span className={styles.areaGroupIcon} style={areaColorVars(area)}><AreaIcon area={area} /></span>
            <span className={styles.areaGroupName}>{area}</span>
            <span className={styles.areaGroupCount}>{areaEntries.length}</span>
          </div>
          <div className={styles.grid}>
            {areaEntries.map((entry) => (
              <EntryCard
                key={entry.id}
                entry={entry}
                flagReason={flaggedEntries.get(entry.id) || null}
                onChanged={() => void load()}
              />
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}
