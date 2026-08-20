import { ChatWindow } from './ChatWindow'
import { GenerationNotice } from '../GenerationNotice'

export function ChatTab({
  resetKey,
  isGenerating,
  onSubmit,
  onViewBacklog,
  initialText = '',
}: {
  resetKey: number
  isGenerating: boolean
  onSubmit: (text: string) => void
  onViewBacklog: () => void
  initialText?: string
}) {
  return <>
    {isGenerating && <GenerationNotice onViewBacklog={onViewBacklog} />}
    <ChatWindow key={resetKey} onReady={onSubmit} disabled={isGenerating} initialText={initialText} />
  </>
}
