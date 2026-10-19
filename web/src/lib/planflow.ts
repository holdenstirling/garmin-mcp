// Your races (races.py), plan preview / levers / undo and the weekly check-in (planflow.py).
import { getJSON, sendJSON } from '@/lib/api'
import type { Change } from '@/lib/adjust'
import type { AthleteFull, BuiltPlan, GoalFull } from '@/lib/plan'

export type Race = {
  id: string; kind: 'goal' | 'event'; goal_id: string | null; event_id: string | null
  title: string; date: string | null; distance: string; active: boolean; past: boolean
  has_plan: boolean; priority: 'A' | 'B' | 'C' | null
}
export const getRaces = () => getJSON<{ active: string | null; races: Race[] }>('/api/races')
export const trainFor = (id: string) =>
  sendJSON<{ plan: BuiltPlan | null; goal: GoalFull; has_plan: boolean; races: { races: Race[] } }>('POST', '/api/races/train', { id })
export const makeTuneUp = (event_id: string) => sendJSON<{ races: Race[] }>('POST', '/api/races/tuneup', { event_id })

export type Phase = {
  phase: BuiltPlan['weeks'][number]['phase']; from: string; to: string; weeks: number; hours_from: number; hours_to: number; focus: string
  /** the workout kinds that define this phase, most frequent first */
  key_kinds?: string[]
  longest_minutes?: number
}
export type CalendarWeek = { start: string; phase: Phase['phase']; hours: number; recovery: boolean; days: DaySessions[] }
export type DaySessions = { date: string; sessions: { sport: string; kind: string | null; title: string; minutes: number }[] }
export type PlanSummary = {
  weeks: number; race_date: string | null; start: string; start_hours: number; peak_hours: number; level: string
  start_from?: string; note?: string | null; phases: Phase[]; hours: number[]; long_minutes: number[]
  first_two_weeks: DaySessions[]
  first_session: ({ date: string } & DaySessions['sessions'][number]) | null
  /** a training block, not a race */
  no_race?: boolean
  /** every week of the plan, for the calendar view */
  calendar?: CalendarWeek[]
}
export type PlanDiff = {
  weeks: { start: string; before: number | null; after: number | null }[]; changed_weeks: number
  days: { date: string; before: string; after: string }[]; changed_days: number
  peak_hours: { before: number | null; after: number | null }
}
export type Levers = Pick<AthleteFull, 'available_days' | 'long_day' | 'weekly_hours' | 'plan_intensity'>

export const previewPlan = (body: { athlete?: Partial<AthleteFull>; goal?: Partial<GoalFull>; start_date?: string; new_goal?: boolean }) =>
  sendJSON<{ summary: PlanSummary; diff?: PlanDiff }>('POST', '/api/plan/preview', body)
export const applyLevers = (levers: Levers, start_date?: string) =>
  sendJSON<{ plan: BuiltPlan; undo: string }>('POST', '/api/plan/levers', { levers, ...(start_date ? { start_date } : {}) })
export const undoLevers = (id: string) => sendJSON<{ plan: BuiltPlan }>('POST', '/api/plan/levers/undo', { id })

export type CheckinAnswers = {
  energy?: 'low' | 'ok' | 'great'; soreness?: 'none' | 'some' | 'a_lot'; time?: 'less' | 'same' | 'more'
  off_days?: string[]; long_day?: string
}
export type CheckinChange = Omit<Change, 'action'> & { action: Change['action'] | 'relocate' }
export type CheckinProposal = { status: 'none' | 'ok' | 'suggest'; id?: string; reasons?: string[]; changes?: CheckinChange[] }
export const getWeekCheck = () => getJSON<{ due: boolean; week_start?: string }>('/api/plan/weekcheck')
export const weekCheck = (action: 'preview' | 'apply' | 'skip', answers: CheckinAnswers, id?: string) =>
  sendJSON<{ proposal: CheckinProposal; calendar_hint?: string | null; applied?: number; plan?: BuiltPlan | null }>('POST', '/api/plan/weekcheck', { action, answers, ...(id ? { id } : {}) })

/** Fired after the plan changes here (race switch, levers, check-in): Schedule reloads. */
export const PLAN_RELOAD_EVENT = 'rabbit:plan-reload'
export function announcePlanReload() {
  try { window.dispatchEvent(new CustomEvent(PLAN_RELOAD_EVENT)) } catch { /* old browsers */ }
}

export const WEEKDAYS: [string, string][] = [['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun']]
export const INTENSITY: [NonNullable<Levers['plan_intensity']>, string, string][] = [
  ['gentle', 'Gentle', 'Fewer hard days, slower build'],
  ['normal', 'Normal', 'Balanced for your level'],
  ['push', 'Push', 'More hard days (still builds safely)'],
]
