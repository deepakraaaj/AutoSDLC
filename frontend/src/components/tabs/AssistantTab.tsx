import { AssistantWindow } from './AssistantWindow'
import type { GenerationOutput } from '../../types'

export function AssistantTab({
  lastOutput,
  genId,
  onGenerate,
  onPushed,
  onOpenRedmineModal,
}: {
  lastOutput: GenerationOutput | null
  genId: number | null
  onGenerate: (text: string) => void
  onPushed: () => void
  onOpenRedmineModal: () => void
}) {
  return (
    <AssistantWindow
      lastOutput={lastOutput}
      genId={genId}
      onGenerate={onGenerate}
      onPushed={onPushed}
      onOpenRedmineModal={onOpenRedmineModal}
    />
  )
}
