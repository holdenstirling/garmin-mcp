// Plan calendar (server: plancal.py): per-session status, distance, target pace and notes,
// weekly/monthly mileage, and the move / swap / fix / undo / goal operations, each of which
// re-balances the rest of the week deterministically and returns what changed.
import { getJSON, sendJSON } from '@/lib/api'
import type { BuiltPlan } from '@/lib/plan'

export type CalStatus = 'done' | 'missed' | 'planned' | 'skipped' | 'rest'
export type DistSport = 'run' | 'bike' | 'swim'
export type CalNote = { source: 'rabbit' | 'coach'; line: string; why: string; how: string; cues: string }
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
