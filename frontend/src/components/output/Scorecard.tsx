import { useState } from 'react'
import type { OverallMetrics } from '../../types'
import type { WeakItem, WeakDimension, ImproveQualityResult, ImproveQualityItem, ImproveQualityProgress } from '../../api/client'
import { scoreTone, formatDuration } from '../../lib/format'
import styles from './Scorecard.module.css'

const FILL_CLASS: Record<ReturnType<typeof scoreTone>, string> = {
  success: styles.fillSuccess,
  warning: styles.fillWarning,
  danger: styles.fillDanger,
}

// Mirrors app.services.metrics.QUALITY_PASS_THRESHOLD — only used here to decide
// whether a bar's own "Fix" link is worth showing at all (a passing bar has nothing
// to target). The backend is still the source of truth for what actually counts as
// weak; this just avoids offering a link that would come back empty.
const QUALITY_PASS_THRESHOLD = 80

/** `dimension` is the backend's find_weak_items dimension name for this bar (e.g.
 * "definition_of_done") — when given and the score is below the pass bar, the bar
 * gets its own "Fix" link that jumps straight to just the items dragging *this* score
 * down, via `onImprove`. Bars with no backend dimension (dependencies — handled by
 * the separate repair action; test-case metrics — not covered by find_weak_items yet)
 * render as plain, non-interactive rows. */
function Bar({
  label,
  score,
  dimension,
  onImprove,
}: {
  label: string
  score: number
  dimension?: string
  onImprove?: (dimension: string) => void
}) {
  const tone = scoreTone(score)
  const fixable = dimension && onImprove && score < QUALITY_PASS_THRESHOLD
  return (
    <div className={styles.row}>
      <span className={styles.label}>{label}</span>
      <div className={styles.barTrack}>
        <div className={`${styles.barFill} ${FILL_CLASS[tone]}`} style={{ width: `${score}%` }} />
      </div>
      <span className={`${styles.val} ${styles[tone]}`}>{score}</span>
      {fixable && (
        <button type="button" className={styles.barFix} onClick={() => onImprove(dimension)}>
          Fix
        </button>
      )}
    </div>
  )
}

