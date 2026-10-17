// Training buddies (server: buddies.py): opt-in matching with people near you at a similar easy
// pace and usual times. Others see a pace band, times, race, note, city and a rounded distance:
// never your exact location, heart rate or single workouts.
import { getJSON, sendJSON } from '@/lib/api'
import type { SocialUser } from '@/lib/social'

export type BuddySport = 'run' | 'trail' | 'ride' | 'swim'
export const BUDDY_SPORTS: readonly (readonly [BuddySport, string])[] = [['run', 'Run'], ['trail', 'Trail'], ['ride', 'Ride'], ['swim', 'Swim']]
export const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
export const WHEN = ['morning', 'midday', 'evening'] as const
/** run / trail: seconds per km; ride: km/h; swim: seconds per 100 m */
export type Band = [number, number]
export type BuddyProfile = {
  sports: BuddySport[]; pace: Partial<Record<BuddySport, Band>>; slots: string[]
  race: string; note: string; paused: boolean; updated?: number
}
export type BuddyState = {
  profile: BuddyProfile | null
  suggested: { sports: BuddySport[]; pace: Partial<Record<BuddySport, Band>>; slots: string[] }
  area: { city: string; radius_mi: number; has_point: boolean }
}
export type BuddyMatch = {
  person: SocialUser; sport: BuddySport; sports: BuddySport[]; chips: string[]; shared_slots: string[]
  distance_mi: number | null; pace: Band | null; slots: string[]; race: string; note: string; city: string
  following: boolean; follows_you: boolean
}

export const getBuddies = () => getJSON<BuddyState>('/api/buddies')
export const saveBuddies = (p: BuddyProfile) => sendJSON<BuddyState>('PUT', '/api/buddies', p)
export const deleteBuddies = () => sendJSON<{ ok: boolean }>('DELETE', '/api/buddies', {})
export const getBuddyMatches = () => getJSON<{ matches: BuddyMatch[]; reason: 'off' | 'paused' | 'none' | null }>('/api/buddies/matches')
export const sayHi = (id: string, text?: string) => sendJSON<{ conv: { id: string } }>('POST', `/api/buddies/${encodeURIComponent(id)}/hi`, text ? { text } : {})
export const hideBuddy = (id: string) => sendJSON<{ ok: boolean }>('POST', `/api/buddies/${encodeURIComponent(id)}/hide`, {})

const KM_PER_MI = 1.609344
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

/** "9:00-9:45 /mi", "14-16 mph", "2:05-2:20 /100yd" in the athlete's units. */
export function bandText(sport: BuddySport, b: Band | null | undefined, imperial: boolean): string {
  if (!b) return ''
  const [lo, hi] = [Math.min(...b), Math.max(...b)]
  if (sport === 'ride') {
    const f = imperial ? 1 / KM_PER_MI : 1
    return `${Math.round(lo * f)}-${Math.round(hi * f)} ${imperial ? 'mph' : 'km/h'}`
  }
  if (sport === 'swim') {
    const f = imperial ? 0.9144 : 1  // per 100 yd is 91.44 m
    return `${mmss(lo * f)}-${mmss(hi * f)} /100${imperial ? 'yd' : 'm'}`
  }
  const f = imperial ? KM_PER_MI : 1
  return `${mmss(lo * f)}-${mmss(hi * f)} /${imperial ? 'mi' : 'km'}`
}

/** ["tue-evening", "thu-evening"] -> "Tue & Thu evenings" */
export function slotsText(slots: string[]): string {
  const by: Record<string, string[]> = {}
  for (const s of slots) {
    const [d, w] = s.split('-') as [string, string]
    ;(by[w] ??= []).push(d.charAt(0).toUpperCase() + d.slice(1))
  }
  return WHEN.filter((w) => by[w]).map((w) => `${by[w]!.join(' & ')} ${w}${by[w]!.length > 1 ? 's' : ''}`).join(' · ')
}
