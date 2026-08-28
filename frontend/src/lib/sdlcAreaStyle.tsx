/** Icon + accent color per SDLC area (app/services/knowledge_base.py's
 * SDLC_AREAS) — shared between the sidebar's Knowledge Base sub-tree,
 * KnowledgeBaseView's grouped list, and each area's own dedicated page, so
 * an area reads as the same visual identity everywhere it appears (same
 * "consistent icon vocabulary" spirit as icons/appIcons.ts).
 *
 * Colors are the dataviz skill's validated 8-hue categorical set (light/dark
 * pair each), cycled — the same "fixed small palette, cycled for more
 * identities than slots" pattern this app's own PullRequestsView.tsx already
 * uses for repo/avatar colors. This is icon+label identity, not an
 * adjacent-series chart, so the skill's 3-slot all-pairs cap doesn't apply
 * here (see color-formula.md's all-pairs-vs-adjacent-pairs distinction) — 15
 * always-solo labels, never compared side by side the way stacked bars are. */
import type { CSSProperties } from 'react'
import {
  BookOpen,
  CheckSquare,
  ClipboardList,
  CloudUpload,
  Database,
  FileText,
  Gauge,
  Network,
  Plug,
  Server,
  Settings2,
  ShieldCheck,
  Target,
  Users,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { SDLC_AREAS } from '../types'
import type { SdlcArea } from '../types'

const AREA_COLORS: { light: string; dark: string }[] = [
  { light: '#2a78d6', dark: '#3987e5' }, // blue
  { light: '#eb6834', dark: '#d95926' }, // orange
  { light: '#1baf7a', dark: '#199e70' }, // aqua
  { light: '#eda100', dark: '#c98500' }, // yellow
  { light: '#e87ba4', dark: '#d55181' }, // magenta
  { light: '#008300', dark: '#008300' }, // green
  { light: '#4a3aa7', dark: '#9085e9' }, // violet
  { light: '#e34948', dark: '#e66767' }, // red
]

export const AREA_ICONS: Record<SdlcArea, LucideIcon> = {
  'Business Context': Target,
  'Domain & Glossary': BookOpen,
  'Actors & Roles': Users,
  'Business Processes': Workflow,
  'Business Rules': ClipboardList,
  'Functional Requirements': FileText,
  'Non-Functional Requirements': Gauge,
  'Architecture Decisions': Network,
  'System Architecture': Server,
  'Data Domain': Database,
  'APIs & Integrations': Plug,
  'Security & Compliance': ShieldCheck,
  'Testing Knowledge': CheckSquare,
  'Deployment & Release': CloudUpload,
  'Operations & Production': Settings2,
}

export function areaColor(area: string): { light: string; dark: string } {
  const index = SDLC_AREAS.indexOf(area as SdlcArea)
  return AREA_COLORS[(index < 0 ? SDLC_AREAS.length : index) % AREA_COLORS.length]
}

/** CSS custom properties for one area's icon color — both light and dark
 * values are set; the consuming stylesheet's `:root[data-theme='dark']`
 * override picks between them per the viewer's theme, never a JS-computed
 * single value that would ignore it. Consumers must declare
 * `--area-icon-light`/`--area-icon-dark` in their own check-tokens.mjs
 * EXTERNALLY_DEFINED list (see KnowledgeBaseView.module.css's). */
export function areaColorVars(area: string): CSSProperties {
  const color = areaColor(area)
  return { '--area-icon-light': color.light, '--area-icon-dark': color.dark } as CSSProperties
}
