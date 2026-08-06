import { useEffect, useRef } from 'react'
import type { GenerationOutput, Hierarchy } from '../../types'
import { hierarchyIsPopulated, hierarchyToTree, outputToTree } from '../../lib/tree'
import { copyText } from '../../lib/format'
import { useToast } from '../../hooks/useToast'
import { Dashboard } from './Dashboard'
import { TrustBanner } from './TrustBanner'
import { ValidationChecklist } from './ValidationChecklist'
import { Scorecard } from './Scorecard'
import { HierarchyView } from './HierarchyView'
import { GapsList } from './GapsList'
import type { DetailTarget } from './DetailModal'
import styles from './OutputView.module.css'

export function OutputView({
  output,
  hierarchy,
  onEpicStatusChange,
  onStoryStatusChange,
  onTaskStatusChange,
  onAssigneeChange,
  onOpenDetail,
  showDashboard = true,
}: {
  output: GenerationOutput
  hierarchy: Hierarchy | null
  onEpicStatusChange: (dbId: number, status: string) => void
  onStoryStatusChange: (dbId: number, status: string) => void
  onTaskStatusChange: (dbId: number, status: string) => void
  onAssigneeChange: (dbId: number, value: string) => void
  onOpenDetail: (target: DetailTarget) => void
  showDashboard?: boolean
}) {
  const { showToast } = useToast()
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    rootRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [output])

  const tree = hierarchyIsPopulated(hierarchy) ? hierarchyToTree(hierarchy!) : outputToTree(output)

  function copyOutput() {
    const lines: string[] = []
    output.stories.forEach((s) => {
      lines.push(`[${s.id}] ${s.title}`)
      lines.push(`As a ${s.as_a}, I want to ${s.i_want}, so that ${s.so_that}.`)
      s.acceptance_criteria.forEach((ac) => lines.push(`  ✓ ${ac}`))
      lines.push('')
    })
    output.tasks.forEach((t) => {
      lines.push(`[${t.id}] ${t.title} (${t.estimate_hours} hrs)`)
      lines.push(`  ${t.description}`)
      lines.push(`  Done: ${t.definition_of_done}`)
      lines.push('')
    })
    void copyText(lines.join('\n')).then(() => showToast('Copied', 'Backlog copied to clipboard.', 'info'))
  }

  return (
    <div ref={rootRef}>
      {showDashboard && <Dashboard output={output} />}
      {output.validation && <TrustBanner validation={output.validation} />}
      {(output.validation || output.metrics) && (
        <div className={styles.reviewGrid}>
          {output.validation && <ValidationChecklist validation={output.validation} />}
          {output.metrics && <Scorecard metrics={output.metrics} onCopy={copyOutput} />}
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Hierarchy</h2>
        </div>
        <HierarchyView
          tree={tree}
          onEpicStatusChange={onEpicStatusChange}
          onStoryStatusChange={onStoryStatusChange}
          onTaskStatusChange={onTaskStatusChange}
          onAssigneeChange={onAssigneeChange}
          onOpenDetail={onOpenDetail}
        />
      </div>

      <GapsList gaps={output.gaps} />
    </div>
  )
}
