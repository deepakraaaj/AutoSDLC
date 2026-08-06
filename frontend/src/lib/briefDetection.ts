export const BRIEF_PROMPT_MARKERS = [
  '## prompt to paste into ai:',
  'output exactly this format',
  'output exactly this structure',
  '[paste your documents below this line]',
  '[paste your idea below this line]',
  '[paste the output from step 1 here]',
]

export function briefContentLooksLikePrompt(text: string): boolean {
  const normalized = String(text || '').toLowerCase()
  return BRIEF_PROMPT_MARKERS.some((marker) => normalized.includes(marker))
}

export interface DetectedTemplate {
  type:
    | 'structured_brief'
    | 'prd'
    | 'readme'
    | 'feature_list'
    | 'vague_idea'
    | 'unstructured'
  label: string
}

export function detectTemplateType(text: string): DetectedTemplate {
  const hasProjectHeader = /^#\s+Project:/m.test(text)
  const hasSections = /^##\s+/m.test(text)
  const hasMetrics = /metric|success|target|kpi|measurement/i.test(text)
  const hasUsers = /user|role|persona|stakeholder|actor/i.test(text)
  const hasFeatures = /feature|require|function|capability|epic|user story/i.test(text)
  const hasTech = /tech|stack|framework|database|infrastructure|architecture/i.test(text)
  const lineCount = text.split('\n').length
  const wordCount = text.split(/\s+/).length

  const signalCount = [hasMetrics, hasUsers, hasFeatures, hasTech].filter(Boolean).length
  const isPRDLike = hasProjectHeader && hasSections && signalCount >= 3
  const isREADMELike = /readme|overview|about|introduction/i.test(text) && hasFeatures && lineCount > 20
  const isFeatureListLike = /feature|requirement|story|epic/i.test(text) && !hasSections && wordCount < 500
  const isVagueIdea = wordCount < 100 && !hasSections && !hasProjectHeader
  const isBriefFormat = hasProjectHeader && hasSections

  if (isBriefFormat) return { type: 'structured_brief', label: 'Structured Brief' }
  if (isPRDLike) return { type: 'prd', label: 'Product Requirements Document (PRD)' }
  if (isREADMELike) return { type: 'readme', label: 'README or Overview Document' }
  if (isFeatureListLike) return { type: 'feature_list', label: 'Feature List or Requirements' }
  if (isVagueIdea) return { type: 'vague_idea', label: 'Rough Idea or Concept' }
  return { type: 'unstructured', label: 'Unstructured Content' }
}

export function briefFilenameFromContent(text: string): string {
  const projectLine = String(text || '')
    .split('\n')
    .find((line) => line.startsWith('# Project:'))
  const projectName = projectLine ? projectLine.replace('# Project:', '').trim() : ''
  const slug = projectName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `${slug || 'project-brief'}.md`
}
