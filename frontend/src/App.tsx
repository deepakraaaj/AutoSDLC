import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, FolderKanban, GitBranch, Layers3, Settings } from 'lucide-react'
import { Sidebar, type ProjectArea, type TabId } from './components/Sidebar'
import { PageHeader } from './components/PageHeader'
import { ProgressPanel } from './components/ProgressPanel'
import { ErrorBanner } from './components/ErrorBanner'
import { SkeletonList } from './components/Skeleton'
import { CreateTab } from './components/tabs/CreateTab'
import { AssistantTab } from './components/tabs/AssistantTab'
import { ProjectsTab } from './components/tabs/ProjectsTab'
import { BacklogsTab } from './components/tabs/BacklogsTab'
import { OutputView } from './components/output/OutputView'
import { BacklogHeader } from './components/output/BacklogHeader'
import { QualityRail } from './components/output/QualityRail'
import { EpicProgressMap } from './components/output/EpicProgressMap'
import { WorkflowVisualizer } from './components/output/WorkflowVisualizer'
import { PhaseTabs } from './components/output/PhaseTabs'
import { PhaseList, type PhaseListHandlers } from './components/output/PhaseList'
import { phaseContent, phaseCount } from './lib/phases'
import { BacklogTabs } from './components/output/BacklogTabs'
import { DetailModal, type DetailTarget } from './components/output/DetailModal'
import { CreateItemModal, type CreateTarget } from './components/output/CreateItemModal'
import { RedmineModal, type RedmineScope } from './components/redmine/RedmineModal'
import { BitbucketModal, type BitbucketScope } from './components/bitbucket/BitbucketModal'
import { ProjectSettingsModal } from './components/projects/ProjectSettingsModal'
import { ProjectPlanningView } from './components/projects/ProjectPlanningView'
import { PullRequestsView } from './components/projects/PullRequestsView'
import { useGeneration, type Phase } from './hooks/useGeneration'
import { useToast } from './hooks/useToast'
import { useRole } from './hooks/useRole'
import { backlogToPlainText, copyText } from './lib/format'
import {
  ApiError,
  exportExcelUrl,
  getProject,
  updateEpicStatus,
  updateStoryStatus,
  updateTaskStatus,
  updateTaskAssignee,
  updateEpicPriority,
  updateStoryPriority,
  updateTaskPriority,
  repairTaskDependencies,
  getWeakItems,
  streamImproveGenerationQuality,
  type ImproveQualityProgress,
  type WeakItem,
  type ImproveQualityResult,
  type QualityItemSelection,
} from './api/client'
import type { EpicStatus, StoryStatus, TaskStatus, GenerationOutput, Hierarchy, ProjectDetail } from './types'
import {
  parseRoute,
  tabPath,
  backlogPath,
  createPath,
  projectPath,
  routePath,
  type AppRoute,
  type BacklogView,
  type CreateMode,
} from './lib/route'
import styles from './App.module.css'
import { DEFAULT_QUALITY_INSTRUCTIONS, GenerationSettings, type QualitySettings } from './components/GenerationSettings'
import { extractBrief } from './api/client'
import { useGenerationPolicy } from './hooks/useGenerationPolicy'

/** The phase views render a flat PhaseList; overview and hierarchy render OutputView
 * sections. Phase ids deliberately match useGeneration's Phase so one URL segment
 * addresses both the generation step and the page showing it. */
function isPhaseView(view: BacklogView): view is Phase {
  return view === 'epics' || view === 'stories' || view === 'tasks' || view === 'tests'
}

function backlogCounts(output: GenerationOutput, hierarchy: Hierarchy | null): Partial<Record<BacklogView, number>> {
  const content = phaseContent(output, hierarchy)
  return {
    epics: phaseCount(content, 'epics'),
    stories: phaseCount(content, 'stories'),
    tasks: phaseCount(content, 'tasks'),
    tests: phaseCount(content, 'tests'),
  }
}

/** One line per screen, not a paragraph. These sat above the fold on every page and
 * were read exactly once. */
