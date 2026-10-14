// Plan builder API: the setup wizard's save, the built plan, session edits, Garmin sync.
import { getJSON, sendJSON, type Athlete, type Goal, type Sport } from '@/lib/api'

export type Step =
  | { type: 'warmup' | 'steady' | 'work' | 'recover' | 'cooldown'; minutes?: number; meters?: number; zone: number }
  | { type: 'repeat'; reps: number; steps: Step[] }

export type PlanSession = {
  id: string; sport: Sport; kind: string; title: string; minutes: number | null
  detail: string; meters?: number | null; edited?: boolean; synced: boolean; travel?: string | null
  exercises?: { name: string; dose: string }[]; prehab?: { name: string; dose: string }[]
  fuel?: { carbs_g_per_h: number; total_carbs_g?: number; fluid_ml_per_h?: string; sodium_mg_per_h?: string; note: string } | null
  steps: Step[]; legs: { sport: Sport; minutes: number; steps: Step[] }[]
}
export type PlanDay = { date: string; sessions: PlanSession[] }
export type PlanWeekBuilt = {
  index: number; start: string; phase: 'base' | 'build' | 'peak' | 'taper' | 'race'
  recovery: boolean; hours: number; focus: string; days: PlanDay[]
}
export type BuiltPlan = {
  start: string; first_day: string; race_date: string; distance: string; race_kind: 'tri' | 'run' | 'bike' | 'general'
  level: string; peak_hours: number; start_hours: number; note: string | null
  created: number; updated: number; weeks: PlanWeekBuilt[]; current_week: number | null
  /** the athlete's local date on the server (YYYY-MM-DD); the device clock may differ */
  today?: string
  garmin: { window?: number; synced_at?: number | null; last?: { uploaded: number; unchanged: number; removed: number }; errors?: number }
  pending_removals: number
  kinds: Record<string, string[]>
  events: { id: string; name: string; date: string; priority: 'B' | 'C' }[]
  events_changed: boolean
  race_changed: boolean
  trips: { id: string; start: string; end: string; label: string; has: Record<'gym' | 'treadmill' | 'pool' | 'bike', boolean> }[]
}
export type SyncResult = {
  uploaded: number; unchanged: number; removed: number; skipped: number
  errors: { title: string; date?: string; error: string }[]; window: [string, string]
}
export type GarminNumbers = Partial<Pick<Athlete, 'age' | 'units'>> & Partial<AthleteNumbers> & { sex?: 'male' | 'female' }

export type AthleteNumbers = {
  height_cm: number | null; weight_kg: number | null; resting_hr: number | null; max_hr: number | null
  threshold_hr: number | null; ftp_w: number | null; run_threshold_pace: number | null; swim_css: number | null
}
export type AthleteFull = Athlete & Partial<AthleteNumbers> & Partial<AthleteTraits> & {
  sex?: 'female' | 'male' | 'other' | null; level?: 'new' | 'intermediate' | 'advanced' | null
  available_days?: string[]; long_day?: string | null; equipment?: string[]; favorite_sports?: string[]
}
export type Trait = typeof TRAITS[number][0]
export type Terrain = typeof TERRAIN[number][0]
export type PastRace = { name: string; date: string; distance: string; result: string }
/** Athlete-entered traits for race fit, race strategy and Rabbit's context. */
export type AthleteTraits = {
  home_location: string; home_elevation_m: number | null; years_training: number | null
  strengths: Trait[]; limiters: Trait[]; heat_tolerance: 'low' | 'normal' | 'high' | null
  sweat: 'light' | 'average' | 'heavy' | 'salty' | null; altitude_acclimatized: boolean | null
  terrain_access: Terrain[]; race_history: PastRace[]; motivation: string; season_goal: string
}
export type GoalFull = Goal & {
  target_time?: string | null; goal_type?: 'finish' | 'time' | 'compete' | null
  priority?: 'A' | 'B' | 'C' | null; limiters?: string[]; course?: string; plan_source?: 'builder' | 'uploaded'
}

