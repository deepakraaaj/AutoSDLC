import { useEffect, useMemo, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { ApiError, generateProjectChapterWiki, getProjectChapterWiki, getProjectSettings } from '../../api/client'
import type { ProjectDetail, ProjectWikiChapterSet, WikiChapter } from '../../types'
import { useToast } from '../../hooks/useToast'
import { SkeletonList } from '../Skeleton'
import { AnimatedEmptyVisual } from '../AnimatedEmptyVisual'
import styles from './ChapterWikiSection.module.css'

/** Phase 1 of the multi-chapter wiki (app/services/wiki_chapters.py) — a
 * sidebar tree of chapters/sub-chapters, reusing the same section shape
 * (heading/body) the flat wiki already uses. GET /projects/{id}/wiki-chapters
 * returns every chapter flat (parent_id null = top-level); the tree is
 * built client-side here, same normalization spirit as lib/tree.ts's
 * TreeEpic/TreeStory/TreeTask, just simple enough (repo-qualified ids,
 * two levels deep in practice) not to need its own file. */
interface ChapterNode extends WikiChapter {
  children: ChapterNode[]
}

function buildChapterTree(chapters: WikiChapter[]): ChapterNode[] {
  const byId = new Map<number, ChapterNode>()
  for (const chapter of chapters) byId.set(chapter.id, { ...chapter, children: [] })
  const roots: ChapterNode[] = []
  for (const chapter of chapters) {
    const node = byId.get(chapter.id)
    if (!node) continue
    const parent = chapter.parent_id != null ? byId.get(chapter.parent_id) : undefined
    if (parent) parent.children.push(node)
    else roots.push(node)
  }
  const byOrder = (a: ChapterNode, b: ChapterNode) => a.order_index - b.order_index
  const sortRecursive = (nodes: ChapterNode[]) => {
    nodes.sort(byOrder)
    for (const node of nodes) sortRecursive(node.children)
  }
  sortRecursive(roots)
  return roots
}

function ChapterRow({
  node, depth, selectedId, onSelect, expanded, onToggle,
}: {
  node: ChapterNode
  depth: number
  selectedId: number | null
  onSelect: (id: number) => void
  expanded: Set<number>
  onToggle: (id: number) => void
}) {
  const hasChildren = node.children.length > 0
  const isExpanded = expanded.has(node.id)
  return (
    <div>
      <div className={styles.row} style={{ paddingLeft: `${depth * 14}px` }}>
        {hasChildren ? (
          <button
            type="button"
            className={`${styles.toggle} ${isExpanded ? styles.toggleOpen : ''}`}
            onClick={() => onToggle(node.id)}
            aria-label={isExpanded ? `Collapse ${node.title || 'chapter'}` : `Expand ${node.title || 'chapter'}`}
          >
            <ChevronRight aria-hidden="true" />
          </button>
        ) : (
          <span className={styles.togglePlaceholder} aria-hidden="true" />
        )}
        <button
          type="button"
          className={`${styles.navItem} ${selectedId === node.id ? styles.navItemActive : ''}`}
          onClick={() => onSelect(node.id)}
        >
          {node.title || 'Untitled chapter'}
        </button>
      </div>
      {hasChildren && isExpanded && node.children.map((child) => (
        <ChapterRow key={child.id} node={child} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} expanded={expanded} onToggle={onToggle} />
      ))}
    </div>
  )
}

/** Plain-text paragraph/bullet renderer for one chapter section's body —
 * same shape as WikiPageContent.tsx's WikiBody, but simpler: a chapter
 * section's citations live in its own "evidence" field (see WikiPageSection),
 * never embedded in "body" text, so there's no Evidence-sentence-stripping
 * regex to run here. */
function ChapterBody({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/).map((b) => b.trim()).filter(Boolean)
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split('\n').map((l) => l.trim()).filter(Boolean)
        if (lines.length > 0 && lines.every((l) => l.startsWith('- '))) {
          return (
            <ul key={i}>
              {lines.map((l, j) => <li key={j}>{l.slice(2)}</li>)}
            </ul>
          )
        }
        return <p key={i}>{block}</p>
      })}
    </>
  )
}

