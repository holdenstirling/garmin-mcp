// The weekly rhythm (server: GET/PUT /app/api/plan/rhythm): which sports go on which weekday,
// e.g. lift Mon, Wed, Fri and bike Tue, Thu, Sat. A missing day is "Any" (rabbt picks), a day
// can hold up to two sports, and "rest" stands alone. Strength sessions are opt-in
// (`strength_opt_in`): until it's true the plan never schedules lifting.
import { getJSON, sendJSON } from '@/lib/api'
import type { BuiltPlan } from '@/lib/plan'

export type Day = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
export type RhythmSport = 'run' | 'bike' | 'swim' | 'strength' | 'rest'
export type WeekRhythm = Partial<Record<Day, RhythmSport[]>>
export type RhythmState = {
  week_rhythm: WeekRhythm
  strength_opt_in: boolean | null
  /** the rhythm has lifting days but strength isn't opted in yet */
  needs_strength_opt_in: boolean
}
export type RhythmSaved = RhythmState & { plan?: BuiltPlan | null; warnings?: string[] }

export const DAYS: [Day, string, string][] = [
  ['mon', 'Mon', 'Monday'], ['tue', 'Tue', 'Tuesday'], ['wed', 'Wed', 'Wednesday'], ['thu', 'Thu', 'Thursday'],
  ['fri', 'Fri', 'Friday'], ['sat', 'Sat', 'Saturday'], ['sun', 'Sun', 'Sunday'],
]
export const SPORT_LABEL: Record<RhythmSport, string> = { run: 'Run', bike: 'Bike', swim: 'Swim', strength: 'Lift', rest: 'Rest' }
export const MAX_PER_DAY = 2

export const getRhythm = () => getJSON<RhythmState>('/api/plan/rhythm')
export const putRhythm = (patch: { week_rhythm?: WeekRhythm; strength_opt_in?: boolean }) =>
  sendJSON<RhythmSaved>('PUT', '/api/plan/rhythm', patch)

/** Tap a chip on one day: Any clears the day, Rest stands alone, at most two sports. */
export function toggle(r: WeekRhythm, day: Day, sport: RhythmSport | 'any'): WeekRhythm {
  const next: WeekRhythm = { ...r }
  const cur = r[day] ?? []
  if (sport === 'any') { delete next[day]; return next }
  if (sport === 'rest') {
    if (cur.length === 1 && cur[0] === 'rest') delete next[day]
    else next[day] = ['rest']
    return next
  }
  const without = cur.filter((s) => s !== 'rest')
  if (without.includes(sport)) {
    const left = without.filter((s) => s !== sport)
    if (left.length) next[day] = left
    else delete next[day]
    return next
  }
  // a third sport replaces the older of the two
  next[day] = [...without, sport].slice(-MAX_PER_DAY)
  return next
}

/** Drop days the server would ignore and keep the order stable (for saving and comparing). */
export function clean(r: WeekRhythm | null | undefined): WeekRhythm {
  const out: WeekRhythm = {}
  for (const [d] of DAYS) {
    const v = (r?.[d] ?? []).filter((s): s is RhythmSport => s in SPORT_LABEL)
    if (v.length) out[d] = v.includes('rest') ? ['rest'] : [...new Set(v)].slice(0, MAX_PER_DAY)
  }
  return out
}

export const hasStrength = (r: WeekRhythm) => Object.values(r).some((v) => v?.includes('strength'))
export const sameRhythm = (a: WeekRhythm, b: WeekRhythm) => JSON.stringify(clean(a)) === JSON.stringify(clean(b))

/** "Lift Mon, Wed, Fri · Bike Tue, Thu, Sat · Rest Sun", or null when every day is Any. */
export function summary(r: WeekRhythm): string | null {
  const order: RhythmSport[] = ['strength', 'run', 'bike', 'swim', 'rest']
  const parts = order.map((sp) => {
    const days = DAYS.filter(([d]) => r[d]?.includes(sp)).map(([, short]) => short)
    return days.length ? `${SPORT_LABEL[sp]} ${days.join(', ')}` : null
  }).filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

/** In plan setup: days with a sport become training days, Rest days stop being one. */
export function syncDays(available: string[] | undefined, r: WeekRhythm): string[] {
  const set = new Set(available ?? [])
  for (const [d] of DAYS) {
    const v = r[d]
    if (!v?.length) continue
    if (v.includes('rest')) set.delete(d)
    else set.add(d)
  }
  return DAYS.map(([d]) => d).filter((d) => set.has(d))
}
