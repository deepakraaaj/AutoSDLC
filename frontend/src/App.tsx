import { useState } from 'react'
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
import { PhaseTabs } from './components/output/PhaseTabs'
import { DetailModal, type DetailTarget } from './components/output/DetailModal'
import { RedmineModal, type RedmineScope } from './components/redmine/RedmineModal'
import { useGeneration } from './hooks/useGeneration'
import { useToast } from './hooks/useToast'
import {
  ApiError,
  exportExcelUrl,
  updateEpicStatus,
  updateStoryStatus,
  updateTaskStatus,
  updateTaskAssignee,
} from './api/client'
import type { EpicStatus, StoryStatus, TaskStatus } from './types'
import styles from './App.module.css'
import { DEFAULT_QUALITY_INSTRUCTIONS, GenerationSettings, type QualitySettings } from './components/GenerationSettings'
import { extractBrief } from './api/client'
import { useGenerationPolicy } from './hooks/useGenerationPolicy'

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
  const [tab, setTab] = useState<TabId>('brief')
  const [chatResetKey, setChatResetKey] = useState(0)
  const [redmineOpen, setRedmineOpen] = useState(false)
  const [redmineScope, setRedmineScope] = useState<RedmineScope | null>(null)
  const [detailTarget, setDetailTarget] = useState<DetailTarget | null>(null)
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
  const { generate: generateForBacklog } = useGenerationPolicy(gen, qualitySettings)

  function setQualitySettings(value: QualitySettings) {
    setQualitySettingsState(value)
    localStorage.setItem('quality-settings', JSON.stringify(value))
  }

  async function generateWithQuality(text: string) {
    setTab('backlog')
    await generateForBacklog(text)
  }

  function handleTextSubmit(text: string) {
    if (!qualitySettings.clarifyFirst) return void generateWithQuality(text)
    setChatSeed(text)
    setChatResetKey((key) => key + 1)
    setTab('chat')
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
    setTab('chat')
  }

  async function handleOpenHistoryItem(id: number) {
    setTab('backlog')
    await gen.loadFromHistory(id)
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
  const page = PAGE_COPY[tab]
  const backlogIsEmpty = !state.isGenerating && !state.lastOutput && !state.error
  const compactBacklog = tab === 'backlog' && Boolean(state.lastOutput) && !state.isGenerating

  return (
    <div className={styles.shell}>
      <Sidebar active={tab} onChange={setTab} />
      <main className={styles.content}>
        <div className={styles.inner}>
          {!compactBacklog && <PageHeader title={page.title} description={page.description} />}
          {(tab === 'brief' || tab === 'chat' || tab === 'upload' || tab === 'assistant') && (
            <GenerationSettings value={qualitySettings} onChange={setQualitySettings} />
          )}

          <div style={{ display: tab === 'brief' ? 'block' : 'none' }}>
            <BriefTab isGenerating={state.isGenerating} onSubmit={handleTextSubmit} />
          </div>
          <div style={{ display: tab === 'chat' ? 'block' : 'none' }}>
            <ChatTab resetKey={chatResetKey} isGenerating={state.isGenerating} onSubmit={generateWithQuality} initialText={chatSeed} />
          </div>
          <div style={{ display: tab === 'upload' ? 'block' : 'none' }}>
            <UploadTab isGenerating={state.isGenerating} onSubmit={handleFileSubmit} />
          </div>
          <div style={{ display: tab === 'assistant' ? 'block' : 'none' }}>
            <AssistantTab
              lastOutput={state.lastOutput}
              genId={genId}
              onGenerate={generateWithQuality}
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

            {state.isGenerating && (
              <EpicProgressMap epics={state.liveEpics} stories={state.liveStories} tasks={state.liveTasks} />
            )}

            {state.error && <ErrorBanner message={state.error.message} userAction={state.error.userAction} />}

            {state.awaitingPhase && !state.isGenerating && state.lastOutput && (
              <PhaseTabs
                awaitingPhase={state.awaitingPhase}
                output={state.lastOutput}
                hierarchy={state.hierarchy}
                onGenerateNext={() => void gen.runPhase(state.awaitingPhase!, genId)}
                onEpicStatusChange={(dbId, status) =>
                  void withStatusUpdate(() => updateEpicStatus(dbId, status as EpicStatus), genId)
                }
                onStoryStatusChange={(dbId, status) =>
                  void withStatusUpdate(() => updateStoryStatus(dbId, status as StoryStatus), genId)
                }
                onTaskStatusChange={(dbId, status) =>
                  void withStatusUpdate(() => updateTaskStatus(dbId, status as TaskStatus), genId)
                }
                onOpenDetail={setDetailTarget}
              />
            )}

            {state.lastOutput && !state.isGenerating && !state.awaitingPhase && (
              <>
                <div className={styles.backlogSummaryBar}>
                  <PageHeader title={page.title} description={page.description} compact />
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
                <OutputView
                  output={state.lastOutput}
                  showDashboard={false}
                  hierarchy={state.hierarchy}
                  onEpicStatusChange={(dbId, status) =>
                    void withStatusUpdate(() => updateEpicStatus(dbId, status as EpicStatus), genId)
                  }
                  onStoryStatusChange={(dbId, status) =>
                    void withStatusUpdate(() => updateStoryStatus(dbId, status as StoryStatus), genId)
                  }
                  onTaskStatusChange={(dbId, status) =>
                    void withStatusUpdate(() => updateTaskStatus(dbId, status as TaskStatus), genId)
                  }
                  onAssigneeChange={(dbId, value) =>
                    void withStatusUpdate(() => updateTaskAssignee(dbId, value || null), genId)
                  }
                  onOpenDetail={setDetailTarget}
                />
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