/** Plan reads and session edits, for the athlete ('/api') or a coach ('/api/coach/athletes/{id}'). */
export function planApi(base = '/api') {
  return {
    getPlan: () => getJSON<{ plan: BuiltPlan | null }>(`${base}/plan`),
    addSession: (s: { date: string; sport: Sport; kind?: string; minutes?: number; title?: string }) =>
      sendJSON<{ plan: BuiltPlan }>('POST', `${base}/plan/sessions`, s),
    updateSession: (id: string, patch: Partial<{ date: string; sport: Sport; kind: string; minutes: number; title: string; detail: string }>) =>
      sendJSON<{ plan: BuiltPlan }>('PATCH', `${base}/plan/sessions/${id}`, patch),
    deleteSession: (id: string) => sendJSON<{ plan: BuiltPlan }>('DELETE', `${base}/plan/sessions/${id}`),
  }
}
export type PlanApi = ReturnType<typeof planApi>
const own = planApi()
export const getPlan = own.getPlan
export const setupPlan = (body: { athlete: Partial<AthleteFull>; goal: Partial<GoalFull>; event?: Record<string, unknown>; start_date?: string; new_goal?: boolean }) =>
  sendJSON<{ plan: BuiltPlan; goal: GoalFull; athlete: AthleteFull }>('POST', '/api/plan/setup', body)
export const rebuildPlan = (start_date?: string) => sendJSON<{ plan: BuiltPlan }>('POST', '/api/plan/rebuild', start_date ? { start_date } : {})
export const deletePlan = () => sendJSON<{ ok: boolean; removed: number }>('DELETE', '/api/plan')
export const addSession = own.addSession
export const updateSession = own.updateSession
export const deleteSession = own.deleteSession
export const syncGarmin = (days: number) => sendJSON<{ plan: BuiltPlan; result: SyncResult }>('POST', '/api/plan/garmin/sync', { days })
export const removeFromGarmin = () => sendJSON<{ plan: BuiltPlan; result: { removed: number } }>('POST', '/api/plan/garmin/remove', {})
export const getGarminNumbers = () => getJSON<{ numbers: GarminNumbers }>('/api/garmin/numbers')

// ------------------------------------------------------------- labels ---
export const DISTANCES: { value: string; label: string; sports: Sport[] }[] = [
  { value: 'sprint triathlon', label: 'Sprint tri', sports: ['swim', 'bike', 'run'] },
  { value: 'olympic triathlon', label: 'Olympic tri', sports: ['swim', 'bike', 'run'] },
  { value: '70.3', label: '70.3', sports: ['swim', 'bike', 'run'] },
  { value: '140.6', label: 'Ironman', sports: ['swim', 'bike', 'run'] },
  { value: '5k', label: '5K', sports: ['run'] },
  { value: '10k', label: '10K', sports: ['run'] },
  { value: 'half marathon', label: 'Half marathon', sports: ['run'] },
  { value: 'marathon', label: 'Marathon', sports: ['run'] },
  { value: 'ultra', label: 'Ultra', sports: ['run'] },
  { value: 'century ride', label: 'Century ride', sports: ['bike'] },
  { value: 'other', label: 'Something else', sports: ['bike', 'run'] },
]
export const sportsFor = (distance: string | undefined): Sport[] =>
  DISTANCES.find((d) => d.value === distance)?.sports ?? ['swim', 'bike', 'run']

