// Race finish-time estimates (predict.py): GET /api/events/{id}/predict, the generic
// /api/predict (Explore race detail) and the linked coach's view. Deterministic: recent
// Garmin efforts (hard ones preferred), FTP/CSS/threshold, course climbing/altitude/heat.
import { getJSON } from '@/lib/api'

export type Confidence = 'high' | 'medium' | 'low'
export type Leg = 'swim' | 't1' | 'bike' | 't2' | 'run'

export type Prediction = {
  kind: 'run' | 'trail' | 'bike' | 'swim' | 'tri'
  estimate: { low_s: number; mid_s: number; high_s: number; text: string }
  splits?: { leg: Leg; mid_s: number }[]
  confidence: Confidence
  basis: string[]
  assumptions: string[]
  label?: 'rough guide'
  text: string
  projection?: { mid_s: number; note: string; ctl_now: number; ctl_race: number; gain_pct: number }
  cutoff?: { s: number; margin_s: number; status: 'safe' | 'tight' | 'over' }
}
export type PredictResult = Prediction | { estimate: null; reason: string }

export const hasEstimate = (r: PredictResult | null | undefined): r is Prediction => !!r?.estimate

// Race cards and the race screen ask for the same event: share one request for a minute.
const cache = new Map<string, { at: number; p: Promise<PredictResult> }>()
function cached(key: string, load: () => Promise<PredictResult>): Promise<PredictResult> {
  const hit = cache.get(key)
  if (hit && Date.now() - hit.at < 60_000) return hit.p
  const p = load()
  p.catch(() => cache.delete(key))
  cache.set(key, { at: Date.now(), p })
  return p
}

export const predictEvent = (eventId: string) =>
  cached(`e:${eventId}`, () => getJSON<PredictResult>(`/api/events/${encodeURIComponent(eventId)}/predict`))

export const predictCoachEvent = (athleteId: string, eventId: string) =>
  cached(`c:${athleteId}:${eventId}`, () => getJSON<PredictResult>(
    `/api/coach/athletes/${encodeURIComponent(athleteId)}/events/${encodeURIComponent(eventId)}/predict`))

export function predictGeneric(q: { type?: string; distanceKm: number; climbM?: number; elevationM?: number; date?: string }) {
  const p = new URLSearchParams({ distance_km: String(q.distanceKm) })
  if (q.type) p.set('type', q.type)
  if (q.climbM != null) p.set('climb_m', String(Math.round(q.climbM)))
  if (q.elevationM != null) p.set('elevation_m', String(Math.round(q.elevationM)))
  if (q.date) p.set('date', q.date)
  return getJSON<PredictResult>(`/api/predict?${p.toString()}`)
}

/** Race clock: "1:52:30" at or above an hour, "47:30" under. */
export function fmtClock(s: number): string {
  const t = Math.round(s)
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}

/** A gap in words: "3 h 10 min", "40 min". */
export function fmtGap(s: number): string {
  const t = Math.round(Math.abs(s) / 60)
  const h = Math.floor(t / 60), m = t % 60
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`
}

export const LEG_LABEL: Record<Leg, string> = { swim: 'Swim', t1: 'T1', bike: 'Bike', t2: 'T2', run: 'Run' }
export const CONF_LABEL: Record<Confidence, string> = {
  high: 'Fairly tight', medium: 'A decent guess', low: 'A rough guide',
}
