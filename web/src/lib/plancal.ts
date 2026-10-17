// Plan calendar (server: plancal.py): per-session status, distance, target pace and notes,
// weekly/monthly mileage, and the move / swap / fix / undo / goal operations, each of which
// re-balances the rest of the week deterministically and returns what changed.
import { getJSON, sendJSON } from '@/lib/api'
import type { BuiltPlan } from '@/lib/plan'

export type CalStatus = 'done' | 'missed' | 'planned' | 'skipped' | 'rest'
export type DistSport = 'run' | 'bike' | 'swim'
export type CalNote = { source: 'rabbit' | 'coach'; line: string; why: string; how: string; cues: string }
/** One step's exact targets (server: workouttargets.py). Ranges are [low, high]; pace and swim
 *  are [fast, slow] in s/km and s/100 m. */
export type TargetStep = {
  type: 'warmup' | 'steady' | 'work' | 'recover' | 'cooldown'; label: string; zone: number
  minutes: number | null; meters: number | null; rpe: string; talk: string
  hr?: [number, number]; pace?: [number, number]; power?: [number, number]; swim?: [number, number]; cadence?: [number, number]
}
export type TargetBlock = TargetStep | { type: 'repeat'; reps: number; steps: TargetBlock[] }
export type Targets = {
  /** where the heart-rate zones come from; null = no max/threshold HR known */
  hr_source: 'threshold' | 'reserve' | 'max' | 'estimated' | null
  ftp: boolean
  steps?: TargetBlock[]
  legs?: { sport: 'bike' | 'run'; steps: TargetBlock[] }[]
  summary: { minutes: number; zones: Record<string, number>; stress: number | null; run_pace: number | null; avg_hr: number | null }
}
export type Went = {
  verdict: 'hit' | 'short' | 'long' | 'hard' | 'fast' | 'slow' | 'done'
  headline: string; lines: string[]
  actual: { minutes: number | null; km: number | null; avg_hr: number | null; cadence: number | null; power: number | null; pace?: number | null }
}
export type CalSession = {
  status: CalStatus
  /** estimated km per sport (a brick has bike + run) */
  km: Partial<Record<DistSport, number>>
  /** main-set pace range for runs, seconds per km */
  pace: { zone: number; fast: number; slow: number } | null
  note: CalNote | null
  rebalanced: boolean; moved_from: string | null; made_up_for: string | null; hard: boolean
  activity?: { id: number | null; km: number | null; minutes: number | null }
  missed?: { why: string; best_day: string | null; this_week: boolean }
  /** exact per-step targets (structured sessions) */
  targets?: Targets
  /** done sessions: how the workout compared with the plan */
  went?: Went
  /** why Rabbit changed this session (made up for a miss, moved, eased, lengthened) */
  adjusted?: string
}
export type Mileage = { done: number; goal: number; planned: number; custom: boolean }
export type CalView = {
  today: string; imperial: boolean; threshold_pace: number; pace_source: 'profile' | 'recent' | 'default'
  /** 0 = Monday */
  available_days: number[]
  sessions: Record<string, CalSession>
  weeks: Record<string, Partial<Record<DistSport, Mileage>>>
  months: Record<string, Partial<Record<DistSport, { done: number; planned: number }>>>
  total: Partial<Record<DistSport, { done: number; planned: number }>>
  /** Garmin workouts not tied to a plan session, by day */
  extra?: Record<string, { id: number | null; name: string; sport: string; km: number | null; minutes: number | null; avg_hr: number | null }[]>
}
export type CalChange = { id: string | null; summary: string; rebalanced: string[]; rebalance_undo: string | null }
export type CalResult = { plan: BuiltPlan; cal: CalView; change: CalChange | null }

export const getCalendar = () => getJSON<{ cal: CalView | null }>('/api/plan/calendar')
const op = (k: string, body: Record<string, unknown>) =>
  sendJSON<CalResult>('POST', `/api/plan/calendar/${k}`, body).then((r) => { announce(r); return r })
