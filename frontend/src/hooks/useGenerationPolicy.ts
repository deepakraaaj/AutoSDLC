import { useCallback } from 'react'
import type { UseGenerationReturn } from './useGeneration'
import { useRole } from './useRole'
import type { QualitySettings } from '../components/GenerationSettings'

/** Decides *how* to generate — one-click vs step-by-step — from quality
 * settings plus the current role, and applies the quality-instructions
 * prompt formatting. Kept separate from useGeneration (which only knows how
 * to run each primitive action, nothing about settings or roles) and from
 * the page component (which should just wire UI intent to `generate`,
 * not contain the policy itself). */
export function useGenerationPolicy(gen: UseGenerationReturn, qualitySettings: QualitySettings) {
  const { canUseOneClickGeneration } = useRole()

  const generate = useCallback(
    async (text: string, projectId?: number | null) => {
      const instructions = qualitySettings.instructions.trim()
      const fullText = instructions
        ? `${text}\n\n[GENERATION GUIDANCE — apply as quality rules; do not turn these rules into product features]\n${instructions}`
        : text
      // A saved 'auto' preference from before a role switch (or before this
      // role even existed) must not silently grant one-click access — the
      // GenerationSettings dropdown also hides the option, but this is the
      // actual enforcement point since every entry tab funnels through here.
      if (qualitySettings.generationMode === 'auto' && canUseOneClickGeneration) {
        await gen.runGenerate(fullText, {}, projectId)
      } else {
        await gen.runPhase('epics', null, fullText, projectId)
      }
    },
    [gen, qualitySettings, canUseOneClickGeneration],
  )

  return { generate }
}
