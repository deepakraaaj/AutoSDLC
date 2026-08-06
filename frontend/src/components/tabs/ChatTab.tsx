import { ChatWindow } from './ChatWindow'

export function ChatTab({
  resetKey,
  isGenerating,
  onSubmit,
  initialText = '',
}: {
  resetKey: number
  isGenerating: boolean
  onSubmit: (text: string) => void
  initialText?: string
}) {
  // Submitting auto-navigates to the Backlog tab (see App.tsx), so this only
  // stays visible if you manually switch back here mid-generation — in
  // which case a disabled composer is the right call, not hiding the tab.
  return <ChatWindow key={resetKey} onReady={onSubmit} disabled={isGenerating} initialText={initialText} />
}