/** Self-gating on ProjectSettings.chapter_wiki_enabled — renders nothing at
 * all when a project hasn't opted in, so callers (App.tsx) can mount this
 * unconditionally next to WikiSection rather than needing to fetch/thread
 * settings themselves just to decide whether to render it. */
export function ChapterWikiSection({ detail }: { detail: ProjectDetail }) {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  // undefined = still loading; null = loaded, nothing built yet.
  const [chapterSet, setChapterSet] = useState<ProjectWikiChapterSet | null | undefined>(undefined)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [generating, setGenerating] = useState(false)
  const [progressMessage, setProgressMessage] = useState('')
  const { showToast } = useToast()

  function selectFirstTopLevel(set: ProjectWikiChapterSet) {
    const first = set.chapters.find((c) => c.parent_id === null)
    if (first) setSelectedId(first.id)
  }

  async function load() {
    try {
      const settings = await getProjectSettings(detail.id)
      setEnabled(settings.chapter_wiki_enabled)
      if (!settings.chapter_wiki_enabled) return
      const result = await getProjectChapterWiki(detail.id)
      setChapterSet(result)
      if (result) selectFirstTopLevel(result)
    } catch (e) {
      showToast('Failed to load chapter wiki', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id])

  async function handleGenerate() {
    setGenerating(true)
    setProgressMessage('Queued — waiting for a background worker…')
    try {
      const result = await generateProjectChapterWiki(detail.id, setProgressMessage)
      setChapterSet(result)
      selectFirstTopLevel(result)
    } catch (e) {
      showToast('Failed to build chapter wiki', e instanceof ApiError ? e.message : 'Unknown error', 'error')
    } finally {
      setGenerating(false)
      setProgressMessage('')
    }
  }

  function toggle(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const tree = useMemo(() => (chapterSet ? buildChapterTree(chapterSet.chapters) : []), [chapterSet])
  const selected = chapterSet?.chapters.find((c) => c.id === selectedId) ?? null

  if (enabled === false) {
    return null
  }

  if (enabled === null || chapterSet === undefined) {
    return <SkeletonList rows={2} />
  }

  if (chapterSet === null) {
    return (
      <div className={styles.empty}>
        <AnimatedEmptyVisual variant="overview" />
        <p>No chapter wiki has been built yet for {detail.name}.</p>
        <button className="btn btn-primary btn-sm" disabled={generating} onClick={() => void handleGenerate()}>
          {generating && <span className="btn-spinner" />}
          {generating ? 'Building…' : 'Build chapter wiki'}
        </button>
        {generating && <p className="text-muted">{progressMessage}</p>}
      </div>
    )
  }

  return (
    <div className={styles.layout}>
      <nav className={styles.nav} aria-label="Wiki chapters">
        {tree.map((node) => (
          <ChapterRow key={node.id} node={node} depth={0} selectedId={selectedId} onSelect={setSelectedId} expanded={expanded} onToggle={toggle} />
        ))}
      </nav>
      <div className={styles.content}>
        <div className={styles.contentHeader}>
          <button className="btn btn-secondary btn-sm" disabled={generating} onClick={() => void handleGenerate()}>
            {generating && <span className="btn-spinner" />}
            {generating ? 'Rebuilding…' : 'Rebuild chapter wiki'}
          </button>
          {generating && <span className="text-muted">{progressMessage}</span>}
        </div>
        {selected ? (
          <>
            <h2 className={styles.title}>{selected.title || 'Untitled chapter'}</h2>
            {selected.summary && <p className={styles.summary}>{selected.summary}</p>}
            {selected.sections.length === 0 && <p className="text-muted">This chapter hasn't been narrated yet — rebuild the chapter wiki to generate its content.</p>}
            {selected.sections.map((section, i) => (
              <section key={i} className={styles.section}>
                <h3>{section.heading}</h3>
                <ChapterBody text={section.body} />
              </section>
            ))}
          </>
        ) : (
          <p className="text-muted">Select a chapter from the tree.</p>
        )}
      </div>
    </div>
  )
}
