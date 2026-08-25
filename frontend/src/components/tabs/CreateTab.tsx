import { FileText, MessageSquareText, Upload, type LucideIcon } from 'lucide-react'
import { BriefTab } from './BriefTab'
import { ChatTab } from './ChatTab'
import { UploadTab } from './UploadTab'
import type { CreateMode } from '../../lib/route'
import styles from './CreateTab.module.css'

const MODES: { id: CreateMode; label: string; hint: string; icon: LucideIcon }[] = [
  {
    id: 'write',
    label: 'Write',
    hint: 'Paste a finished brief, or start from the template.',
    icon: FileText,
  },
  {
    id: 'chat',
    label: 'Chat',
    hint: "Describe the project and I'll ask what I'm missing.",
    icon: MessageSquareText,
  },
  {
    id: 'upload',
    label: 'Upload',
    hint: 'Bring a Markdown or Word brief you already have.',
    icon: Upload,
  },
]

/**
 * One destination for "get a brief into the app", with a mode switch — replacing the
 * three sidebar entries (Brief / Chat / Upload) that made three doors to a single
 * action look like three separate features.
 *
 * This is a wrapper, not a rewrite: BriefTab, ChatTab and UploadTab are rendered with
 * exactly the props they always took, and all the submit wiring still lives in App.
 */
export function CreateTab({
  mode,
  onModeChange,
  isGenerating,
  chatResetKey,
  chatSeed,
  onTextSubmit,
  onChatSubmit,
  onFileSubmit,
  onViewBacklog,
  projectId,
  projectRepoCount,
}: {
  mode: CreateMode
  onModeChange: (mode: CreateMode) => void
  isGenerating: boolean
  chatResetKey: number
  chatSeed: string
  onTextSubmit: (text: string) => void
  onChatSubmit: (text: string) => void
  onFileSubmit: (file: File) => void
  onViewBacklog: () => void
  /** Set when this run is attached to a Project (App.tsx's selectedProjectId)
   * — passed through to BriefTab's "From repository" brief generation. */
  projectId?: number | null
  projectRepoCount?: number
}) {
  const active = MODES.find((m) => m.id === mode) ?? MODES[0]

  return (
    <div>
      <div className={styles.modes} role="tablist" aria-label="Input mode">
        {MODES.map((m) => {
          const Icon = m.icon
          return (
            <button
              key={m.id}
              role="tab"
              aria-selected={m.id === mode}
              className={`${styles.mode} ${m.id === mode ? styles.modeActive : ''}`}
              onClick={() => onModeChange(m.id)}
            >
              <Icon className={styles.modeIcon} aria-hidden="true" />
              {m.label}
            </button>
          )
        })}
        <span className={styles.hint}>{active.hint}</span>
      </div>

      {mode === 'write' && (
        <BriefTab
          isGenerating={isGenerating}
          onSubmit={onTextSubmit}
          onViewBacklog={onViewBacklog}
          projectId={projectId}
          projectRepoCount={projectRepoCount}
        />
      )}
      {mode === 'upload' && (
        <UploadTab isGenerating={isGenerating} onSubmit={onFileSubmit} onViewBacklog={onViewBacklog} />
      )}
      {/* Kept mounted, only hidden: the transcript is real work, and losing it by
          clicking "Upload" to check something would be a nasty surprise. The other
          two modes hold nothing worth preserving, so they unmount normally. */}
      <div className={mode === 'chat' ? undefined : styles.hidden}>
        <ChatTab
          resetKey={chatResetKey}
          isGenerating={isGenerating}
          onSubmit={onChatSubmit}
          onViewBacklog={onViewBacklog}
          initialText={chatSeed}
        />
      </div>
    </div>
  )
}