export const moveSession = (session_id: string, date: string) => op('move', { session_id, date })
export const swapDays = (a: string, b: string) => op('swap', { a, b })
export const fixMissed = (session_id: string, how: 'move' | 'easy' | 'skip', date?: string) =>
  op('fix', { session_id, how, ...(date ? { date } : {}) })
export const undoChange = (id: string) => op('undo', { id })
/** km = null puts the plan's own goal back */
export const setWeekGoal = (week: string, sport: DistSport, km: number | null) => op('goal', { week, sport, km })

/** Fired on window after every calendar change (TrainingPeaks sync and other screens can listen). */
export const PLAN_CHANGED_EVENT = 'rabbit:plan-session-changed'
function announce(r: CalResult) {
  try { window.dispatchEvent(new CustomEvent(PLAN_CHANGED_EVENT, { detail: { change: r.change } })) } catch { /* old browsers */ }
}

// A Rabbit moment's "Fix my week" opens Plan with the fix sheet for that session.
let pendingFix: string | null = null
export const PLAN_FIX_EVENT = 'rabbit:plan-fix'
export function requestPlanFix(sessionId: string | undefined) {
  if (!sessionId) return
  pendingFix = sessionId
  try { window.dispatchEvent(new CustomEvent(PLAN_FIX_EVENT)) } catch { /* ignore */ }
}
export function takePlanFix(): string | null {
  const id = pendingFix
  pendingFix = null
  return id
}

/** One session as an .ics download (a timed event when it has a start time). */
export const sessionIcsUrl = (id: string) => `/app/api/plan/sessions/${encodeURIComponent(id)}/calendar.ics`

/** Google Calendar's own "add event" page, pre-filled (no sign-in to Rabbit's side needed). */
export function googleCalendarUrl(s: { title: string; time?: string | null; minutes: number | null; detail?: string }, date: string): string {
  const d = date.replace(/-/g, '')
  let dates: string
  if (s.time) {
    const [h, m] = s.time.split(':').map(Number) as [number, number]
    const start = new Date(`${date}T${s.time}:00`)
    const end = new Date(start.getTime() + (s.minutes || 60) * 60_000)
    const p = (n: number) => String(n).padStart(2, '0')
    const f = (x: Date) => `${x.getFullYear()}${p(x.getMonth() + 1)}${p(x.getDate())}T${p(x.getHours())}${p(x.getMinutes())}00`
    dates = `${d}T${p(h)}${p(m)}00/${f(end)}`
  } else {
    const next = new Date(`${date}T12:00:00`); next.setDate(next.getDate() + 1)
    dates = `${d}/${next.getFullYear()}${String(next.getMonth() + 1).padStart(2, '0')}${String(next.getDate()).padStart(2, '0')}`
  }
  const q = new URLSearchParams({ action: 'TEMPLATE', text: s.title, dates, details: s.detail ?? '' })
  return `https://calendar.google.com/calendar/render?${q}`
}

/** "6:30 AM" in the device's style from "06:30". */
export function fmtTime(t: string): string {
  const [h, m] = t.split(':').map(Number) as [number, number]
  return new Date(2000, 0, 1, h, m).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export const SPORT_DIST_LABEL: Record<DistSport, string> = { run: 'Run', bike: 'Bike', swim: 'Swim' }

// Open the Plan tab's calendar on one day (Day view). Anyone can call this; PlanCalendar reads
// the keys when it mounts and listens for the event while mounted; Chat.tsx switches to Plan.
export const OPEN_PLAN_DAY_EVENT = 'rabbit:open-plan-day'
export const PLAN_VIEW_KEY = 'rabbit.plancal.view'
export const PLAN_DAY_KEY = 'rabbit.plancal.day'
export function openPlanDay(date: string): void {
  try { sessionStorage.setItem(PLAN_VIEW_KEY, 'day'); sessionStorage.setItem(PLAN_DAY_KEY, date) } catch { /* storage off */ }
  try { window.dispatchEvent(new CustomEvent(OPEN_PLAN_DAY_EVENT, { detail: date })) } catch { /* old browsers */ }
}
