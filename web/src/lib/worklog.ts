// Workouts logged by hand (server: worklog.py): lifting with sets and weights, or any workout
// without a watch. They count like synced ones: the planned session that day turns done, stats
// and streaks include them, and the Feed shows sport, time and distance only (never sets).
import { getJSON, sendJSON } from '@/lib/api'

export type WeightUnit = 'lb' | 'kg'
export type LogSet = { reps: string; weight: number | null; unit: WeightUnit }
export type LogExercise = { name: string; note?: string; sets: LogSet[] }
export type LogSport = 'strength' | 'run' | 'bike' | 'swim' | 'walk' | 'hike' | 'other'
export type LoggedWorkout = {
  id: string; key: string; source: 'manual'; sport: LogSport; title: string
  date: string; time: string | null; minutes: number | null; km: number | null; rpe: number | null
  notes: string; session_id: string | null; exercises: LogExercise[]; created: number; updated: number
}
export type LogBody = Partial<Omit<LoggedWorkout, 'id' | 'key' | 'source' | 'created' | 'updated'>> & { sport?: LogSport }
export type ExerciseHistory = { date: string; workout_id: string; sets: LogSet[]; line: string }

export const LOG_SPORTS: [LogSport, string][] = [
  ['strength', 'Lift'], ['run', 'Run'], ['bike', 'Ride'], ['swim', 'Swim'], ['walk', 'Walk'], ['hike', 'Hike'], ['other', 'Other'],
]

export const listLogged = (from?: string, to?: string) => {
  const q = new URLSearchParams()
  if (from) q.set('from', from)
  if (to) q.set('to', to)
  const s = q.toString()
  return getJSON<{ items: LoggedWorkout[]; unit: WeightUnit }>(`/api/workouts/manual${s ? `?${s}` : ''}`)
}
export const logWorkout = (body: LogBody) => sendJSON<{ item: LoggedWorkout }>('POST', '/api/workouts/manual', body)
export const updateLogged = (id: string, body: LogBody) =>
  sendJSON<{ item: LoggedWorkout }>('PATCH', `/api/workouts/manual/${encodeURIComponent(id)}`, body)
export const deleteLogged = (id: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/workouts/manual/${encodeURIComponent(id)}`)
export const exerciseHistory = (name: string) =>
  getJSON<{ name: string; items: ExerciseHistory[] }>(`/api/workouts/exercise-history?name=${encodeURIComponent(name)}`)

/** Something was logged, edited or removed: the plan, day and stats views re-read. */
export const WORKLOG_CHANGED = 'rabbit:worklog-changed'
export function worklogChanged(): void {
  window.dispatchEvent(new CustomEvent(WORKLOG_CHANGED))
}

/** Any screen can open the log sheet (screens/Chat.tsx hosts it). */
export type LogRequest = {
  /** prefill from a planned session */
  session?: { id: string; date: string; title: string; sport: string; minutes: number | null
    exercises?: { name: string; sets?: number | null; reps?: string | number | null }[] }
  /** edit an existing log */
  edit?: LoggedWorkout
  date?: string
}
export const OPEN_LOG_EVENT = 'rabbit:open-log'
export function openLogWorkout(req: LogRequest = {}): void {
  window.dispatchEvent(new CustomEvent<LogRequest>(OPEN_LOG_EVENT, { detail: req }))
}

/** '3 x 5 @ 185 lb' when every set matches, else each set. */
export function setLine(sets: LogSet[]): string {
  if (!sets.length) return ''
  const unit = sets[0]!.unit
  const same = sets.every((s) => s.reps === sets[0]!.reps && s.weight === sets[0]!.weight)
  if (same) return `${sets.length} x ${sets[0]!.reps}${sets[0]!.weight != null ? ` @ ${sets[0]!.weight} ${unit}` : ''}`
  return sets.map((s) => (s.weight != null ? `${s.reps} @ ${s.weight}` : s.reps)).join(', ') + (sets.some((s) => s.weight != null) ? ` ${unit}` : '')
}

/** Planned session sport -> a log sport (bricks and others log as their main sport). */
export function logSportOf(sport: string): LogSport {
  if (sport === 'strength' || sport === 'run' || sport === 'bike' || sport === 'swim' || sport === 'walk' || sport === 'hike') return sport
  if (sport === 'brick') return 'bike'
  return 'other'
}
