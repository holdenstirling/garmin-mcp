// Explore v2: where you are (device location -> rounded server-side; never precise; or a typed
// zip), "Let Rabbit explore" (For you + an AI web scout + places and groups near you, in one
// tap), Near you (OpenStreetMap places + group activities from the web) and finish-time
// estimates (GET /api/predict).
import { getJSON, sendJSON } from '@/lib/api'
import type { ExploreRace } from '@/lib/explore'

export type LocSource = 'device' | 'manual' | 'home_zip' | 'profile_zip' | 'profile_city' | null
export type ResolvedLocation = {
  source: LocSource; label: string; zip: string; state: string; city: string; searchable: boolean
  nationwide?: boolean; note?: string
}
export type SavedLocation = { zip: string; city: string; state: string; source: 'device' | 'manual'; updated: number } | null
/** `device` mirrors `saved` (older name). */
export type LocationState = { saved: SavedLocation; device: SavedLocation; resolved: ResolvedLocation; use_for_local: boolean }

export type Estimate = {
  kind: 'run' | 'bike' | 'swim' | 'tri'; low: number; high: number; likely: number
  basis: string[]; confidence: 'high' | 'medium' | 'low'; label?: 'rough guide'; text: string
  event?: string; splits?: { swim: number; bike: number; run: number; transitions: number }
}
/** Extra fields Explore v2 adds to races (estimates, unverified popular races, Rabbit's ranking). */
export type RaceX = ExploreRace & {
  estimate?: Estimate; check_dates?: boolean; usual_month?: number; popular?: boolean
  why?: string; tune_up?: boolean; score?: number
}

export type PlaceKind = 'volleyball' | 'track' | 'pool' | 'climbing' | 'bike_park' | 'trailhead' | 'fitness' | 'pickleball' | 'tennis'
/** A place to play from OpenStreetMap (local.py). */
export type Place = {
  id: string; name: string; named: boolean; kind: PlaceKind; kind_label: string; lat: number; lon: number
  distance_km: number; osm_url: string; tags: { lit?: string; surface?: string; access?: string }
}
export type PlacesState = 'ok' | 'off' | 'needs_location' | 'failed'
export type GroupsState = 'ok' | 'off' | 'needs_location' | 'cached_only' | 'limit' | 'unavailable' | 'failed'

export type RabbitExploreResult = {
  intro: string; summary: string; count: number; races: RaceX[]; places: Place[]; groups: LocalActivity[]
  places_state: PlacesState; groups_state: GroupsState; total: number
  web: 'ok' | 'limit' | 'unavailable' | 'failed'; partial: boolean; inferred: boolean; nationwide: boolean
  location: ResolvedLocation
}

export type LocalCategory = 'run' | 'ride' | 'swim' | 'social_sports' | 'yoga' | 'climb' | 'other'
/** A group activity found on the web (always with a URL). */
export type LocalActivity = {
  id: string; name: string; category: LocalCategory; kind: LocalCategory; organizer: string; when: string
  schedule: string; where: string; area: string; cost: string; url: string; why: string; source: 'web'
}
export type LocalResult = {
  city: string; state: string; items: LocalActivity[]; needs_location: boolean; disabled: boolean
  places: Place[]; places_state: PlacesState; groups_state: GroupsState
  suggested: LocalCategory[]; chips: Partial<Record<LocalCategory, string>>; location: ResolvedLocation
}

export const getLocation = () => getJSON<LocationState>('/api/location')
export const saveDeviceLocation = (lat: number, lon: number) =>
  sendJSON<LocationState>('POST', '/api/location', { lat, lon })
export const saveZipLocation = (zip: string) => sendJSON<LocationState>('POST', '/api/location', { zip })
export const setUseForLocal = (on: boolean) => sendJSON<LocationState>('POST', '/api/location/prefs', { use_for_local: on })
export const forgetLocation = () => sendJSON<LocationState>('DELETE', '/api/location')
export const letRabbitExplore = () => sendJSON<RabbitExploreResult>('POST', '/api/explore/rabbit')
/** Near you with a web search for groups when this week's city list isn't cached yet. */
export const getLocal = () => sendJSON<LocalResult>('POST', '/api/explore/local')
/** Near you without spending a web search (places + groups already found this week). */
export const getNearby = () => getJSON<LocalResult>('/api/explore/nearby')

/** The finish estimate shape the race detail renders (both predict API shapes map to it). */
export type Finish = { low_s: number; mid_s: number; high_s: number; confidence: string; basis: string[] }

/** GET /api/predict for a race distance. Resolves null on 404/errors/no estimate, so the
 *  chip simply doesn't show when the predictor isn't there. */
export async function predictFinish(q: { type?: string; distanceKm: number; climbM?: number | null; date?: string; elevationM?: number | null }): Promise<Finish | null> {
  const p = new URLSearchParams({ distance_km: String(q.distanceKm) })
  if (q.type) p.set('type', q.type)
  if (q.climbM != null) p.set('climb_m', String(q.climbM))
  if (q.date) p.set('date', q.date)
  if (q.elevationM != null) p.set('elevation_m', String(q.elevationM))
  try {
    const r = await getJSON<Record<string, unknown>>(`/api/predict?${p.toString()}`)
    return toFinish(r)
  } catch { return null }
}

function num(v: unknown): number | null { return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null }
export function toFinish(r: Record<string, unknown> | null | undefined): Finish | null {
  const e = r?.estimate as Record<string, unknown> | null | undefined
  if (!e || typeof e !== 'object') return null
  const mid = num(e.mid_s) ?? num(e.likely)
  const low = num(e.low_s) ?? num(e.low)
  const high = num(e.high_s) ?? num(e.high)
  if (mid == null || low == null || high == null) return null
  const conf = (r?.confidence ?? e.confidence) as unknown
  const basis = (r?.basis ?? e.basis) as unknown
  return {
    low_s: low, mid_s: mid, high_s: high, confidence: typeof conf === 'string' ? conf : '',
    basis: Array.isArray(basis) ? basis.filter((x): x is string => typeof x === 'string') : typeof basis === 'string' ? [basis] : [],
  }
}

export function predictFor(q: { eventId?: string; distanceKm?: number; type?: string }) {
  const p = new URLSearchParams()
  if (q.eventId) p.set('event_id', q.eventId)
  if (q.distanceKm != null) p.set('distance_km', String(q.distanceKm))
  if (q.type) p.set('type', q.type)
  return getJSON<{ estimate: Estimate | null; reason?: string }>(`/api/predict?${p.toString()}`)
}

/** Browser location, only ever after the athlete taps (never on page load). */
export function askDevicePosition(): Promise<{ lat: number; lon: number }> {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) { reject(new Error("This browser can't share a location. Enter a zip instead.")); return }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      (e) => reject(new Error(e.code === 1
        ? 'Location is blocked for this site. Enter a zip instead, or allow location in your browser settings.'
        : "Couldn't get your location. Enter a zip instead.")),
      { enableHighAccuracy: false, timeout: 15_000, maximumAge: 30 * 60_000 },
    )
  })
}

/** Ask the device, then hand the coordinates to the server (it rounds them before anything else). */
export async function shareDeviceLocation(): Promise<LocationState> {
  const { lat, lon } = await askDevicePosition()
  return saveDeviceLocation(lat, lon)
}

export const MONTH_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December']
