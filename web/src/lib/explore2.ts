// Explore v2: where you are (device location -> rounded server-side; never precise),
// "Let Rabbit explore" (RunSignup + web research in one ranked list), local activities
// ("Near you" -> Local) and finish-time estimates (GET /api/predict).
import { getJSON, sendJSON } from '@/lib/api'
import type { ExploreRace } from '@/lib/explore'

export type LocSource = 'device' | 'home_zip' | 'profile_zip' | 'profile_city' | null
export type ResolvedLocation = {
  source: LocSource; label: string; zip: string; state: string; city: string; searchable: boolean
}
export type DeviceLocation = { zip: string; city: string; state: string; ts: number } | null
export type LocationState = { device: DeviceLocation; resolved: ResolvedLocation }

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

export type RabbitExploreResult = {
  intro: string; races: RaceX[]; total: number; web: 'ok' | 'limit' | 'unavailable' | 'failed'
  partial: boolean; inferred: boolean; location: ResolvedLocation
}

export type LocalCategory = 'run' | 'ride' | 'swim' | 'social_sports' | 'yoga' | 'climb' | 'other'
export type LocalActivity = {
  id: string; name: string; category: LocalCategory; organizer: string; when: string; where: string
  cost: string; url: string; why: string
}
export type LocalResult = {
  city: string; state: string; items: LocalActivity[]; needs_location: boolean
  suggested: LocalCategory[]; chips: Partial<Record<LocalCategory, string>>
}

export const getLocation = () => getJSON<LocationState>('/api/location')
export const saveDeviceLocation = (lat: number, lon: number) =>
  sendJSON<LocationState>('POST', '/api/location', { lat, lon })
export const forgetLocation = () => sendJSON<LocationState>('DELETE', '/api/location')
export const letRabbitExplore = () => sendJSON<RabbitExploreResult>('POST', '/api/explore/rabbit')
export const getLocal = () => sendJSON<LocalResult>('POST', '/api/explore/local')

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
