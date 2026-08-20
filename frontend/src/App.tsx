import { useEffect, useRef, useState } from 'react'
import { Sidebar, type TabId } from './components/Sidebar'
import { PageHeader } from './components/PageHeader'
import { ProgressPanel } from './components/ProgressPanel'
import { ErrorBanner } from './components/ErrorBanner'
import { ActionBar } from './components/ActionBar'
import { BriefTab } from './components/tabs/BriefTab'
import { ChatTab } from './components/tabs/ChatTab'
import { UploadTab } from './components/tabs/UploadTab'
import { AssistantTab } from './components/tabs/AssistantTab'
import { HistoryTab } from './components/tabs/HistoryTab'
import { OutputView } from './components/output/OutputView'
import { Dashboard } from './components/output/Dashboard'
import { EpicProgressMap } from './components/output/EpicProgressMap'
import { WorkflowVisualizer } from './components/output/WorkflowVisualizer'
import { PhaseTabs } from './components/output/PhaseTabs'
import { PhaseList, type PhaseListHandlers } from './components/output/PhaseList'
import { phaseContent, phaseCount } from './lib/phases'
import { BacklogTabs } from './components/output/BacklogTabs'
import { DetailModal, type DetailTarget } from './components/output/DetailModal'
import { CreateItemModal, type CreateTarget } from './components/output/CreateItemModal'
import { RedmineModal, type RedmineScope } from './components/redmine/RedmineModal'
import { useGeneration, type Phase } from './hooks/useGeneration'
import { useToast } from './hooks/useToast'
import { useRole } from './hooks/useRole'
import {
  ApiError,
  exportExcelUrl,
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
import type { EpicStatus, StoryStatus, TaskStatus, GenerationOutput, Hierarchy } from './types'
import { parseRoute, tabPath, backlogPath, type AppRoute, type BacklogView } from './lib/route'
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

const PAGE_COPY: Record<TabId, { title: string; description: string }> = {
  brief: {
    title: 'Brief',
    description:
      'Paste a finished brief or load our template. Best when you have comprehensive requirements, documents, or want full control over structure.',
  },
  chat: {
    title: 'Chat',
    description: "Tell me about your project below. I'll ask a couple of quick questions if I need more detail, then generate your backlog.",
  },
  upload: {
    title: 'Upload',
    description: "Already have a Markdown brief or Word document? Upload it and I'll parse it and generate your backlog directly.",
  },
  assistant: {
    title: 'Assistant',
    description: 'Ask about existing Redmine issues, create or update one, or tell it what to build — it can generate a backlog and push it for you.',
  },
  backlog: {
    title: 'Backlog',
    description: 'The backlog you generate from Brief, Chat, or Upload shows up here — separate from however you fed it in.',
  },
  history: {
    title: 'History',
    description: 'Every backlog generated in this workspace, newest first.',
  },
}

export default function App() {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.pathname))
  const tab = route.tab
  const [chatResetKey, setChatResetKey] = useState(0)
  const [redmineOpen, setRedmineOpen] = useState(false)
  const [redmineScope, setRedmineScope] = useState<RedmineScope | null>(null)
  const [detailTarget, setDetailTarget] = useState<DetailTarget | null>(null)
  const [createTarget, setCreateTarget] = useState<CreateTarget | null>(null)
  const [repairingDependencies, setRepairingDependencies] = useState(false)
  const [boostingQuality, setBoostingQuality] = useState(false)
  // Live progress from the fix run — a few dozen items take several rounds of AI calls
  // and can pause on a provider rate limit, so the panel reports what it's doing.
  const [fixProgress, setFixProgress] = useState<ImproveQualityProgress | null>(null)
  const [chatSeed, setChatSeed] = useState('')
  const [qualitySettings, setQualitySettingsState] = useState<QualitySettings>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem('quality-settings') || '')
      // A settings blob saved before generationMode existed — default it in
      // rather than losing clarifyFirst/instructions the user already set.
      // Defaults to 'stepwise' (not 'auto') so the step-by-step review flow
      // is what a first-time user actually sees, not an opt-in they'd never
      // discover behind a collapsed settings panel.
      return { generationMode: 'stepwise', ...parsed }
    } catch {
      return { clarifyFirst: true, instructions: DEFAULT_QUALITY_INSTRUCTIONS, generationMode: 'stepwise' }
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

  function navigateTo(nextTab: TabId) {
    go(nextTab === 'backlog' ? backlogPath(gen.state.lastGenId) : tabPath(nextTab))
  }

  /** Open a specific generation (and optionally one of its pages). The id lives in the
   * URL, so this address survives a reload, a share, and — the actual point — being
   * opened in a separate browser tab. */
  function navigateToBacklog(targetGenId: number | null, view: BacklogView = 'overview') {
    go(backlogPath(targetGenId, view))
  }

  useEffect(() => {
    const syncRoute = () => setRoute(parseRoute(window.location.pathname))
    window.addEventListener('popstate', syncRoute)
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])

  function setQualitySettings(value: QualitySettings) {
    setQualitySettingsState(value)
    localStorage.setItem('quality-settings', JSON.stringify(value))
  }

  async function generateWithQuality(text: string, openBacklog = false) {
    if (openBacklog) navigateTo('backlog')
    await generateForBacklog(text)
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
    navigateTo('chat')
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
    // Drop the generation id too: leaving it in the URL would have the route effect
    // reload the run that was just cleared.
    loadedGenIdRef.current = null
    go(tabPath('chat'))
  }

  function handleOpenHistoryItem(id: number) {
    navigateToBacklog(id)
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
    if (route.tab !== 'backlog' || route.genId == null) return
    if (loadedGenIdRef.current === route.genId) return
    loadedGenIdRef.current = route.genId
    void gen.loadFromHistory(route.genId)
    // gen.loadFromHistory is stable (useCallback); depending on `gen` would refire this
    // on every generation state change and refetch the backlog mid-edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.tab, route.genId])

  // A run started from Brief/Chat/Upload lands on /app/backlog with no id. Once it has
  // one, put it in the address bar so the page can be reloaded, shared or opened in a
  // second tab. replaceState, not push: this isn't a navigation the back button should
  // have to step through. Only fills a *missing* id, so it never fights the effect above.
  useEffect(() => {
    if (route.tab !== 'backlog' || route.genId != null || state.lastGenId == null) return
    const path = backlogPath(state.lastGenId, route.view)
    window.history.replaceState({}, '', path)
    loadedGenIdRef.current = state.lastGenId
    setRoute(parseRoute(path))
  }, [route.tab, route.genId, route.view, state.lastGenId])

  const page = PAGE_COPY[tab]
  const backlogIsEmpty = !state.isGenerating && !state.lastOutput && !state.error
  const compactBacklog = tab === 'backlog' && Boolean(state.lastOutput) && !state.isGenerating
  // The Backlog tab's own page copy is a generic "Backlog" label with no indication
  // of which project it's actually showing — swap in the real project name (carried
  // on lastOutput the same way generation_id is; see types/index.ts) once one exists,
  // so the page you're staring at scores on says what it's scoring.
  const projectName = tab === 'backlog' ? state.lastOutput?.project_name : undefined
  const pageTitle = projectName || page.title
  const pageDescription = projectName ? undefined : page.description

  return (
    <div className={styles.shell}>
      <Sidebar active={tab} onChange={navigateTo} />
      <main className={styles.content}>
        <div className={`${styles.inner} ${compactBacklog ? styles.backlogCanvas : ''}`}>
          {!compactBacklog && <PageHeader title={pageTitle} description={pageDescription} />}
          {(tab === 'brief' || tab === 'chat' || tab === 'upload' || tab === 'assistant') && (
            <GenerationSettings value={qualitySettings} onChange={setQualitySettings} />
          )}

          <div style={{ display: tab === 'brief' ? 'block' : 'none' }}>
            <BriefTab isGenerating={state.isGenerating} onSubmit={handleTextSubmit} onViewBacklog={() => navigateTo('backlog')} />
          </div>
          <div style={{ display: tab === 'chat' ? 'block' : 'none' }}>
            <ChatTab resetKey={chatResetKey} isGenerating={state.isGenerating} onSubmit={generateWithQuality} onViewBacklog={() => navigateTo('backlog')} initialText={chatSeed} />
          </div>
          <div style={{ display: tab === 'upload' ? 'block' : 'none' }}>
            <UploadTab isGenerating={state.isGenerating} onSubmit={handleFileSubmit} onViewBacklog={() => navigateTo('backlog')} />
          </div>
          <div style={{ display: tab === 'assistant' ? 'block' : 'none' }}>
            <AssistantTab
              lastOutput={state.lastOutput}
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
          </div>
          <div style={{ display: tab === 'history' ? 'block' : 'none' }}>
            <HistoryTab onOpen={handleOpenHistoryItem} />
          </div>

          <div style={{ display: tab === 'backlog' ? 'block' : 'none' }}>
            {/* Keep the phase navigation stable while its next phase runs.
                Progress and live results appear below instead of replacing it. */}
            {state.awaitingPhase && state.lastOutput && (
              <PhaseTabs
                awaitingPhase={state.awaitingPhase}
                output={state.lastOutput}
                hierarchy={state.hierarchy}
                isGenerating={state.isGenerating}
                onGenerateNext={() => void gen.runPhase(state.awaitingPhase!, genId)}
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
                output={state.lastOutput}
                isGenerating={state.isGenerating}
                onOpenDetail={setDetailTarget}
              />
            )}

            {state.error && <ErrorBanner message={state.error.message} userAction={state.error.userAction} />}

            {state.lastOutput && !state.isGenerating && !state.awaitingPhase && (
              <>
                <div className={styles.backlogSummaryBar}>
                  <PageHeader title={pageTitle} description={pageDescription} compact />
                  <ActionBar
                    compact
                    onExport={() => {
                      if (genId) window.location.href = exportExcelUrl(genId)
                    }}
                    onOpenRedmine={() => {
                      setRedmineScope(null)
                      setRedmineOpen(true)
                    }}
                    onNewRun={handleNewRun}
                  />
                  <Dashboard output={state.lastOutput} compact />
                </div>
                {/* One generation, several addressable pages instead of one very long
                    one — the tabs are links, so any of these can be opened in its own
                    browser tab (see lib/route.ts and BacklogTabs). */}
                <BacklogTabs
                  genId={genId}
                  active={route.view}
                  counts={backlogCounts(state.lastOutput, state.hierarchy)}
                  onNavigate={(view) => navigateToBacklog(genId, view)}
                />
                {isPhaseView(route.view) ? (
                  <div className={`card ${styles.phasePage}`}>
                    <PhaseList
                      phase={route.view}
                      content={phaseContent(state.lastOutput, state.hierarchy)}
                      handlers={rowHandlers}
                    />
                  </div>
                ) : (
                  <OutputView
                    output={state.lastOutput}
                    showDashboard={false}
                    section={route.view === 'hierarchy' ? 'hierarchy' : 'overview'}
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
                )}
              </>
            )}

            {backlogIsEmpty && (
              <div className={`card ${styles.emptyState}`}>
                <p>Nothing generated yet.</p>
                <p className="text-muted">
                  Head to <strong>Brief</strong>, <strong>Chat</strong>, or <strong>Upload</strong> to start one —
                  it'll show up here as it builds, live.
                </p>
              </div>
            )}
          </div>
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
        output={state.lastOutput}
        genId={genId}
        scope={redmineScope}
        onPushed={() => {
          if (genId) void gen.refreshHierarchy(genId)
        }}
      />
    </div>
  )
}