const PAGE_COPY: Record<TabId, { title: string; description: string }> = {
  projects: { title: 'Overview', description: 'Monitor your products, backlogs, and connected repositories.' },
  create: { title: 'Create a backlog', description: 'Turn a brief, conversation, or document into an implementation-ready backlog.' },
  backlogs: { title: 'Backlog', description: 'Review every generated plan in this workspace, newest first.' },
  assistant: { title: 'Assistant', description: 'Ask about your product, delivery work, and connected tools.' },
}

export default function App() {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.pathname))
  const tab = route.tab
  const [chatResetKey, setChatResetKey] = useState(0)
  const [redmineOpen, setRedmineOpen] = useState(false)
  const [redmineScope, setRedmineScope] = useState<RedmineScope | null>(null)
  const [bitbucketOpen, setBitbucketOpen] = useState(false)
  const [bitbucketScope, setBitbucketScope] = useState<BitbucketScope | null>(null)
  const [detailTarget, setDetailTarget] = useState<DetailTarget | null>(null)
  const [createTarget, setCreateTarget] = useState<CreateTarget | null>(null)
  const [repairingDependencies, setRepairingDependencies] = useState(false)
  const [boostingQuality, setBoostingQuality] = useState(false)
  // Only meaningful below 1180px, where the Quality rail leaves the layout and comes
  // back as a sheet driven from the header's Quality button.
  const [qualitySheetOpen, setQualitySheetOpen] = useState(false)
  // Only meaningful at/above 1180px, where the rail persists in the layout — the
  // Overview meta bar's panel-toggle icon collapses it to reclaim the width.
  const [qualityRailOpen, setQualityRailOpen] = useState(true)
  const [hierarchyFocusStoryId, setHierarchyFocusStoryId] = useState<string | null>(null)
  // Live progress from the fix run — a few dozen items take several rounds of AI calls
  // and can pause on a provider rate limit, so the panel reports what it's doing.
  const [fixProgress, setFixProgress] = useState<ImproveQualityProgress | null>(null)
  const [chatSeed, setChatSeed] = useState('')
  // Set by ProjectsTab's "Generate backlog for this project" action — the
  // next generation (any tab) attaches to this project. Cleared on New Run,
  // same lifecycle as the rest of one generation's transient state.
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null)
  const [projectSettingsOpen, setProjectSettingsOpen] = useState(false)
  const [projectSettingsId, setProjectSettingsId] = useState<number | null>(null)
  const [qualitySettings, setQualitySettingsState] = useState<QualitySettings>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem('quality-settings') || '')
      return { generationMode: 'auto', ...parsed }
    } catch {
      return { clarifyFirst: true, instructions: DEFAULT_QUALITY_INSTRUCTIONS, generationMode: 'auto' }
    }
  })
  const gen = useGeneration()
  const { showToast } = useToast()
  const { canAccessWorkflowVisualizer } = useRole()
  const { generate: generateForBacklog } = useGenerationPolicy(gen, qualitySettings)

  function go(path: string) {
    if (window.location.pathname !== path) window.history.pushState({}, '', path)
    setRoute(parseRoute(path))
  }

  /** Sidebar navigation. "Backlogs" always means the list — /app/backlogs with no id.
   * Pointing it at the session's last generation instead would make the list
   * unreachable the moment one backlog had been opened. */
  function navigateTo(nextTab: TabId) {
    go(tabPath(nextTab))
  }

  /** Open a specific generation (and optionally one of its pages). The id lives in the
   * URL, so this address survives a reload, a share, and — the actual point — being
   * opened in a separate browser tab. */
  function navigateToBacklog(targetGenId: number | null, view: BacklogView = 'overview') {
    go(backlogPath(targetGenId, view))
  }

  // The address bar is normalised on first load so a legacy path (/app/brief,
  // /app/history, /app/backlog/12/stories) doesn't stay in the URL after being
  // redirected. replaceState, not push: there is nothing to go "back" to.
  useEffect(() => {
    const canonical = routePath(parseRoute(window.location.pathname))
    if (canonical !== window.location.pathname) window.history.replaceState({}, '', canonical)
  }, [])

  useEffect(() => {
    const syncRoute = () => setRoute(parseRoute(window.location.pathname))
    window.addEventListener('popstate', syncRoute)
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])

  // When opening a project, load its project details and latest backlog if available
  useEffect(() => {
    if (route.tab !== 'projects' || route.projectId == null) {
      setProjectDetail(null)
      return
    }
    let cancelled = false
    void getProject(route.projectId)
      .then((detail) => {
        if (cancelled) return
        setProjectDetail(detail)
        if (route.projectSection !== 'settings' && detail.generations.length > 0) {
          const targetGenId = route.genId ?? detail.generations[0].id
          if (loadedGenIdRef.current !== targetGenId) {
            loadedGenIdRef.current = targetGenId
            void gen.loadFromHistory(targetGenId)
          }
        }
      })
      .catch((e) => {
        if (cancelled) return
        showToast('Error', e instanceof ApiError ? e.message : 'Could not load project', 'error')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.tab, route.projectId, route.projectSection, route.genId])

  function setQualitySettings(value: QualitySettings) {
    setQualitySettingsState(value)
    localStorage.setItem('quality-settings', JSON.stringify(value))
  }

  async function generateWithQuality(text: string, openBacklog = false) {
    if (openBacklog) navigateTo('backlogs')
    await generateForBacklog(text, selectedProjectId)
  }

  /** Diagnosis step: every specific story/task dragging the score down, and *why*
   * (find_weak_items, same rubric the Scorecard shows) — no AI call, no write.
   * Scorecard groups these and lets the user tick which ones to actually fix, rather
   * than the app silently picking "the worst N" for them. An optional `dimension`
   * narrows this to items weak on just that one Scorecard bar — what a bar's own
   * "Fix" link uses so clicking, say, Definition of done goes straight to the items
   * dragging that score down instead of the whole mixed list. */
  async function handleAnalyzeWeakItems(dimension?: string): Promise<WeakItem[] | null> {
    if (!genId) return null
    try {
      const { items } = await getWeakItems(genId, dimension)
      return items
    } catch (e) {
      // null, not [] — an empty array here used to be indistinguishable from "checked
      // and genuinely nothing is weak," so a failed request rendered as a cheerful
      // "Nothing fell below the quality bar" instead of the error it actually was.
      showToast('Analysis failed', e instanceof ApiError || e instanceof Error ? e.message : 'Could not analyze backlog quality', 'error')
      return null
    }
  }

  /** Fix step: only the items the user ticked on the diagnosis above, in place — not
   * a full regeneration. Reloads the current generation afterward so the refreshed
   * scores and content show up, same as onRepairDependencies below. */
  async function handleFixWeakItems(items: QualityItemSelection[]): Promise<ImproveQualityResult | null> {
    if (!genId || items.length === 0) return null
    setBoostingQuality(true)
    try {
      const result = await streamImproveGenerationQuality(genId, items, setFixProgress)
      if (result.targeted > 0) await gen.loadFromHistory(genId)
      const failedToWrite = result.targeted - result.updated
      // "updated" (wrote a rewrite) and "resolved" (that rewrite actually cleared the
      // bar) are different things — an item can improve without fully resolving. The
      // backend already retries each item automatically within this one call (see
      // main.py's MAX_FIX_ATTEMPTS), so "still weak" here means it didn't clear the
      // bar even after those attempts, not that nothing was tried — say so, since a
      // flat "Fixed N" implies nothing's left and a plain "needs another pass" reads
      // like this click didn't already try.
      const stillWeak = result.updated - result.resolved
      showToast(
        result.targeted === 0 ? 'Already strong' : 'Quality improved',
        result.targeted === 0
          ? result.message ?? 'Nothing scored low enough to target.'
          : `Resolved ${result.resolved} of ${result.targeted} selected item(s).` +
            (stillWeak ? ` ${stillWeak} improved but stayed short of the bar after retrying — see attempts below.` : '') +
            (failedToWrite ? ` ${failedToWrite} couldn't be fixed automatically.` : ''),
        'info',
      )
      return result
    } catch (e) {
      showToast('Quality improvement failed', e instanceof ApiError || e instanceof Error ? e.message : 'Could not improve quality', 'error')
      return null
    } finally {
      setBoostingQuality(false)
      setFixProgress(null)
    }
  }

  function handleTextSubmit(text: string) {
    if (!qualitySettings.clarifyFirst) return void generateWithQuality(text)
    setChatSeed(text)
    setChatResetKey((key) => key + 1)
    go(createPath('chat'))
  }

  async function handleFileSubmit(file: File) {
    try {
      const { text } = await extractBrief(file)
      if (qualitySettings.clarifyFirst) handleTextSubmit(text)
      else await generateWithQuality(text)
    } catch (e) {
      showToast('Upload failed', e instanceof ApiError ? e.message : 'Could not read the uploaded brief', 'error')
    }
  }

  function handleNewRun() {
    gen.reset()
    setChatSeed('')
    setChatResetKey((k) => k + 1)
    setSelectedProjectId(null)
    // Drop the generation id too: leaving it in the URL would have the route effect
    // reload the run that was just cleared.
    loadedGenIdRef.current = null
    go(createPath('chat'))
  }

  async function withStatusUpdate(action: () => Promise<unknown>, genId: number | null) {
    try {
      await action()
      if (genId) await gen.refreshHierarchy(genId)
    } catch (e) {
      showToast('Error', e instanceof ApiError ? e.message : 'Failed to update', 'error')
    }
  }

  const { state } = gen
  const showProgress = state.isGenerating && state.step
  const genId = state.lastGenId

  /** The status/priority/detail wiring every backlog surface needs — the checkpoint
   * PhaseTabs, the routed per-phase PhaseList pages, and the Hierarchy tree all take
   * the same bundle rather than each restating twelve near-identical props. */
  const rowHandlers: PhaseListHandlers = {
    onEpicStatusChange: (dbId, status) =>
      void withStatusUpdate(() => updateEpicStatus(dbId, status as EpicStatus), genId),
    onStoryStatusChange: (dbId, status) =>
      void withStatusUpdate(() => updateStoryStatus(dbId, status as StoryStatus), genId),
    onTaskStatusChange: (dbId, status) =>
      void withStatusUpdate(() => updateTaskStatus(dbId, status as TaskStatus), genId),
    onEpicPriorityChange: (dbId, priority) =>
      void withStatusUpdate(() => updateEpicPriority(dbId, priority), genId),
    onStoryPriorityChange: (dbId, priority) =>
      void withStatusUpdate(() => updateStoryPriority(dbId, priority), genId),
    onTaskPriorityChange: (dbId, priority) =>
      void withStatusUpdate(() => updateTaskPriority(dbId, priority), genId),
    onOpenDetail: setDetailTarget,
  }
  // Which generation is on screen follows the URL, not the other way round. The ref
  // starts at the id the page was opened with so this doesn't re-fetch what
  // useGeneration's own restore already loaded on mount.
  const loadedGenIdRef = useRef<number | null>(parseRoute(window.location.pathname).genId)
  useEffect(() => {
    if (route.tab !== 'backlogs' || route.genId == null) return
    if (loadedGenIdRef.current === route.genId) return
    loadedGenIdRef.current = route.genId
    void gen.loadFromHistory(route.genId)
    // gen.loadFromHistory is stable (useCallback); depending on `gen` would refire this
    // on every generation state change and refetch the backlog mid-edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.tab, route.genId])

  // A run started from Create lands on /app/backlogs with no id. Once it has one, put
  // it in the address bar so the page can be reloaded, shared or opened in a second
  // tab. replaceState, not push: this isn't a navigation the back button should have
  // to step through. Only fills a *missing* id, so it never fights the effect above.
  useEffect(() => {
    if (route.tab !== 'backlogs' || route.genId != null || state.lastGenId == null) return
    const path = backlogPath(state.lastGenId, route.view)
    window.history.replaceState({}, '', path)
    loadedGenIdRef.current = state.lastGenId
    setRoute(parseRoute(path))
  }, [route.tab, route.genId, route.view, state.lastGenId])

  const page = PAGE_COPY[tab]
  const output = state.lastOutput
  const quality = output?.metrics?.story_metrics?.overall ?? null
  const backlogIsEmpty = !state.isGenerating && !output && !state.error
  const backlogReady = Boolean(output) && !state.isGenerating && !state.awaitingPhase
  // The URL decides, not the session: /app/backlogs is the list, /app/backlogs/:id is
  // one backlog. A run that has not been assigned an id yet is the third case — it has
  // no address to be at, so an in-flight generation shows here too until the effect
  // below stamps its id into the URL.
  const runInFlight = state.isGenerating || Boolean(state.awaitingPhase) || Boolean(state.error)
  const isProjectBacklog = tab === 'projects' && route.projectId != null
  const isProjectPlanning = isProjectBacklog && route.projectSection === 'planning'
  const isProjectPullRequests = isProjectBacklog && route.projectSection === 'pull-requests'
  const showBacklogDetail =
    (tab === 'backlogs' && (route.genId != null || runInFlight)) ||
    (isProjectBacklog && !isProjectPlanning && !isProjectPullRequests && Boolean((projectDetail && projectDetail.generations.length > 0) || runInFlight))
  // Where the detail view is showing, BacklogHeader carries the title — a PageHeader
  // above it would be a second heading saying the same thing.
  const showPageHeader = !(showBacklogDetail && backlogReady) && !isProjectBacklog

  function copyBacklog() {
    if (!output) return
    void copyText(backlogToPlainText(output)).then(() =>
      showToast('Copied', 'Backlog copied to clipboard.', 'info'),
    )
  }

  return (
    <div className={styles.shell}>
      <Sidebar
        active={tab}
        activeProjectId={route.projectId}
        onChange={navigateTo}
        onOpenProject={(projectId) => go(projectPath(projectId))}
        onOpenProjectArea={(projectId: number, area: ProjectArea) => {
          if (area === 'planning' || area === 'pull-requests') {
            go(projectPath(projectId, area))
            return
          }
          go(projectPath(projectId, null, area === 'backlog' ? 'hierarchy' : 'overview'))
        }}
      />
      <main className={styles.content}>
        <div className={`${styles.inner} ${tab === 'backlogs' || isProjectBacklog ? styles.backlogCanvas : ''}`}>
          {showPageHeader && <PageHeader title={page.title} description={page.description} />}
          {tab === 'create' && <GenerationSettings value={qualitySettings} onChange={setQualitySettings} />}

          {tab === 'create' && (
            <CreateTab
              mode={route.createMode}
              onModeChange={(mode: CreateMode) => go(createPath(mode))}
              isGenerating={state.isGenerating}
              chatResetKey={chatResetKey}
              chatSeed={chatSeed}
              onTextSubmit={handleTextSubmit}
              onChatSubmit={generateWithQuality}
              onFileSubmit={handleFileSubmit}
              onViewBacklog={() => navigateTo('backlogs')}
            />
          )}

          {tab === 'assistant' && (
            <AssistantTab
              lastOutput={output}
              genId={genId}
              onGenerate={(text) => generateWithQuality(text, true)}
              onPushed={() => {
                if (genId) void gen.refreshHierarchy(genId)
              }}
              onOpenRedmineModal={() => {
                setRedmineScope(null)
                setRedmineOpen(true)
              }}
            />
          )}

          {tab === 'projects' && route.projectId == null && (
            <ProjectsTab
              onOpenProject={(projectId) => go(projectPath(projectId))}
              onOpenSettings={(projectId) => {
                setProjectSettingsId(projectId)
                setProjectSettingsOpen(true)
              }}
            />
          )}

          {tab === 'projects' && route.projectId != null && (
            <div className={styles.projectHeader}>
              <div className={styles.projectHeaderLeft}>
                <button className={styles.backBtn} onClick={() => go(projectPath(null))}>
                  <ArrowLeft aria-hidden="true" />
                  All projects
                </button>
                <div className={styles.projectIdentity}>
                  <span className={styles.projectMark} aria-hidden="true"><FolderKanban /></span>
                  <div className={styles.projectIdentityCopy}>
                    <span className={styles.projectEyebrow}>Product workspace</span>
                    <div className={styles.projectTitleRow}>
                      <span className={styles.projectNameTitle}>{projectDetail?.name || 'Project'}</span>
                      {projectDetail?.ticket_prefix && (
                        <span className={styles.ticketPrefix}>{projectDetail.ticket_prefix}</span>
                      )}
                    </div>
                    {projectDetail?.description && <p>{projectDetail.description}</p>}
                    {projectDetail && (
                      <div className={styles.projectMeta}>
                        <span><Layers3 aria-hidden="true" />{projectDetail.generations.length} backlog{projectDetail.generations.length === 1 ? '' : 's'}</span>
                        <span><GitBranch aria-hidden="true" />{projectDetail.repos.length} linked repo{projectDetail.repos.length === 1 ? '' : 's'}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              <div className={styles.projectHeaderRight}>
                {isProjectBacklog && !isProjectPullRequests && projectDetail && projectDetail.generations.length > 1 && (
                  <select
                    className={`select ${styles.genSelect}`}
                    value={genId || ''}
                    onChange={(e) => {
                      const newGenId = Number(e.target.value)
                      loadedGenIdRef.current = newGenId
                      void gen.loadFromHistory(newGenId)
                    }}
                    aria-label="Select backlog generation"
                  >
                    {projectDetail.generations.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.project_name || `Backlog #${g.id}`}
                      </option>
                    ))}
                  </select>
                )}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setProjectSettingsId(route.projectId)
                    setProjectSettingsOpen(true)
                  }}
                  title="Project settings"
                >
                  <Settings aria-hidden="true" />
                  Settings
                </button>
              </div>
            </div>
          )}

          {isProjectBacklog && !isProjectPullRequests && projectDetail && projectDetail.generations.length === 0 && !runInFlight && (
            <div className={`card ${styles.emptyState}`}>
              <p>No backlog generated for {projectDetail.name} yet</p>
              <p className="text-muted">Start a brief to generate epics, stories, and tasks attached to this project.</p>
              <div className={styles.emptyActions}>
                <button
                  className="btn btn-primary"
                  onClick={() => {
                    setSelectedProjectId(projectDetail.id)
                    go(createPath('write'))
                  }}
                >
                  Generate backlog
                </button>
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    setProjectSettingsId(projectDetail.id)
                    setProjectSettingsOpen(true)
                  }}
                >
                  Project settings
                </button>
              </div>
            </div>
          )}

          {isProjectPlanning && projectDetail && output && !state.isGenerating && (
            <ProjectPlanningView
              project={projectDetail}
              output={output}
              hierarchy={state.hierarchy}
              onOpenStoryHierarchy={(storyId) => {
                setHierarchyFocusStoryId(storyId)
                go(projectPath(projectDetail.id, 'backlog', 'hierarchy'))
              }}
            />
          )}

          {isProjectPullRequests && projectDetail && (
            <PullRequestsView project={projectDetail} />
          )}

          {tab === 'backlogs' && !showBacklogDetail && <BacklogsTab onOpen={(id) => navigateToBacklog(id)} />}

          {showBacklogDetail && (
            <>
              {/* Header and the view tab bar are pinned together as one unit (see
                  .backlogTopBar) — they only ever render at the same time as each
                  other (both gated on backlogReady), never alongside PhaseTabs/
                  ProgressPanel/the visualizers below, which are the other, mutually
                  exclusive generation states. */}
              {backlogReady && output && (
                <div className={styles.backlogTopBar}>
                  <BacklogHeader
                    output={output}
                    title={projectDetail?.name || output.project_name || 'Backlog'}
                    quality={quality}
                    onOpenQuality={() => setQualitySheetOpen(true)}
                    onExport={() => {
                      if (genId) window.location.href = exportExcelUrl(genId)
                    }}
                    onOpenRedmine={() => {
                      setRedmineScope(null)
                      setRedmineOpen(true)
                    }}
                    onOpenBitbucket={() => {
                      setBitbucketScope(null)
                      setBitbucketOpen(true)
                    }}
                    onOpenProjectSettings={() => {
                      const targetProjId = route.projectId ?? output.project_id
                      if (targetProjId) {
                        setProjectSettingsId(targetProjId)
                        setProjectSettingsOpen(true)
                      }
                    }}
                    onNewRun={handleNewRun}
                    onGenerateTasks={
                      genId ? () => void gen.runRemainingPhases('tasks', genId) : undefined
                    }
                  />
                  {/* One generation, several addressable pages instead of one very long
                      one — the tabs are links, so any of these can be opened in its own
                      browser tab (see lib/route.ts and BacklogTabs). */}
                  <BacklogTabs
                    genId={genId}
                    active={route.view}
                    counts={backlogCounts(output, state.hierarchy)}
                    onNavigate={(view) => {
                      if (isProjectBacklog && route.projectId != null) {
                        go(projectPath(route.projectId, 'backlog', view))
                      } else {
                        navigateToBacklog(genId, view)
                      }
                    }}
                  />
                </div>
              )}

              {/* Keep the phase navigation stable while its next phase runs.
                  Progress and live results appear below instead of replacing it. */}
              {state.awaitingPhase && output && (
                <PhaseTabs
                  awaitingPhase={state.awaitingPhase}
                  output={output}
                  hierarchy={state.hierarchy}
                  isGenerating={state.isGenerating}
                  onGenerateNext={() => void gen.runPhase(state.awaitingPhase!, genId)}
                  onGenerateAllRemaining={
                    genId ? () => void gen.runRemainingPhases(state.awaitingPhase!, genId) : undefined
                  }
                  handlers={rowHandlers}
                />
              )}

              {showProgress && (
                <ProgressPanel
                  step={state.step!}
                  message={state.progressMessage}
                  counts={{ epics: state.liveEpics.length, stories: state.liveStories.length, tasks: state.liveTasks.length }}
                  onStop={gen.stop}
                  startedAt={state.startedAt}
                  estimatedSeconds={state.estimatedSeconds}
                />
              )}

              {/* Admins get the same (and richer — click-to-edit) picture from WorkflowVisualizer
                  right below, so this read-only live map would just be a duplicate for them. */}
              {state.isGenerating && !canAccessWorkflowVisualizer && (
                <EpicProgressMap epics={state.liveEpics} stories={state.liveStories} tasks={state.liveTasks} />
              )}

              {/* The visualizer is a live-progress aid. Once a phase pauses, PhaseTabs is the
                  single checkpoint UI; rendering both made users read the same backlog twice. */}
              {canAccessWorkflowVisualizer && state.isGenerating && (
                <WorkflowVisualizer
                  liveEpics={state.liveEpics}
                  liveStories={state.liveStories}
                  liveTasks={state.liveTasks}
                  hierarchy={state.hierarchy}
                  output={output}
                  isGenerating={state.isGenerating}
                  onOpenDetail={setDetailTarget}
                />
              )}

              {state.error && <ErrorBanner message={state.error.message} userAction={state.error.userAction} />}

              {backlogReady && output && (
                <>
                  <div className={styles.backlogBody}>
                    <div className={styles.backlogMain}>
                      {isPhaseView(route.view) ? (
                        <div className={`card ${styles.phasePage}`}>
                          <PhaseList
                            phase={route.view}
                            content={phaseContent(output, state.hierarchy)}
                            handlers={rowHandlers}
                            onGeneratePhase={(p) => {
                              if (genId) {
                                if (p === 'tasks') void gen.runRemainingPhases('tasks', genId)
                                else void gen.runPhase('tests', genId)
                              }
                            }}
                            isGenerating={state.isGenerating}
                          />
                        </div>
                      ) : (
                        <OutputView
                          output={output}
                          hierarchy={state.hierarchy}
                          onEpicStatusChange={rowHandlers.onEpicStatusChange}
                          onStoryStatusChange={rowHandlers.onStoryStatusChange}
                          onTaskStatusChange={rowHandlers.onTaskStatusChange}
                          onEpicPriorityChange={rowHandlers.onEpicPriorityChange}
                          onStoryPriorityChange={rowHandlers.onStoryPriorityChange}
                          onTaskPriorityChange={rowHandlers.onTaskPriorityChange}
                          onAssigneeChange={(dbId, value) =>
                            void withStatusUpdate(() => updateTaskAssignee(dbId, value || null), genId)
                          }
                          onOpenDetail={setDetailTarget}
                          onCreateEpic={() => {
                            if (genId) setCreateTarget({ kind: 'epic', generationId: genId })
                          }}
                          showMeta={route.view === 'overview'}
                          railOpen={qualityRailOpen}
                          onToggleRail={() => setQualityRailOpen((v) => !v)}
                          onGenerateRemaining={
                            genId ? () => void gen.runRemainingPhases('tasks', genId) : undefined
                          }
                          hierarchyFocusStoryId={route.view === 'hierarchy' ? hierarchyFocusStoryId : null}
                        />
                      )}
                    </div>

                    <QualityRail
                      output={output}
                      sheetOpen={qualitySheetOpen}
                      onCloseSheet={() => setQualitySheetOpen(false)}
                      collapsed={!qualityRailOpen}
                      onCopy={copyBacklog}
                      onRepairDependencies={() => {
                        if (!genId) return
                        setRepairingDependencies(true)
                        void repairTaskDependencies(genId)
                          .then(() => gen.loadFromHistory(genId))
                          .catch((e) => showToast('Repair failed', e instanceof ApiError ? e.message : 'Could not repair task dependencies', 'error'))
                          .finally(() => setRepairingDependencies(false))
                      }}
                      repairingDependencies={repairingDependencies}
                      onAnalyzeWeakItems={handleAnalyzeWeakItems}
                      onFixWeakItems={handleFixWeakItems}
                      boostingQuality={boostingQuality}
                      fixProgress={fixProgress}
                    />
                  </div>
                </>
              )}

              {/* Addressed a backlog by id and it hasn't arrived yet. Distinct from
                  "nothing here" below — showing the empty state during the fetch
                  told the user their backlog didn't exist for as long as it took. */}
              {backlogIsEmpty && route.genId != null && (
                <div className="card" aria-busy="true">
                  <SkeletonList rows={4} />
                </div>
              )}

              {backlogIsEmpty && route.genId == null && (
                <div className={`card ${styles.emptyState}`}>
                  <p>No backlog open</p>
                  <p className="text-muted">Start one from Create, or pick an existing backlog from the list.</p>
                  <div className={styles.emptyActions}>
                    <button className="btn btn-primary" onClick={() => go(createPath('write'))}>
                      Create a backlog
                    </button>
                    <button className="btn btn-secondary" onClick={() => go(tabPath('backlogs'))}>
                      Browse backlogs
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </main>

      <DetailModal
        target={detailTarget}
        onClose={() => setDetailTarget(null)}
        onPushToRedmine={(epicId, epicTitle) => {
          setRedmineScope({ epicId, label: epicTitle })
          setDetailTarget(null)
          setRedmineOpen(true)
        }}
        onSaved={() => {
          if (genId) void gen.refreshHierarchy(genId)
        }}
        onCreateChild={setCreateTarget}
      />

      <CreateItemModal
        target={createTarget}
        onClose={() => setCreateTarget(null)}
        onCreated={() => {
          if (genId) void gen.refreshHierarchy(genId)
        }}
      />

      <RedmineModal
        open={redmineOpen}
        onClose={() => setRedmineOpen(false)}
        output={output}
        genId={genId}
        scope={redmineScope}
        onPushed={() => {
          if (genId) void gen.refreshHierarchy(genId)
        }}
      />

      <BitbucketModal
        open={bitbucketOpen}
        onClose={() => setBitbucketOpen(false)}
        output={output}
        genId={genId}
        scope={bitbucketScope}
        onPushed={() => {
          if (genId) void gen.refreshHierarchy(genId)
        }}
      />

      <ProjectSettingsModal
        open={projectSettingsOpen}
        projectId={projectSettingsId}
        onClose={() => {
          setProjectSettingsOpen(false)
          if (route.projectId) {
            void getProject(route.projectId).then(setProjectDetail).catch(() => {})
          }
        }}
        onDeleted={() => {
          setProjectSettingsOpen(false)
          if (route.projectId === projectSettingsId) {
            go(projectPath(null))
          }
        }}
      />
    </div>
  )
}
