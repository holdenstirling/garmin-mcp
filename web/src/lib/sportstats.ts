// Which numbers make sense for a workout, by sport family. A run is told by pace per mile, a
// ride by speed, a swim by pace per 100, a row by pace per 500 m, a ski day by vertical, and a
// yoga or strength session by time alone. Mirrors src/garmin_mcp/sportfamily.py (keep the two in
// step): the server already sends only the fitting rate on new cards; this also sorts older
// cards and plan sessions, and turns a card into labeled stats.
import { fmtClimb, fmtDist, fmtDuration, fmtPaceKm, fmtSwim100, KM_PER_MI } from './format'

export type SportFamily = 'run' | 'walk' | 'hike' | 'ride' | 'indoor_ride' | 'swim' | 'row' | 'paddle' | 'ski'
  | 'strength' | 'mind' | 'hiit' | 'climb' | 'brick' | 'other'

const RAW: [string, SportFamily][] = [
  ['multi_sport', 'brick'], ['multisport', 'brick'], ['triathlon', 'brick'], ['duathlon', 'brick'], ['brick', 'brick'],
  ['indoor_cycling', 'indoor_ride'], ['virtual_ride', 'indoor_ride'], ['trainer', 'indoor_ride'], ['spin', 'indoor_ride'],
  ['indoor_bik', 'indoor_ride'],
  ['swim', 'swim'], ['pool', 'swim'], ['open_water', 'swim'],
  ['indoor_row', 'row'], ['rowing', 'row'],
  ['paddl', 'paddle'], ['kayak', 'paddle'], ['canoe', 'paddle'], ['stand_up', 'paddle'],
  ['ski', 'ski'], ['snowboard', 'ski'], ['snowshoe', 'ski'],
  ['climb', 'climb'], ['boulder', 'climb'], ['mountaineer', 'climb'],
  ['yoga', 'mind'], ['pilates', 'mind'], ['breath', 'mind'], ['meditat', 'mind'], ['stretch', 'mind'], ['mobility', 'mind'],
  ['hiit', 'hiit'], ['cardio', 'hiit'], ['crossfit', 'hiit'], ['bootcamp', 'hiit'], ['boxing', 'hiit'],
  ['strength', 'strength'], ['weight', 'strength'], ['gym', 'strength'], ['lift', 'strength'],
  ['walk', 'walk'],
  ['hik', 'hike'], ['trek', 'hike'],
  ['cycl', 'ride'], ['bik', 'ride'], ['ride', 'ride'], ['gravel', 'ride'], ['mtb', 'ride'],
  ['run', 'run'], ['jog', 'run'], ['treadmill', 'run'], ['track', 'run'],
]
const SPORT: Record<string, SportFamily> = {
  run: 'run', walk: 'walk', hike: 'hike', bike: 'ride', ride: 'ride', swim: 'swim', brick: 'brick',
  strength: 'strength', ski: 'ski', climb: 'climb', paddle: 'paddle', row: 'row', yoga: 'mind', hiit: 'hiit',
}
const FAMILIES = new Set<string>(['run', 'walk', 'hike', 'ride', 'indoor_ride', 'swim', 'row', 'paddle', 'ski', 'strength',
  'mind', 'hiit', 'climb', 'brick', 'other'])

const norm = (s: string) => s.trim().toLowerCase().replace(/[\s-]+/g, '_')
const byRules = (k: string): SportFamily | null => {
  for (const [sub, fam] of RAW) if (k.includes(sub)) return fam
  return null
}

/** The family for a workout: ``kind`` (Garmin's type, e.g. "indoor_cycling") wins over the
 * coarse plan/stats ``sport`` when it says more. Also accepts a family or free text. */
export function sportFamily(sport: string | null | undefined, kind?: string | null): SportFamily {
  const k = kind ? norm(kind) : ''
  if (k) { const f = FAMILIES.has(k) ? (k as SportFamily) : byRules(k); if (f) return f }
  const s = norm(sport ?? '')
  if (!s) return 'other'
  if (FAMILIES.has(s)) return s as SportFamily
  if (s in SPORT) return SPORT[s]
  return byRules(s) ?? 'other'
}

/** Families whose cards show a lap shape: miles (or km) for the foot sports, 100s for swims. */
export const splitsOk = (fam: SportFamily) => fam === 'run' || fam === 'walk' || fam === 'hike' || fam === 'swim'
/** Families with no distance to speak of: time (and sets/reps) only. */
export const noDistance = (fam: SportFamily) => fam === 'strength' || fam === 'mind' || fam === 'hiit' || fam === 'climb' || fam === 'other'

export type Stat = { label: string; value: string }