export const KIND_LABEL: Record<string, string> = {
  easy: 'Easy', long: 'Long', endurance: 'Endurance', recovery: 'Recovery', strides: 'Strides',
  tempo: 'Tempo', threshold: 'Threshold', vo2: 'VO2 max', racepace: 'Race pace', openers: 'Openers',
  shakeout: 'Shakeout', technique: 'Technique', css: 'CSS intervals', brick: 'Brick',
  strength: 'Strength', rest: 'Rest', race: 'Race',
}
export const PHASE_LABEL: Record<PlanWeekBuilt['phase'], string> = {
  base: 'Base', build: 'Build', peak: 'Peak', taper: 'Taper', race: 'Race week',
}
export const WEEKDAYS = [
  ['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun'],
] as const
export const FAVORITE_SPORTS = [
  ['run', 'Running'], ['trail', 'Trail running'], ['bike', 'Road cycling'], ['gravel', 'Gravel'], ['mtb', 'Mountain biking'],
  ['swim', 'Pool swimming'], ['open_water', 'Open water'], ['strength', 'Strength'], ['yoga', 'Yoga & mobility'],
  ['hike', 'Hiking'], ['climb', 'Climbing'], ['ski', 'Skiing'], ['row', 'Rowing'], ['walk', 'Walking'],
] as const
export const TRAITS = [
  ['climbing', 'Climbing'], ['descending', 'Descending'], ['flats', 'Flats'], ['speed', 'Speed'], ['endurance', 'Endurance'],
  ['heat', 'Heat'], ['cold', 'Cold'], ['technical_terrain', 'Technical terrain'], ['open_water', 'Open water'],
  ['night', 'Night'], ['pacing', 'Pacing'],
] as const
export const TERRAIN = [
  ['flat_roads', 'Flat roads'], ['rolling', 'Rolling'], ['hills', 'Hills'], ['mountains', 'Mountains'], ['trails', 'Trails'],
  ['track', 'Track'], ['pool', 'Pool'], ['open_water', 'Open water'], ['trainer', 'Trainer / treadmill'],
] as const
export const M_PER_FT = 0.3048
export const EQUIPMENT = [
  ['pool', 'Pool'], ['open_water', 'Open water'], ['power_meter', 'Power meter'], ['indoor_trainer', 'Indoor trainer'],
  ['hr_strap', 'HR strap'], ['treadmill', 'Treadmill'], ['gym', 'Gym'],
] as const

// ------------------------------------------------------------ helpers ---
/** "4:30" from seconds. */
export function fmtPace(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return ''
  const s = Math.round(sec)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
/** Seconds from "4:30" (or bare minutes). */
export function parsePace(v: string): number | null {
  const m = v.trim().match(/^(\d{1,2})(?::([0-5]?\d))?$/)
  if (!m) return null
  return Number(m[1]) * 60 + Number(m[2] ?? 0)
}
export const KM_PER_MI = 1.609344
export const cmToFtIn = (cm: number) => { const inches = Math.round(cm / 2.54); return { ft: Math.floor(inches / 12), inch: inches % 12 } }
export const ftInToCm = (ft: number, inch: number) => Math.round((ft * 12 + inch) * 2.54)
export const kgToLb = (kg: number) => Math.round(kg * 2.20462)
export const lbToKg = (lb: number) => Math.round((lb / 2.20462) * 10) / 10

export function weeksUntil(dateStr: string | null | undefined): number | null {
  if (!dateStr) return null
  const ms = new Date(`${dateStr}T12:00:00`).getTime() - Date.now()
  return Math.floor(ms / (7 * 86_400_000))
}

export function stepText(s: Step): string {
  if (s.type === 'repeat') return `${s.reps}× ${s.steps.map((x) => stepText(x)).join(' + ')}`
  const amt = s.meters ? `${s.meters}m` : fmtMin(s.minutes ?? 0)
  const what = s.type === 'warmup' ? 'warm-up' : s.type === 'cooldown' ? 'cool-down' : s.type === 'recover' ? 'easy' : `Z${s.zone}`
  return `${amt} ${what}`
}
export function fmtMin(m: number): string {
  if (m < 1) return `${Math.round(m * 60)}s`
  if (Math.abs(m - Math.round(m)) > 0.01) return `${Math.floor(m)}:${String(Math.round((m % 1) * 60)).padStart(2, '0')}`
  return m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}` : `${Math.round(m)}m`
}
export const ZONE_LABEL: Record<number, string> = { 1: 'Easy', 2: 'Aerobic', 3: 'Tempo', 4: 'Threshold', 5: 'Hard' }
