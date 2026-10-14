// Near-instant workout sync, the Today card and the weekly recap.
import { getJSON, sendJSON } from '@/lib/api'

export type SyncedActivity = { id: number; name: string; sport: string; minutes: number; km: number }
export type SyncResult = {
  checked_at: string; new: SyncedActivity[]; changed: boolean; cached?: boolean; error?: string
}
export const syncNow = () => sendJSON<SyncResult>('POST', '/api/sync', {})

export type TodayTone = 'go' | 'easy' | 'rest' | 'race' | 'done' | 'plan'
export type TodayActionKind = 'open_session' | 'review_adjust' | 'open_racepack' | 'build_plan' | 'log_rest' | 'ask'
export type Today = {
  date: string; tone: TodayTone; headline: string; detail: string
  session: { id: string | null; title: string; minutes: number | null; sport: string } | null
  action: { kind: TodayActionKind; label: string }
  signals: { label: string; value: string; good: boolean }[]
  garmin: boolean
}
export const getToday = () => getJSON<Today>('/api/today')

export type RecapSession = { date: string; title: string; sport: string; kind: string | null; minutes: number | null }
export type Recap = {
  week_start: string; week_end: string; today: string; current: boolean
  xp: number; workouts: number; hours: number; km: number; active_days: number
  streak: number; streak_best: number
  adherence: { done: number; planned: number; pct: number | null; phase: string | null; focus: string | null } | null
  badges: { id: string; title: string; description: string }[]
  best: { name: string; sport: string; minutes: number; km: number; date: string } | null
  next_week: { start: string; phase: string | null; focus: string | null; recovery: boolean; sessions: RecapSession[]; target: string | null }
  level: { level: number; name: string; xp: number; level_xp: number; level_span: number; to_next: number; next_name: string | null }
  browse: { oldest: string; newest: string }
  summary: string
}
export const getRecap = (week?: string) => getJSON<Recap>(`/api/recap${week ? `?week=${encodeURIComponent(week)}` : ''}`)

/** Local YYYY-MM-DD (not UTC). */
export function localDay(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** Monday of the week containing ``day`` (YYYY-MM-DD), shifted by ``weeks``. */
export function shiftWeek(day: string, weeks: number): string {
  const d = new Date(`${day}T12:00:00`)
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + 7 * weeks)
  return localDay(d)
}
