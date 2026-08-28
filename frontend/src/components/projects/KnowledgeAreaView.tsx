import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowLeft, Plus, RefreshCw, Search } from 'lucide-react'
import { ApiError, checkKnowledgeQuality, createKnowledgeEntry, listKnowledgeEntries } from '../../api/client'
import { SDLC_AREA_PURPOSE } from '../../types'
import type { BusinessContextKind, KnowledgeEntry, KnowledgeEntryType, ProjectDetail, SdlcArea } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { AnimatedEmptyVisual } from '../AnimatedEmptyVisual'
import { areaColorVars } from '../../lib/sdlcAreaStyle'
import { AreaIcon, EntryCard, EntryForm } from './KnowledgeBaseView'
import styles from './KnowledgeAreaView.module.css'

/** One SDLC area's own dedicated page — reached from the sidebar's Knowledge
 * Base sub-tree (one sub-item per app/services/knowledge_base.py's 15
 * SDLC_AREAS). Same card/form building blocks as the all-areas
 * KnowledgeBaseView (imported from there, not duplicated) but scoped:
 * header names the area and its purpose (the reference extraction table's
 * "Purpose in SDLC" column), search/filter/add all default to this area, and
 * only this area's entries ever show — a focused page per area rather than
 * one long page a reader has to scroll and hunt through. */
export function KnowledgeAreaView({ project, area, onBack }: { project: ProjectDetail; area: SdlcArea; onBack: () => void }) {
  const [entries, setEntries] = useState<KnowledgeEntry[] | null>(null)
  const [query, setQuery] = useState('')
  const [showAddForm, setShowAddForm] = useState(false)
  const [adding, setAdding] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [flaggedEntries, setFlaggedEntries] = useState<Map<number, string>>(new Map())
  const { showToast } = useToast()

  // Quality-checks automatically, every load — a reader landing on this page
  // must never see an unreadable entry (backticks, enum dumps, a raw code
  // citation in the sentence) without it already being flagged; a manual
  // "click to find out" button was the wrong default given check_body_quality
  // is cheap (no LLM call) and entries saved before the check existed or was
  // tightened otherwise sit here silently unreadable forever.
  async function load() {
    setRefreshing(true)
    try {
      const [all, quality] = await Promise.all([listKnowledgeEntries(project.id), checkKnowledgeQuality(project.id)])
      setEntries(all.filter((e) => e.sdlc_area === area))
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
  }, [project.id, area])

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

  const areaFlaggedCount = (entries || []).filter((e) => flaggedEntries.has(e.id)).length

  const visible = (entries || []).filter((e) => {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return e.title.toLowerCase().includes(q) || e.body.toLowerCase().includes(q)
  })

  return (
    <section className={styles.page}>
      <button type="button" className={styles.backLink} onClick={onBack}>
        <ArrowLeft aria-hidden="true" /> All Knowledge Base areas
      </button>
      <header className={styles.header} style={areaColorVars(area)}>
        <div className={styles.headerIcon}><AreaIcon area={area} /></div>
        <div className={styles.headerText}>
          <h2>
            {area}
            {areaFlaggedCount > 0 && (
              <span className={styles.headerFlagBadge} title={`${areaFlaggedCount} entr${areaFlaggedCount === 1 ? 'y needs' : 'ies need'} a rewrite`}>
                <AlertTriangle aria-hidden="true" /> {areaFlaggedCount}
              </span>
            )}
          </h2>
          <p>{SDLC_AREA_PURPOSE[area]}</p>
        </div>
        <div className={styles.headerActions}>
          <button className="btn btn-secondary btn-sm" disabled={refreshing} onClick={() => void load()}>
            <RefreshCw aria-hidden="true" /> {refreshing ? 'Checking…' : 'Refresh'}
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => setShowAddForm((v) => !v)}>
            <Plus aria-hidden="true" /> Add entry
          </button>
        </div>
      </header>

      {showAddForm && (
        <EntryForm
          submitLabel="Add entry"
          busy={adding}
          initialArea={area}
          onCancel={() => setShowAddForm(false)}
          onSubmit={(fields) => void handleAdd(fields)}
        />
      )}

      {entries === null && (
        <div aria-busy="true"><SkeletonList rows={3} /></div>
      )}

      {entries !== null && entries.length > 0 && (
        <label className={styles.searchBox}>
          <Search aria-hidden="true" />
          <input
            type="search"
            placeholder={`Search ${area.toLowerCase()}…`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label={`Search ${area}`}
          />
        </label>
      )}

      {entries !== null && entries.length === 0 && (
        <div className={`card ${styles.emptyState}`}>
          <AnimatedEmptyVisual variant="connections" />
          <div className={styles.emptyStateIcon} style={areaColorVars(area)}><AreaIcon area={area} /></div>
          <p>No {area.toLowerCase()} entries yet</p>
          <p className="text-muted">
            Add one directly, or run "Generate from repo" / upload a template from the Knowledge Base
            overview — anything tagged {`"${area}"`} lands here automatically.
          </p>
        </div>
      )}

      {entries !== null && entries.length > 0 && visible.length === 0 && (
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
    </section>
  )
}
