// Weekly and monthly challenges: personal targets from your recent Garmin training.
import { getJSON, postJSON, sendJSON } from '@/lib/api'
import { fmtClimb, fmtDist, fmtDuration } from '@/lib/format'

export type ChallengePeriod = 'week' | 'month'
export type Metric =
  | 'workouts' | 'active_days' | 'minutes' | 'distance_km' | 'climb_m' | 'long_session' | 'early_sessions'
  | 'sports_variety' | 'streak_days' | 'strength_sessions' | 'plan_adherence'

export type Suggestion = {
  template: string; period: ChallengePeriod; metric: Metric; sport: string | null; name: string
  target: number; baseline: number; kind: 'easy' | 'stretch' | 'fun'; why: string; xp: number
  period_start: string; period_end: string
}
export type LeaderRow = { user_id: string; name: string; pct: number | null; me: boolean }
export type Joined = {
  id: string; template: string; period: ChallengePeriod; period_start: string; period_end: string
  target: number; metric: Metric; sport: string | null; name: string; joined_at: string
  completed_at: string | null; group: string | null
  value: number; pct: number; done: boolean; days_left: number; xp: number
  leaderboard?: LeaderRow[] | null
}
export type Invite = {
  id: string; from: { id: string; name: string }; name: string; template: string; period: ChallengePeriod
  metric: Metric; sport: string | null; target: number; period_end: string; participants: number; xp: number
}
export type PeriodInfo = {
  start: string; end: string; days_left: number; joined: number; limit: number
  suggestions: Suggestion[]; notice: string | null
}
export type ChallengesView = {
  today: string; periods: Record<ChallengePeriod, PeriodInfo>; joined: Joined[]
  recent: { id: string; name: string; period: ChallengePeriod; metric: Metric; sport: string | null; target: number; completed_at: string }[]
  streak: Record<ChallengePeriod, number>; invites: Invite[]; can_invite: boolean; xp: Record<ChallengePeriod, number>
}

export const getChallenges = () => getJSON<ChallengesView>('/api/challenges')
export const joinChallenge = (template: string, period: ChallengePeriod) =>
  postJSON<ChallengesView & { challenge: Joined }>('/api/challenges/join', { template, period })
export const leaveChallenge = (id: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/challenges/${encodeURIComponent(id)}`)
export const inviteFriends = (id: string, userIds: string[]) =>
  postJSON<{ group: string; invited: string[] }>(`/api/challenges/${encodeURIComponent(id)}/invite`, { user_ids: userIds })
export const acceptInvite = (id: string) => postJSON<{ challenge: Joined }>(`/api/challenges/${encodeURIComponent(id)}/accept`)
export const declineInvite = (id: string) => postJSON<{ ok: boolean }>(`/api/challenges/${encodeURIComponent(id)}/decline`)

const plural = (n: number, one: string, many = `${one}s`) => `${Math.round(n)} ${Math.round(n) === 1 ? one : many}`

/** A value of ``metric`` in the athlete's units: "5 workouts", "3h 45m", "1,500 m". */
export function fmtMetric(metric: Metric, v: number, imperial: boolean, sport?: string | null): string {
  switch (metric) {
    case 'workouts': return plural(v, 'workout')
    case 'active_days': return plural(v, 'active day')
    case 'minutes': return fmtDuration(v) || '0 min'
    case 'distance_km': return fmtDist(v, imperial, sport, { decimals: v >= 20 ? 0 : 1 })
    case 'climb_m': return fmtClimb(v, imperial)
    case 'long_session': return fmtDuration(v) || '0 min'
    case 'early_sessions': return `${plural(v, 'session')} before 7 am`
    case 'sports_variety': return plural(v, 'sport')
    case 'streak_days': return `${plural(v, 'day')} in a row`
    case 'strength_sessions': return plural(v, 'strength session')
    case 'plan_adherence': return `${Math.round(v)}% of planned sessions`
  }
}

/** "1,500 m this week", "one 2h session this month". */
export function targetLine(c: { metric: Metric; target: number; period: ChallengePeriod; sport?: string | null }, imperial: boolean): string {
  const when = c.period === 'week' ? 'this week' : 'this month'
  if (c.metric === 'long_session') return `One ${fmtDuration(c.target)} session ${when}`
  const t = fmtMetric(c.metric, c.target, imperial, c.sport)
  return `${t.charAt(0).toUpperCase()}${t.slice(1)} ${when}`
}

/** "3 of 4 workouts", "Longest 1h 20m of 2h". */
export function progressLine(c: Joined, imperial: boolean): string {
  if (c.metric === 'long_session') return `Longest ${fmtDuration(c.value) || '0 min'} of ${fmtDuration(c.target)}`
  if (c.metric === 'plan_adherence') return `${Math.round(c.value)}% of ${Math.round(c.target)}%`
  const counts: Metric[] = ['workouts', 'active_days', 'early_sessions', 'sports_variety', 'streak_days', 'strength_sessions']
  if (counts.includes(c.metric)) return `${Math.floor(c.value)} of ${fmtMetric(c.metric, c.target, imperial, c.sport)}`
  return `${fmtMetric(c.metric, c.value, imperial, c.sport)} of ${fmtMetric(c.metric, c.target, imperial, c.sport)}`
}

export function daysLeft(n: number): string {
  return n <= 0 ? 'last day' : n === 1 ? '1 day left' : `${n} days left`
}
