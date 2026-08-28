import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowLeft, Plus, RefreshCw, Search } from 'lucide-react'
import { ApiError, checkKnowledgeQuality, createKnowledgeEntry, listKnowledgeEntries } from '../../api/client'
import { BUSINESS_CONTEXT_KIND_LABELS, BUSINESS_CONTEXT_KIND_PURPOSE } from '../../types'
import type { BusinessContextKind, KnowledgeEntry, KnowledgeEntryType, ProjectDetail } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { AnimatedEmptyVisual } from '../AnimatedEmptyVisual'
import { areaColorVars } from '../../lib/sdlcAreaStyle'
import { AreaIcon, EntryCard, EntryForm } from './KnowledgeBaseView'
import { ProblemStatementEditor } from './ProblemStatementEditor'
import styles from './KnowledgeAreaView.module.css'

const BUSINESS_CONTEXT_AREA = 'Business Context'

/** One Business Context kind's own dedicated page — one level deeper than
 * KnowledgeAreaView's per-SDLC-area pages, reached from the sidebar's
 * Business Context sub-tree. Same card/form building blocks (imported from
 * KnowledgeBaseView, not duplicated), same page shell (KnowledgeAreaView's
 * CSS module, reused as-is — identical layout, just filtered one field
 * deeper): header names the kind and its purpose, "Add entry" pre-fills and
 * locks the kind selector to this one (the whole point of the page is
 * "everything here is this one kind"), only entries of this kind ever show. */
export function BusinessContextKindView({ project, kind, onBack }: { project: ProjectDetail; kind: BusinessContextKind; onBack: () => void }) {
  const [entries, setEntries] = useState<KnowledgeEntry[] | null>(null)
  const [query, setQuery] = useState('')
  const [showAddForm, setShowAddForm] = useState(false)
  const [adding, setAdding] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [flaggedEntries, setFlaggedEntries] = useState<Map<number, string>>(new Map())
  const { showToast } = useToast()
  const label = BUSINESS_CONTEXT_KIND_LABELS[kind]

  // Same auto-flag-on-load contract as KnowledgeAreaView.tsx's load() — see
  // that file's comment for why this isn't a manual "check quality" button.
  async function load() {
    setRefreshing(true)
    try {
      const [all, quality] = await Promise.all([listKnowledgeEntries(project.id), checkKnowledgeQuality(project.id)])
      setEntries(all.filter((e) => e.sdlc_area === BUSINESS_CONTEXT_AREA && e.business_context_kind === kind))
      setFlaggedEntries(new Map(quality.flagged.map((f) => [f.id, f.reason])))
    } catch (e) {
      showToast('Failed to load knowledge base', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    setEntries(null)
    setFlaggedEntries(new Map())
    setShowAddForm(false)
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, kind])

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

  const flaggedCount = (entries || []).filter((e) => flaggedEntries.has(e.id)).length

  const visible = (entries || []).filter((e) => {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return e.title.toLowerCase().includes(q) || e.body.toLowerCase().includes(q)
  })

  return (
    <section className={styles.page}>
      <button type="button" className={styles.backLink} onClick={onBack}>
        <ArrowLeft aria-hidden="true" /> All Business Context entries
      </button>
      <header className={styles.header} style={areaColorVars(BUSINESS_CONTEXT_AREA)}>
        <div className={styles.headerIcon}><AreaIcon area={BUSINESS_CONTEXT_AREA} /></div>
        <div className={styles.headerText}>
          <h2>
            {label}
            {flaggedCount > 0 && (
              <span className={styles.headerFlagBadge} title={`${flaggedCount} entr${flaggedCount === 1 ? 'y needs' : 'ies need'} a rewrite`}>
                <AlertTriangle aria-hidden="true" /> {flaggedCount}
              </span>
            )}
          </h2>
          <p>{BUSINESS_CONTEXT_KIND_PURPOSE[kind]}</p>
        </div>
        <div className={styles.headerActions}>
          <button className="btn btn-secondary btn-sm" disabled={refreshing} onClick={() => void load()}>
            <RefreshCw aria-hidden="true" /> {refreshing ? 'Checking…' : 'Refresh'}
          </button>
          {/* Problem Statement has no generic add form — its fields (Overview/
              Impact/Pain Points) save inline as you type, via ProblemStatementEditor. */}
          {kind !== 'problem_statement' && (
            <button className="btn btn-primary btn-sm" onClick={() => setShowAddForm((v) => !v)}>
              <Plus aria-hidden="true" /> Add entry
            </button>
          )}
        </div>
      </header>

      {entries === null && (
        <div aria-busy="true"><SkeletonList rows={3} /></div>
      )}

      {/* Problem Statement gets its own concrete Overview/Impact/Pain-Points
          fields (see ProblemStatementEditor's docstring) instead of the
          generic freeform title+body list every other kind uses — a
          problem statement isn't a bag of small unrelated facts, it's these
          three specific things every BRD opens with. */}
      {entries !== null && kind === 'problem_statement' && (
        <ProblemStatementEditor projectId={project.id} entries={entries} onChanged={() => void load()} />
      )}

      {entries !== null && kind !== 'problem_statement' && (
        <>
          {showAddForm && (
            <EntryForm
              submitLabel="Add entry"
              busy={adding}
              initialArea={BUSINESS_CONTEXT_AREA}
              initialBusinessContextKind={kind}
              lockBusinessContextKind
              onCancel={() => setShowAddForm(false)}
              onSubmit={(fields) => void handleAdd(fields)}
            />
          )}

          {entries.length > 0 && (
            <label className={styles.searchBox}>
              <Search aria-hidden="true" />
              <input
                type="search"
                placeholder={`Search ${label.toLowerCase()} entries…`}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label={`Search ${label}`}
              />
            </label>
          )}

          {entries.length === 0 && (
            <div className={`card ${styles.emptyState}`}>
              <AnimatedEmptyVisual variant="connections" />
              <div className={styles.emptyStateIcon} style={areaColorVars(BUSINESS_CONTEXT_AREA)}><AreaIcon area={BUSINESS_CONTEXT_AREA} /></div>
              <p>No {label.toLowerCase()} entries yet</p>
              <p className="text-muted">
                Add one directly, or run "Generate from repo" / upload a template from the Knowledge Base
                overview — anything tagged {`"${label}"`} under Business Context lands here automatically.
              </p>
            </div>
          )}

          {entries.length > 0 && visible.length === 0 && (
            <div className={`card ${styles.emptyState}`}>
              <p>No entries match your search</p>
              <p className="text-muted">Try a different search term.</p>
            </div>
          )}

          {visible.length > 0 && (
            <div className={styles.grid}>
              {visible.map((entry) => (
                <EntryCard key={entry.id} entry={entry} flagReason={flaggedEntries.get(entry.id) || null} onChanged={() => void load()} />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
