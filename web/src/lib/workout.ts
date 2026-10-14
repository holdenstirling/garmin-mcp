// Workout day: the "Ready to go" screen before a session and the reaction card after one
// (server: workoutday.py). Both are deterministic, no AI.
import { getJSON } from '@/lib/api'
import { fmtDist as fmtDistBase } from '@/lib/format'

export type Target = { kind: 'pace' | 'power' | 'hr' | 'rpe' | 'rest'; label: string }
export type WStep =
  | { type: 'warmup' | 'steady' | 'work' | 'recover' | 'cooldown'; label: string; amount: string; zone: number; zone_name: string; targets: Target[] }
  | { type: 'repeat'; reps: number; steps: WStep[] }
export type WSection = { kind: 'warmup' | 'main' | 'cooldown'; name: string; minutes: number; steps: WStep[] }
export type WGear = { id: string; kind: string; name: string; total_km: number; total_label: string; status: 'ok' | 'soon' | 'retire'; warning: string | null }
export type WFuel = { carbs_g_per_h: number; total_carbs_g?: number; fluid_ml_per_h?: string; sodium_mg_per_h?: string; note: string }
export type Weather = {
  place: string; temp_c: number | null; feels_c: number | null; wind_kmh: number | null; summary: string
  rain_pct: number | null; next: { time: string; temp_c: number | null; rain_pct: number | null; summary: string }[]
}
export type WorkoutSession = {
  id: string | null; date: string; title: string; sport: string; kind: string | null; minutes: number | null
  meters?: number | null; detail: string; purpose: string; cue: string; sections: WSection[]
  warmup_min: number; cooldown_min: number; main_targets: Target[]
  exercises: { name: string; dose: string }[]; prehab: { name: string; dose: string }[]
  fuel: WFuel | null; garmin: { on_watch: boolean; syncable: boolean }
  status: 'planned' | 'done' | 'missed'; activity?: { id: number | null; name: string; minutes: number } | null
  gear: WGear[]
}
export type WorkoutToday = {
  date: string; today: string; units: 'metric' | 'imperial'; has_plan: boolean
  readiness: { tone: string; line: string; signals: { label: string; value: string; good: boolean }[] } | null
  others: { id: string | null; title: string; sport: string; minutes: number | null; status: string }[]
  weather: Weather | null
} & (
  | { state: 'session'; session: WorkoutSession }
  | { state: 'rest' }
  | { state: 'free'; free: { title: string; sport: string; purpose: string; cue: string; main_targets: Target[] } }
)
export const getWorkoutToday = (sessionId?: string) =>
  getJSON<WorkoutToday>(`/api/workout/today${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`)

export type Verdict = 'nailed' | 'close' | 'different' | 'bonus'
export type Reaction = {
  activity: { id: number; name: string; sport: string; date: string; minutes: number; distance_km: number | null
    avg_hr?: number | null; avg_power_w?: number | null; pace: string | null; climb_m?: number | null }
  session_id: string | null
  planned: { title: string; minutes: number | null; kind: string | null; meters?: number | null; zone: number; zone_name: string; targets: Target[] } | null
  verdict: Verdict; line: string; duration_ratio: number | null
  effort: { zone: number; zone_name: string; in_zone: boolean | null; basis: string | null; direction: string | null; target: string | null; actual?: string } | null
  xp: { workout: number; plan: number; total: number }
  streak: { current: number; best: number }
  bests: { key: string; label: string; value: number; previous: number }[]
  gear: (WGear & { added_km: number; label: string }) | null
  tomorrow: { date: string; rest: boolean; title: string; sport: string; minutes: number | null; id: string | null; more?: number } | null
  units: 'metric' | 'imperial'
}
export const getReaction = (activityId: number) => getJSON<Reaction>(`/api/workout/reaction?activity_id=${activityId}`)

/** What the reaction card's "How did it feel?" hands to the voice check-in. */
export type CheckInRequest = { sessionId?: string; activityId?: number; title: string }

// Reaction cards show once per activity (remembered on this device).
const SHOWN = 'rabbit.reaction.shown'
export function reactionShown(id: number): boolean {
  try { return (JSON.parse(window.localStorage.getItem(SHOWN) ?? '[]') as number[]).includes(id) } catch { return false }
}
export function markReactionShown(id: number) {
  try {
    const ids = (JSON.parse(window.localStorage.getItem(SHOWN) ?? '[]') as number[]).filter((x) => x !== id)
    window.localStorage.setItem(SHOWN, JSON.stringify([...ids, id].slice(-50)))
  } catch { /* storage unavailable: may show again next session */ }
}

// Pre-run checklist, ticked per day on this device.
export const CHECKLIST: Record<string, string[]> = {
  run: ['Watch charged, workout loaded', 'Shoes laced, socks on', 'Water or a gel if it\'s long', 'Quick bathroom stop', '5 min of easy mobility'],
  bike: ['Tyres pumped, chain lubed', 'Helmet, glasses, gloves', 'Bottles filled, fuel packed', 'Head unit + lights charged', 'Repair kit: tube, CO2, tool'],
  swim: ['Goggles, cap, suit', 'Towel and flip-flops', 'Bottle for the pool deck', 'Watch set to pool length'],
  brick: ['Bike ready: tyres, bottles, fuel', 'Run shoes set out for the switch', 'Watch on multisport', 'Helmet, glasses'],
  strength: ['Space cleared, mat out', 'Water nearby', '5 min warm-up first'],
  other: ['Watch charged', 'Water', 'Something fun planned'],
}
const CK = 'rabbit.workout.checklist'
export function readChecklist(day: string): number[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(CK) ?? 'null') as { day: string; done: number[] } | null
    return v && v.day === day ? v.done : []
  } catch { return [] }
}
export function writeChecklist(day: string, done: number[]) {
  try { window.localStorage.setItem(CK, JSON.stringify({ day, done })) } catch { /* this session only */ }
}

export const fmtDist = (km: number, imperial: boolean, sport?: string | null) => fmtDistBase(km, imperial, sport)
export const fmtTemp = (c: number | null | undefined, imperial: boolean) =>
  c == null ? '' : imperial ? `${Math.round(c * 9 / 5 + 32)}°F` : `${Math.round(c)}°C`
