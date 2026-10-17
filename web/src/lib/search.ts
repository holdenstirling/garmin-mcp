// Search everywhere (server: search.py, GET /app/api/search?q=). Recent searches stay on this
// device. Picking a result fires SEARCH_OPEN_EVENT; screens/Chat.tsx routes it to the right tab.
import { getJSON } from '@/lib/api'
import { openPlanDay } from '@/lib/plancal'
import type { Partner } from '@/lib/clubdir'
import type { ActivityId } from '@/lib/activity'

export type SearchPerson = { id: string; name: string; photo?: number | null; picture?: string; relation: string }
export type SearchClub = { id: string; name: string; city: string; members?: number | null; mine: boolean; source: 'club' | 'directory'; kind?: string; activity?: ActivityId }
export type SearchEvent = { id: string; title: string; date: string | null; location: string; kind: string; past: boolean
  /** someone else's public event near you (opens Local, where you can say you're going) */
  public?: boolean; activity?: string | null }
export type SearchSession = { id: string; date: string; title: string; sport: string; kind: string; minutes?: number | null }
export type SearchWorkout = { id: number; date: string; name: string; sport: string; minutes: number | null; km: number | null }
export type SearchResults = {
  q: string
  /** The owner's partners near you that fit the query (always labelled "Partner"). */
  partners?: Partner[]
  people: SearchPerson[]; clubs: SearchClub[]; events: SearchEvent[]; sessions: SearchSession[]; workouts: SearchWorkout[]
}
export type SearchPick =
  | { kind: 'person'; id: string }
  | { kind: 'club'; id: string; source: 'club' | 'directory' }
  | { kind: 'event'; id: string }
  | { kind: 'session'; id: string; date: string }
  | { kind: 'workout'; id: number }

export const MIN_QUERY = 2
export const search = (q: string) => getJSON<SearchResults>(`/api/search?q=${encodeURIComponent(q)}`)

export const SEARCH_OPEN_EVENT = 'rabbit:search-open'
export function openSearchResult(p: SearchPick) {
  if (p.kind === 'session') {
    openPlanDay(p.date)  // the Plan tab opens on this day (Chat.tsx listens)
    return
  }
  try { window.dispatchEvent(new CustomEvent<SearchPick>(SEARCH_OPEN_EVENT, { detail: p })) } catch { /* ignore */ }
}

const RECENT = 'rabbit.search.recent'
export function recentSearches(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT) ?? '[]')
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').slice(0, 6) : []
  } catch { return [] }
}
export function rememberSearch(q: string) {
  const t = q.trim()
  if (t.length < MIN_QUERY) return
  try { localStorage.setItem(RECENT, JSON.stringify([t, ...recentSearches().filter((x) => x.toLowerCase() !== t.toLowerCase())].slice(0, 6))) } catch { /* ignore */ }
}
export function clearSearches() { try { localStorage.removeItem(RECENT) } catch { /* ignore */ } }