/** "definition_of_done" -> "Definition of done" */
function formatDimensionName(name: string): string {
  const words = name.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function formatValue(value: unknown): string {
  const text = Array.isArray(value) ? value.join('; ') : String(value ?? '')
  return text.length > 90 ? `${text.slice(0, 90)}…` : text
}

function WeakDimensionRow({ dim }: { dim: WeakDimension }) {
  return (
    <li className={styles.weakDim}>
      <span className={styles.dimBadge}>{dim.score}</span>
      <span className={styles.dimText}>
        <strong>{formatDimensionName(dim.name)}:</strong> {dim.reason}
      </span>
    </li>
  )
}

function itemKey(item: { kind: string; id: string }): string {
  return `${item.kind}:${item.id}`
}

/** Collapsed by default — with 30+ items in a group, one expanded reason paragraph
 * and diff per row was a wall of text. Collapsed, a row is one line: checkbox, title,
 * a pill per weak dimension (the "why", at a glance — refreshed post-fix so a
 * partially-fixed item shows what's *still* wrong, not the stale original list), a
 * status badge, and a chevron. Click the row to expand the full reason text and
 * before/after diff. */
function WeakItemRow({
  item,
  fix,
  checked,
  onToggle,
}: {
  item: WeakItem
  fix?: ImproveQualityItem
  checked: boolean
  onToggle: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  // "updated" (a rewrite was written) and "resolved" (that rewrite actually cleared
  // the bar) are different — only a resolved item is really done and lockable.
  const resolved = fix?.updated && fix.resolved
  const stillWeak = fix?.updated && !fix.resolved
  const currentDims = fix ? fix.weak_dimensions : item.weak_dimensions
  // The pass bar only decides when we stop touching an item — the model isn't told to
  // aim for exactly that number, so show what it actually landed on (could be well
  // above the bar) instead of a bare "Fixed" that reads like the score got clamped.
  const worstScore = fix?.current_scores ? Math.min(...Object.values(fix.current_scores)) : null
  const worstBefore = fix?.before_scores ? Math.min(...Object.values(fix.before_scores)) : null
  // Whether the number the user cares about actually moved. "updated" only means a
  // rewrite was written — it can lift a strong dimension while the weak one that
  // caused the flag sits exactly where it was, which is why a bare "Improved to 50%"
  // was so misleading: 50% was both the before and the after.
  const moved = worstBefore != null && worstScore != null && worstScore > worstBefore
  // An item that improved without clearing the bar gets retried automatically against
  // its own current weak dimensions (see main.py's MAX_FIX_ATTEMPTS) — worth showing
  // when it took more than one try, since "still below bar" after several attempts
  // reads differently than after just one.
  const attemptsNote = fix?.attempts && fix.attempts > 1 ? ` (${fix.attempts} attempts)` : ''
  // A deliberate "we left it alone" is not a failure and must not be dressed as one —
  // red "Failed" on an untouched backlog reads like something broke.
  const blocked = fix?.error_kind === 'blocked'
  return (
    <li className={styles.weakItem}>
      <div className={styles.weakItemHead}>
        <input
          type="checkbox"
          className={styles.weakItemCheck}
          checked={checked}
          onChange={onToggle}
          disabled={resolved}
          aria-label={`Include ${item.title} in the fix`}
        />
        <button type="button" className={styles.weakItemToggle} onClick={() => setExpanded((v) => !v)}>
          <span className={styles.weakItemTitle}>{item.title}</span>
          <span className={styles.dimPills}>
            {currentDims.map((dim) => (
              <span key={dim.name} className={styles.dimPill}>{formatDimensionName(dim.name)}</span>
            ))}
          </span>
          {resolved && <span className={styles.fixedBadge}>Fixed{worstScore != null ? ` · ${worstScore}%` : ''}{attemptsNote}</span>}
          {stillWeak && moved && (
            <span className={styles.partialBadge}>
              Improved {worstBefore}% → {worstScore}% — still below bar{attemptsNote}
            </span>
          )}
          {stillWeak && !moved && (
            <span className={styles.blockedBadge}>
              Rewritten, but still {worstScore}%{attemptsNote}
            </span>
          )}
          {fix?.error && blocked && (
            <span className={styles.blockedBadge}>
              Left as-is{worstScore != null ? ` · ${worstScore}%` : ''}
            </span>
          )}
          {fix?.error && !blocked && <span className={styles.errorBadge}>Failed</span>}
          <span className={styles.chevron}>{expanded ? '▾' : '▸'}</span>
        </button>
      </div>
      {expanded && (
        <>
          <ul className={styles.weakDims}>
            {currentDims.map((dim) => (
              <WeakDimensionRow key={dim.name} dim={dim} />
            ))}
          </ul>
          {fix?.error && (
            <p className={blocked ? styles.itemBlocked : styles.itemError}>
              {blocked ? 'Left unchanged: ' : "Couldn't fix automatically: "}{fix.error}
              {blocked && fix.stalled && ' Another click will do the same thing — this one needs a manual edit.'}
            </p>
          )}
          {fix?.changes && fix.changes.length > 0 && (
            <ul className={styles.changeList}>
              {fix.changes.map((change) => (
                <li key={change.field} className={styles.changeRow}>
                  <span className={styles.changeField}>{formatDimensionName(change.field)}</span>
                  <span className={styles.changeBefore}>{formatValue(change.before)}</span>
                  {' → '}
                  <span className={styles.changeAfter}>{formatValue(change.after)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </li>
  )
}

/** The group itself folds too, same as each row inside it — a "Stories (7)" or
 * "Tasks (33)" section shouldn't have to render every row just to show its count. */
function WeakGroup({
  title,
  items,
  selected,
  onToggle,
  onSelectAll,
  onSelectNone,
  fixByItem,
}: {
  title: string
  items: WeakItem[]
  selected: Set<string>
  onToggle: (key: string) => void
  onSelectAll: () => void
  onSelectNone: () => void
  fixByItem: Map<string, ImproveQualityItem>
}) {
  const [expanded, setExpanded] = useState(true)
  // A finished item is done — it doesn't need reading again. After a big fix run most
  // of this list is "Fixed · 90%" rows, and leaving them in means scrolling a wall of
  // green to find the handful that still need attention. They stay one click away.
  const [showFixed, setShowFixed] = useState(false)
  if (items.length === 0) return null
  const resolvedItems = items.filter((item) => fixByItem.get(itemKey(item))?.resolved)
  const fixedCount = resolvedItems.length
  const stillWeakCount = items.filter((item) => {
    const fix = fixByItem.get(itemKey(item))
    return fix?.updated && !fix.resolved
  }).length
  // Counted separately so the header's numbers account for themselves. These were
  // attempted and deliberately not written; folding them into "still need another
  // pass" implied another click would help, which for a stalled item it won't.
  const leftAsIsCount = items.filter((item) => {
    const fix = fixByItem.get(itemKey(item))
    return fix && !fix.updated && fix.error_kind === 'blocked'
  }).length
  // Real failures were missing from the header entirely, so "40, 29 fixed, 10 still
  // need another pass" silently lost one item and the numbers didn't add up.
  const failedCount = items.filter((item) => {
    const fix = fixByItem.get(itemKey(item))
    return fix && !fix.updated && fix.error_kind === 'failed'
  }).length
  const visibleItems = showFixed ? items : items.filter((item) => !fixByItem.get(itemKey(item))?.resolved)
  return (
    <div className={styles.weakGroup}>
      <div className={styles.weakGroupHead}>
        <button type="button" className={styles.weakGroupToggle} onClick={() => setExpanded((v) => !v)}>
          <span className={styles.groupChevron}>{expanded ? '▾' : '▸'}</span>
          <h4>
            {title} ({items.length}
            {fixedCount > 0 ? `, ${fixedCount} fixed` : ''}
            {stillWeakCount > 0 ? `, ${stillWeakCount} still need another pass` : ''}
            {leftAsIsCount > 0 ? `, ${leftAsIsCount} left as-is` : ''}
            {failedCount > 0 ? `, ${failedCount} failed` : ''})
          </h4>
        </button>
        <div className={styles.weakGroupActions}>
          {fixedCount > 0 && (
            <button type="button" className={styles.linkBtn} onClick={() => setShowFixed((v) => !v)}>
              {showFixed ? `Hide ${fixedCount} fixed` : `Show ${fixedCount} fixed`}
            </button>
          )}
          <button type="button" className={styles.linkBtn} onClick={onSelectAll}>Select all</button>
          <button type="button" className={styles.linkBtn} onClick={onSelectNone}>Clear</button>
        </div>
      </div>
      {expanded && visibleItems.length === 0 && (
        <p className={styles.groupAllClear}>All {fixedCount} cleared the bar.</p>
      )}
      {expanded && visibleItems.length > 0 && (
        <ul className={styles.weakList}>
          {visibleItems.map((item) => (
            <WeakItemRow
              key={itemKey(item)}
              item={item}
              fix={fixByItem.get(itemKey(item))}
              checked={selected.has(itemKey(item))}
              onToggle={() => onToggle(itemKey(item))}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

export function Scorecard({
  metrics,
  onCopy,
  onAnalyzeWeakItems,
  onFixWeakItems,
  boostingQuality = false,
  fixProgress = null,
}: {
  metrics: OverallMetrics
  onCopy: () => void
  onAnalyzeWeakItems: (dimension?: string) => Promise<WeakItem[] | null>
  onFixWeakItems: (items: { kind: 'story' | 'task'; id: string }[]) => Promise<ImproveQualityResult | null>
  boostingQuality?: boolean
  /** Live progress while a fix runs. Without it the button just spins for what can be
   * minutes across several retry rounds and a rate-limit wait — indistinguishable from
   * a hang. */
  fixProgress?: ImproveQualityProgress | null
}) {
  const gapTone = metrics.gap_count === 0 ? 'success' : metrics.gap_count <= 3 ? 'warning' : 'danger'
  const [boostOpen, setBoostOpen] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [weakItems, setWeakItems] = useState<WeakItem[] | null>(null)
  // Distinct from weakItems === null ("haven't checked yet") — a failed request must
  // never render the same as "checked, found nothing." That was the actual bug: a
  // 500 from the backend still resolved to an empty list here, so the panel showed
  // "Nothing fell below the quality bar" — a false all-clear for a check that never
  // actually ran.
  const [analysisFailed, setAnalysisFailed] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [fixResult, setFixResult] = useState<ImproveQualityResult | null>(null)
  // Which bar's "Fix" link (if any) drove the current weakItems list — kept so
  // "Re-check backlog" re-applies the same filter instead of suddenly showing
  // everything, and so the panel can say what it's currently scoped to.
  const [activeDimension, setActiveDimension] = useState<string | null>(null)

  async function handleAnalyze(dimension: string | null = activeDimension) {
    setAnalyzing(true)
    setFixResult(null)
    setActiveDimension(dimension)
    try {
      const items = await onAnalyzeWeakItems(dimension ?? undefined)
      if (items === null) {
        setAnalysisFailed(true)
        return
      }
      setAnalysisFailed(false)
      setWeakItems(items)
      setSelected(new Set(items.map(itemKey))) // all ticked by default — click to exclude
    } finally {
      setAnalyzing(false)
    }
  }

  /** A bar's own "Fix" link: open the panel and jump straight to a diagnosis scoped
   * to just that one dimension, instead of the whole mixed list. */
  function handleImproveDimension(dimension: string) {
    setBoostOpen(true)
    void handleAnalyze(dimension)
  }

  async function handleFix() {
    if (!weakItems) return
    const items = weakItems.filter((item) => selected.has(itemKey(item))).map((item) => ({ kind: item.kind, id: item.id }))
    const result = await onFixWeakItems(items)
    if (!result) return
    setFixResult(result)
    // Untick what there's no point re-sending: anything resolved, plus anything the
    // backend deliberately left alone after its score stopped moving. An item that
    // genuinely improved but is still below the bar stays ticked — that one has a
    // real chance next click. Leaving the stalled ones ticked is what turned a second
    // "Fix" click into a round of AI calls that could only report the same thing again.
    setSelected((prev) => {
      const next = new Set(prev)
      for (const item of result.items) {
        if (item.resolved || (item.stalled && !item.updated)) next.delete(itemKey(item))
      }
      return next
    })
  }

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const stories = weakItems?.filter((item) => item.kind === 'story') ?? []
  const tasks = weakItems?.filter((item) => item.kind === 'task') ?? []
  const fixByItem = new Map((fixResult?.items ?? []).map((item) => [itemKey(item), item]))
  const groupSelectAll = (items: WeakItem[]) => () => setSelected((prev) => new Set([...prev, ...items.map(itemKey)]))
  const groupSelectNone = (items: WeakItem[]) => () => {
    const keys = new Set(items.map(itemKey))
    setSelected((prev) => new Set([...prev].filter((k) => !keys.has(k))))
  }

  return (
    <div className={`card ${styles.card}`}>
      <div className={styles.header}>
        <h2>Quality</h2>
        <div className={styles.actions}>
          <button className="btn btn-ghost btn-sm" onClick={onCopy}>Copy</button>
          <button className="btn btn-primary btn-sm" onClick={() => setBoostOpen((open) => !open)} disabled={boostingQuality}>
            {boostingQuality ? 'Fixing…' : 'Improve quality'}
          </button>
        </div>
      </div>
      <div className={styles.grid}>
        <div>
          <h3 className={styles.groupTitle}>Stories</h3>
          <Bar label="Specificity" score={metrics.story_metrics.specificity_score} dimension="specificity" onImprove={handleImproveDimension} />
          <Bar label="Testability" score={metrics.story_metrics.testability_score} dimension="testability" onImprove={handleImproveDimension} />
          <Bar label="Sizing" score={metrics.story_metrics.sizing_score} dimension="sizing" onImprove={handleImproveDimension} />
          <Bar label="Edge cases" score={metrics.story_metrics.edge_case_score} dimension="edge_case" onImprove={handleImproveDimension} />
        </div>
        <div>
          <h3 className={styles.groupTitle}>Tasks</h3>
          <Bar label="Clarity" score={metrics.task_metrics.clarity_score} dimension="clarity" onImprove={handleImproveDimension} />
          <Bar label="Definition of done" score={metrics.task_metrics.definition_of_done_score} dimension="definition_of_done" onImprove={handleImproveDimension} />
          <Bar label="Estimates" score={metrics.task_metrics.estimate_score} dimension="estimate" onImprove={handleImproveDimension} />
          {/* No dimension: dependency scoring is fixed deterministically by the
              separate "repair dependencies" action, not by find_weak_items/AI. */}
          <Bar label="Dependencies" score={metrics.task_metrics.dependency_score} />
        </div>
        {metrics.test_metrics && (
          <div>
            <h3 className={styles.groupTitle}>Test cases</h3>
            <Bar label="Coverage" score={metrics.test_metrics.coverage_score} />
            <Bar label="Expected result quality" score={metrics.test_metrics.expected_result_quality_score} />
            <Bar label="Edge case mix" score={metrics.test_metrics.edge_case_coverage_score} />
          </div>
        )}
      </div>
      <div className={styles.overallRow}>
        <div className={styles.overallChip}>
          <div className={`${styles.overallVal} ${styles[scoreTone(metrics.story_metrics.overall)]}`}>
            {metrics.story_metrics.overall}%
          </div>
          <div className={styles.overallLabel}>Story quality</div>
        </div>
        <div className={styles.overallChip}>
          <div className={`${styles.overallVal} ${styles[scoreTone(metrics.task_metrics.overall)]}`}>
            {metrics.task_metrics.overall}%
          </div>
          <div className={styles.overallLabel}>Task quality</div>
        </div>
        <div className={styles.overallChip}>
          <div className={`${styles.overallVal} ${styles[scoreTone(metrics.coverage_score)]}`}>
            {metrics.coverage_score}%
          </div>
          <div className={styles.overallLabel}>Coverage</div>
        </div>
        {metrics.test_metrics && (
          <div className={styles.overallChip}>
            <div className={`${styles.overallVal} ${styles[scoreTone(metrics.test_metrics.overall)]}`}>
              {metrics.test_metrics.overall}%
            </div>
            <div className={styles.overallLabel}>Test quality</div>
          </div>
        )}
        <div className={styles.overallChip}>
          <div className={`${styles.overallVal} ${styles[gapTone]}`}>{metrics.gap_count}</div>
          <div className={styles.overallLabel}>Gaps found</div>
        </div>
      </div>
      {metrics.confidence_summary && <div className={styles.confidenceNote}>{metrics.confidence_summary}</div>}
      {boostOpen && (
        <section className={styles.boostPanel} aria-label="Quality improvement">
          <div>
            <h3>Fix the weakest items — not a full regeneration</h3>
            <p>
              Finds the specific stories/tasks dragging the scores above down and why. Tick the ones to fix (all
              ticked by default) — the model rewrites just those weaknesses and retries automatically if a fix
              doesn't clear the {QUALITY_PASS_THRESHOLD}% bar on the first try.
            </p>
          </div>

          {!weakItems && !analysisFailed && (
            <button className="btn btn-primary" onClick={() => void handleAnalyze(null)} disabled={analyzing}>
              {analyzing ? 'Checking…' : 'Check backlog for weak items'}
            </button>
          )}

          {analysisFailed && (
            <p className={styles.itemError}>
              Couldn't check the backlog — the analysis failed on the server.{' '}
              <button type="button" className={styles.linkBtn} onClick={() => void handleAnalyze(activeDimension)} disabled={analyzing}>
                {analyzing ? 'Retrying…' : 'Try again'}
              </button>
            </p>
          )}

          {weakItems && activeDimension && (
            <p className={styles.filterNote}>
              Showing only items dragging down <strong>{formatDimensionName(activeDimension)}</strong>.{' '}
              <button type="button" className={styles.linkBtn} onClick={() => void handleAnalyze(null)}>Show all weak items instead</button>
            </p>
          )}

          {weakItems && weakItems.length === 0 && (
            <p className={styles.emptyWeak}>
              {activeDimension
                ? `Nothing is dragging down ${formatDimensionName(activeDimension)} — nothing to fix here.`
                : 'Nothing fell below the quality bar — nothing to fix here.'}
            </p>
          )}

          {weakItems && weakItems.length > 0 && (
            <>
              <WeakGroup
                title="Stories"
                items={stories}
                selected={selected}
                onToggle={toggle}
                onSelectAll={groupSelectAll(stories)}
                onSelectNone={groupSelectNone(stories)}
                fixByItem={fixByItem}
              />
              <WeakGroup
                title="Tasks"
                items={tasks}
                selected={selected}
                onToggle={toggle}
                onSelectAll={groupSelectAll(tasks)}
                onSelectNone={groupSelectNone(tasks)}
                fixByItem={fixByItem}
              />
              {boostingQuality && fixProgress && (
                <div className={styles.fixProgress}>
                  <div className={styles.fixProgressTrack}>
                    <div
                      className={styles.fixProgressFill}
                      style={{ width: `${fixProgress.total > 0 ? Math.round((fixProgress.completed / fixProgress.total) * 100) : 0}%` }}
                    />
                  </div>
                  <p className={styles.fixProgressText}>
                    <strong>{fixProgress.completed} of {fixProgress.total}</strong>
                    {' · '}{fixProgress.message}
                  </p>
                </div>
              )}
              <div className={styles.boostControls}>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => void handleAnalyze()} disabled={analyzing || boostingQuality}>
                  {analyzing ? 'Re-checking…' : 'Re-check backlog'}
                </button>
                <button className="btn btn-primary" onClick={() => void handleFix()} disabled={boostingQuality || selected.size === 0}>
                  {boostingQuality
                    ? fixProgress
                      ? `Fixing ${fixProgress.completed}/${fixProgress.total}…`
                      : 'Fixing…'
                    : selected.size > 0
                      ? `Fix ${selected.size} selected item${selected.size > 1 ? 's' : ''}`
                      : 'Fix selected items'}
                </button>
              </div>
            </>
          )}
        </section>
      )}
      {(metrics.generation_seconds != null || metrics.token_usage) && (
        <div className={styles.usageBlock}>
          <div className={styles.usageHeader}>Generation cost</div>
          <div className={styles.usageChips}>
            {metrics.generation_seconds != null && (
              <div className={styles.usageChip}>
                <div className={styles.usageVal}>{formatDuration(metrics.generation_seconds)}</div>
                <div className={styles.usageLabel}>Time</div>
              </div>
            )}
            {metrics.token_usage && (
              <>
                <div className={styles.usageChip}>
                  <div className={styles.usageVal}>{metrics.token_usage.total_tokens.toLocaleString()}</div>
                  <div className={styles.usageLabel}>Total tokens</div>
                </div>
                <div className={styles.usageChip}>
                  <div className={styles.usageVal}>${metrics.token_usage.cost_usd.toFixed(4)}</div>
                  <div className={styles.usageLabel}>Est. cost</div>
                </div>
              </>
            )}
          </div>
          {metrics.token_usage && (
            <div className={styles.usageDetail}>
              {metrics.token_usage.ai_calls} AI call{metrics.token_usage.ai_calls === 1 ? '' : 's'} ·{' '}
              {metrics.token_usage.prompt_tokens.toLocaleString()} prompt tokens ·{' '}
              {metrics.token_usage.completion_tokens.toLocaleString()} completion tokens
            </div>
          )}
        </div>
      )}
    </div>
  )
}
