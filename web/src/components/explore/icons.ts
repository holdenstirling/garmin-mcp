// Sport icons and hint colours shared by the Explore screens (icons already used in the app).
import { Activity, Bike, Footprints, Layers, Mountain, Waves } from 'lucide-react'
import type { ExploreCategory, HintTone } from '@/lib/explore'

export const CATEGORY_ICON: Record<ExploreCategory, typeof Bike> = {
  road: Footprints, trail: Mountain, ultra: Mountain, triathlon: Layers, duathlon: Layers, cycling: Bike,
  gravel: Bike, mtb: Bike, swim: Waves, hike: Mountain, obstacle: Activity, other: Activity,
}
export const HINT_CLS: Record<HintTone, string> = {
  helps: 'bg-(--accent-subtle) text-(--accent)',
  watch: 'bg-(--warning-subtle) text-(--warning)',
  risk: 'bg-(--danger-subtle) text-(--danger)',
  neutral: 'bg-(--bg-elevated) text-(--text-secondary)',
}