/** What a workout card or summary may carry (server: community.WORKOUT_FIELDS). */
export type StatSource = {
  sport: string; family?: string | null; kind?: string | null
  km?: number | null; minutes?: number | null; climb_m?: number | null
  pace_s_km?: number; speed_kmh?: number; pace_s_100m?: number; pace_s_500m?: number
  vertical_m?: number; sets?: number; reps?: number
}

const clock = (s: number) => { const t = Math.round(s); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}` }

/** Distance as people talk about it for the family: yards or meters for a swim, meters for a row. */
export function famDist(km: number, fam: SportFamily, imperial: boolean): string {
  if (fam === 'row') return `${Math.round(km * 1000).toLocaleString()} m`
  return fmtDist(km, imperial, fam === 'swim' ? 'swim' : null)
}

/** Labeled stats in the order that matters for the family, only the ones that fit. */
export function statsFor(w: StatSource, imperial: boolean): Stat[] {
  const fam = sportFamily(w.family || w.sport, w.family ? null : w.kind)
  const out: Stat[] = []
  const add = (label: string, value: string | null | undefined | false) => { if (value) out.push({ label, value }) }
  const dist = !noDistance(fam) && w.km ? famDist(w.km, fam, imperial) : null
  const time = w.minutes ? fmtDuration(w.minutes) : null
  const climb = w.climb_m && w.climb_m >= 30 ? fmtClimb(w.climb_m, imperial) : null
  switch (fam) {
    case 'run': case 'walk': case 'hike':
      add('Distance', dist); add('Time', time)
      add('Pace', w.pace_s_km ? fmtPaceKm(w.pace_s_km, imperial) : null)
      add(fam === 'hike' ? 'Elevation gain' : 'Climb', fam === 'hike' && w.climb_m ? fmtClimb(w.climb_m, imperial) : climb)
      break
    case 'ride':
      add('Distance', dist); add('Time', time)
      add('Avg speed', w.speed_kmh ? speed(w.speed_kmh, imperial) : null); add('Climb', climb)
      break
    case 'indoor_ride':
      add('Time', time); add('Distance', dist); add('Avg speed', w.speed_kmh ? speed(w.speed_kmh, imperial) : null)
      break
    case 'swim':
      add('Distance', dist); add('Time', time)
      add(imperial ? 'Per 100 yd' : 'Per 100 m', w.pace_s_100m ? fmtSwim100(w.pace_s_100m, imperial).split(' ')[0] : null)
      break
    case 'row': case 'paddle':
      add('Distance', dist); add('Time', time); add('Per 500 m', w.pace_s_500m ? clock(w.pace_s_500m) : null)
      break
    case 'ski':
      add('Time', time); add('Distance', dist); add('Vertical', w.vertical_m ? fmtClimb(w.vertical_m, imperial) : null)
      break
    case 'strength': case 'hiit':
      add('Time', time); add('Sets', w.sets ? String(w.sets) : null); add('Reps', w.reps ? w.reps.toLocaleString() : null)
      break
    case 'brick':
      add('Time', time); add('Distance', w.km ? fmtDist(w.km, imperial) : null)
      break
    default:
      add('Time', time)
  }
  return out
}

/** One leg of a multisport card: "Swim 1,640 yd, 1:50 per 100 yd". */
export function legLine(lg: StatSource & { family?: string | null }, imperial: boolean): { label: string; value: string } {
  const fam = sportFamily(lg.family || lg.sport)
  const bits = [lg.km ? famDist(lg.km, fam, imperial) : '', lg.minutes ? fmtDuration(lg.minutes) : '']
  const rate = fam === 'swim' && lg.pace_s_100m ? `${fmtSwim100(lg.pace_s_100m, imperial).split(' ')[0]} per 100 ${imperial ? 'yd' : 'm'}`
    : (fam === 'ride' || fam === 'indoor_ride') && lg.speed_kmh ? speed(lg.speed_kmh, imperial)
    : (fam === 'run' || fam === 'walk' || fam === 'hike') && lg.pace_s_km ? fmtPaceKm(lg.pace_s_km, imperial)
    : fam === 'row' && lg.pace_s_500m ? `${clock(lg.pace_s_500m)} per 500 m` : ''
  return { label: FAMILY_NAME[fam], value: [...bits, rate].filter(Boolean).join(', ') }
}

function speed(kmh: number, imperial: boolean) {
  return imperial ? `${(kmh / KM_PER_MI).toFixed(1)} mph` : `${kmh.toFixed(1)} km/h`
}

/** A plain name for the family ("Indoor ride", "Yoga"). */
export const FAMILY_NAME: Record<SportFamily, string> = {
  run: 'Run', walk: 'Walk', hike: 'Hike', ride: 'Ride', indoor_ride: 'Indoor ride', swim: 'Swim', row: 'Row',
  paddle: 'Paddle', ski: 'Ski', strength: 'Strength', mind: 'Yoga', hiit: 'HIIT', climb: 'Climb', brick: 'Brick',
  other: 'Workout',
}
