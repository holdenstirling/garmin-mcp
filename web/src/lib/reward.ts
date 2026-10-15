// Post-workout reward + monthly recap (server: reward.py). Deterministic, no AI.
import { getJSON, postJSON } from '@/lib/api'

export type LevelView = { level: number; name: string; xp: number; level_xp: number; level_span: number; to_next: number; next_name: string | null }
export type Reward = {
  activity_id: number
  name: string
  sport: string
  date: string
  headline: { kind: string; text: string; value: string | null; weeks?: number | null }
  chips: { label: string; value: string }[]
  xp: { gained: number; workout: number; plan: number }
  level: { before: LevelView; after: LevelView; level_up: boolean }
  streak: number
  verdict: 'nailed' | 'close' | 'different' | 'bonus' | null
  session_id: string | null
  units: 'metric' | 'imperial'
  seen?: boolean
}

/** The newest unseen reward (shown once on open), or one by activity (push tap). */
export const getReward = (activityId?: number) =>
  getJSON<{ reward: Reward | null }>(activityId != null ? `/api/reward?activity_id=${activityId}` : '/api/reward')
export const markRewardSeen = (activityId: number) => postJSON<{ ok: boolean }>(`/api/reward/${activityId}/seen`)

export type MonthRecap = {
  month: string
  label: string
  year: number
  partial: boolean
  units: 'metric' | 'imperial'
  hours: number
  sessions: number
  active_days: number
  longest: { sport: string; minutes: number } | null
  best_streak: number
  top_sport: { sport: string; hours: number } | null
  top_club: string | null
  weeks: { start: string; hours: number }[]
}
export const getMonthRecap = (month?: string) =>
  getJSON<MonthRecap>(month ? `/api/recap/month?month=${encodeURIComponent(month)}` : '/api/recap/month')

/** Last calendar month as YYYY-MM and its name (the Progress entry's label). */
export function lastMonth(now = new Date()): { month: string; label: string } {
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return { month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`, label: d.toLocaleDateString([], { month: 'long' }) }
}

export const SPORT_NAME: Record<string, string> = {
  run: 'Running', bike: 'Cycling', swim: 'Swimming', brick: 'Brick', strength: 'Strength', hike: 'Hiking',
  ski: 'Skiing', climb: 'Climbing', paddle: 'Paddling', yoga: 'Yoga', walk: 'Walking', other: 'Training',
}
export const sportName = (s: string | null | undefined) => SPORT_NAME[s ?? ''] ?? 'Training'
