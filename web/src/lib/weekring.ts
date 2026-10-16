// Rabbit home: this week's ring (server: weekring.py) and the live race grade (gradetrend.py).
import { getJSON } from '@/lib/api'
import type { ReadinessStatus } from '@/lib/readiness'

export type RingDayState = 'done' | 'partial' | 'missed' | 'planned' | 'rest' | 'extra' | 'empty'
export type WeekRingData = {
  kind: 'plan' | 'active'; unit: 'session' | 'workout'
  done: number; target: number; remaining: number; closed: boolean
  /** "4 of 5 · one more closes your week" | "Week closed!" */
  line: string; sub: string
  days: { date: string; weekday: string; today: boolean; state: RingDayState }[]
  days_left: number; week_start: string; rest_week: boolean
  next: { date: string; title: string; sport: string | null; id: string | null; minutes: number | null } | null
  phase: string | null
  /** this week's mileage (plancal.py), km; null without a plan with distances */
  miles?: { week_start: string; imperial: boolean; primary: 'run' | 'bike' | 'swim'
    sports: Partial<Record<'run' | 'bike' | 'swim', { done: number; goal: number; planned: number; custom: boolean }>> } | null
}
export const getWeekRing = () => getJSON<{ ring: WeekRingData | null }>('/api/weekring')

export type GradeReason = { sign: '+' | '-'; text: string }
export type LiveGrade = {
  event_id: string; name: string; date: string; grade: string; score: number
  status: ReadinessStatus; confidence: string
  /** "Boulder 70.3 · B+ · on track" */
  line: string; days_to_race: number
  /** vs the newest snapshot from an earlier week (null in the first week) */
  delta: number | null; direction: 'up' | 'down' | 'flat' | null; since: string | null
  prev_grade: string | null; reasons: GradeReason[]
  /** true when ``since`` is exactly last week */
  weekly: boolean
}
export const getLiveGrade = () => getJSON<{ race: LiveGrade | null }>('/api/racegrade/live')
