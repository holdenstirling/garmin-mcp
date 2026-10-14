// Explore races: RunSignup search (server-side, cached), "Find more with Rabbit" web search,
// and "Add to my races". Everything comes back as plain text; render it as text only.
import { getJSON, sendJSON } from '@/lib/api'
import { fmtDist } from '@/lib/format'
import type { RaceEvent } from '@/lib/events'

export type ExploreCategory =
  | 'road' | 'trail' | 'ultra' | 'triathlon' | 'duathlon' | 'cycling' | 'gravel' | 'mtb'
  | 'swim' | 'hike' | 'obstacle' | 'other'
export type ExploreDistance = '5k' | '10k' | 'half' | 'marathon' | 'ultra' | 'sprint' | 'olympic' | '70.3' | '140.6'
export type HintTone = 'helps' | 'watch' | 'risk' | 'neutral'

export type ExploreRaceEvent = {
  name: string; distance_km: number | null; distance_label: string; type: ExploreCategory
  start_time: string | null; date: string; fee_from: string | null
}
export type ExploreRace = {
  id: string; source: 'runsignup' | 'web'; name: string; date: string; end_date: string | null
  city: string; state: string; zip: string; location?: string
  url: string | null; website: string | null; logo: string | null
  registration_open: boolean | null; summary: string
  events: ExploreRaceEvent[]; types: ExploreCategory[]; min_km: number | null; max_km: number | null
  hints: { id: string; label: string; tone: HintTone }[]
}
export type ExploreFilters = {
  near: string; radius: number; months: number; types: ExploreCategory[]; distance: ExploreDistance | null; q: string
}
export type ExploreDefaults = { near: string; types: ExploreCategory[]; radius: number; months: number }
export type ExploreResult = { races: ExploreRace[]; page: number; has_more: boolean; capped: boolean; partial: boolean }

export const CATEGORY_LABEL: Record<ExploreCategory, string> = {
  road: 'Road', trail: 'Trail', ultra: 'Ultra', triathlon: 'Triathlon', duathlon: 'Duathlon', cycling: 'Cycling',
  gravel: 'Gravel', mtb: 'MTB', swim: 'Swim', hike: 'Hike', obstacle: 'Obstacle', other: 'Other',
}
export const CATEGORIES = Object.keys(CATEGORY_LABEL) as ExploreCategory[]
export const DISTANCE_CHIPS: [ExploreDistance, string][] = [
  ['5k', '5K'], ['10k', '10K'], ['half', 'Half'], ['marathon', 'Marathon'], ['ultra', 'Ultra'],
  ['sprint', 'Sprint tri'], ['olympic', 'Olympic'], ['70.3', '70.3'], ['140.6', '140.6'],
]
export const RADII = [10, 25, 50, 100, 250]
export const MONTHS = [1, 3, 6, 12]

function query(f: ExploreFilters, page: number): string {
  const p = new URLSearchParams()
  if (f.near.trim()) p.set('near', f.near.trim())
  p.set('radius', String(f.radius))
  p.set('months', String(f.months))
  if (f.types.length) p.set('types', f.types.join(','))
  if (f.distance) p.set('distance', f.distance)
  if (f.q.trim()) p.set('q', f.q.trim())
  p.set('page', String(page))
  return p.toString()
}

export const searchRaces = (f: ExploreFilters, page = 1) => getJSON<ExploreResult>(`/api/explore?${query(f, page)}`)
export const exploreDefaults = () => getJSON<ExploreDefaults>('/api/explore/defaults')
export const findWithRabbit = (f: ExploreFilters) =>
  sendJSON<{ races: ExploreRace[] }>('POST', '/api/explore/ai', {
    near: f.near.trim(), radius: f.radius, months: f.months, types: f.types,
    distance: f.distance ?? '', q: f.q.trim(),
  })
export const addRace = (race: ExploreRace, eventIndex: number | null) =>
  sendJSON<{ event: RaceEvent; already: boolean; events: RaceEvent[] }>('POST', '/api/explore/add', {
    race, event_index: eventIndex,
  })

const STORE_KEY = 'rabbit.explore.filters'
export function loadFilters(): Partial<ExploreFilters> | null {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (!raw) return null
    const v = JSON.parse(raw) as Partial<ExploreFilters>
    return v && typeof v === 'object' ? v : null
  } catch { return null }
}
export function saveFilters(f: ExploreFilters): void {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(f)) } catch { /* private mode */ }
}

/** "Sat, May 22" (adds the year when it isn't this year). */
export function raceDate(d: string): string {
  const dt = new Date(`${d}T12:00:00`)
  const sameYear = dt.getFullYear() === new Date().getFullYear()
  return dt.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }) })
}
export function monthLabel(d: string): string {
  return new Date(`${d}T12:00:00`).toLocaleDateString([], { month: 'long', year: 'numeric' })
}
export function placeOf(r: ExploreRace): string {
  return [r.city, r.state].filter(Boolean).join(', ') || r.location || ''
}
export function distanceText(e: ExploreRaceEvent, imperial: boolean): string {
  if (e.distance_label) return e.distance_label
  if (e.distance_km == null) return e.name
  return fmtDist(e.distance_km, imperial)
}
export function feeFrom(r: ExploreRace): string | null {
  const fees = r.events.map((e) => e.fee_from).filter((x): x is string => !!x)
  if (!fees.length) return null
  return fees.reduce((a, b) => (Number(a.replace(/[^0-9.]/g, '')) <= Number(b.replace(/[^0-9.]/g, '')) ? a : b))
}
