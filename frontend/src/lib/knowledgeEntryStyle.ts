/** Label + badge color per knowledge-entry kind (glossary/rule/decision/
 * constraint, and Business Context's own 7 kinds) — shared between
 * KnowledgeBaseView, KnowledgeAreaView, and BusinessContextKindView so the
 * fact kinds read identically everywhere they're shown. Split into its own
 * constants-only module (rather than living alongside the components that
 * use it) so those files stay Fast-Refresh-friendly. */
import type { BusinessContextKind, KnowledgeEntryType } from '../types'

export const TYPE_LABELS: Record<KnowledgeEntryType, string> = {
  glossary: 'Glossary',
  rule: 'Business rule',
  decision: 'Decision',
  constraint: 'Constraint',
}

export const TYPE_ORDER: KnowledgeEntryType[] = ['glossary', 'rule', 'decision', 'constraint']

// Distinct color per fact kind (global badge classes — styles/primitives.css)
// instead of one flat accent tint for all four — matches the reference
// extraction table's own color-per-category convention, and lets a reader
// tell glossary/rule/decision/constraint apart at a glance without reading
// the label text.
export const TYPE_BADGE_CLASS: Record<KnowledgeEntryType, string> = {
  glossary: 'badge badge-info',
  rule: 'badge badge-warning',
  decision: 'badge badge-violet',
  constraint: 'badge badge-success',
}

// Same distinct-color-per-kind treatment for Business Context's own
// breakdown. Only 6 badge colors exist in styles/primitives.css for 7
// kinds, so proposed_solution and success_metric share warning — chosen as
// the least confusable pair (they're read at opposite ends of a BRD, rarely
// compared side by side the way two kinds in the same card grid are).
export const BUSINESS_CONTEXT_KIND_BADGE_CLASS: Record<BusinessContextKind, string> = {
  problem_statement: 'badge badge-danger',
  competitive_landscape: 'badge badge-neutral',
  proposed_solution: 'badge badge-warning',
  objective: 'badge badge-info',
  stakeholder: 'badge badge-violet',
  scope_boundary: 'badge badge-success',
  success_metric: 'badge badge-warning',
}

// Body placeholder per kind — shown in the add/edit form's textarea, so a
// blank Problem Statement entry doesn't show an Objective-shaped example
// (or vice versa). One per kind, not one generic Business Context example
// for all 7.
export const BUSINESS_CONTEXT_KIND_BODY_PLACEHOLDER: Record<BusinessContextKind, string> = {
  problem_statement: 'e.g. Facility managers wait an average of 5 business days for approval on routine maintenance requests.',
  competitive_landscape: 'e.g. Competing tools handle facility management and asset tracking separately, requiring manual reconciliation.',
  proposed_solution: 'e.g. A unified platform combining facility hierarchy, asset tracking, and approvals into one system.',
  objective: 'e.g. Reduce manual approval time by 40% within two quarters.',
  stakeholder: 'e.g. Head of Operations — owns the go-live decision and reports project status to the board.',
  scope_boundary: 'e.g. Mobile app support is explicitly out of scope for phase-1.',
  success_metric: 'e.g. 95% of users onboarded within 30 days of launch.',
}
