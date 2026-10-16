// Race-week mode (server: raceweek.py / raceweek_web.py): the home card in the 7 days before
// an A/B/main race, the race-week page, packing/reminders, and friends' race status.
import { getJSON, postJSON, sendJSON } from '@/lib/api'
import type { SocialUser } from '@/lib/social'

export type RaceWeekEvent = {
  id: string; name: string; type: string; distance: string; date: string; location: string
  priority: string; main: boolean; url?: string; target_time?: string | null
}
export type Taper = { day: number; of: number; text: string }
export type TodaySession = { id: string | null; title: string; minutes: number | null; sport: string }

export type RaceWeekCard = {
  event: RaceWeekEvent; days: number; race_day: boolean; taper: Taper; today: TodaySession[]
  readiness: { grade: string; status: string; headline: string } | null
  packing: { done: number; total: number }; tracking: boolean
}

export type SplitRow = { at: number; label: string; split_s: number; cum_s: number; cum: string; pace?: string; speed?: string }
export type TriLeg = { leg: 'swim' | 't1' | 'bike' | 't2' | 'run'; label: string; s: number; time: string; cum: string; pace?: string }
export type Pacing = {
  target_s: number | null; target: string | null; source: 'you' | 'goal' | 'estimate' | null
  estimate: { low_s: number; mid_s: number; high_s: number; text: string; confidence: string } | null
  goal_s: number | null; mode: 'tri' | 'pace' | 'speed' | null; legs: TriLeg[]
  splits: { unit: string; step: number; rows: SplitRow[]; pace_s: number | null; pace?: string; band?: string; speed?: string } | null
  notes: string[]; effort: { leg: string; target: string; detail: string }[]
}
export type PackItem = { id: string; text: string; group: string; done: boolean; custom: boolean }
export type Packing = { items: PackItem[]; done: number; total: number }
export type Reminder = { id: string; text: string; when: string | null; done: boolean }
export type RaceState = 'not_started' | 'racing' | 'finished' | 'race_day' | 'no_result'
export type RaceStatus = {
  state: RaceState; start: string | null; elapsed_s: number | null; date: string
  result: { activity_id: number | null; name: string; duration_s: number; time: string; distance_km: number | null } | null
}
export type Weather = { place: string; high_c: number | null; low_c: number | null; rain_pct: number | null; wind_kmh: number | null }

export type RaceWeekPage = {
  event: RaceWeekEvent; days: number; race_day: boolean; imperial: boolean; taper: Taper; today: TodaySession[]
  pacing: Pacing
  course: { text: string; profile: string | null; climb_m: number | null; elevation_m: number | null; terrain: string | null
    typical_weather: string | null; weather: Weather | null; weather_tips: string[] }
  packing: Packing
  nutrition: { hours: number; carbs_g_per_h: [number, number]; fluid_ml_per_h: [number, number]; sodium_mg_per_h: [number, number]
    total_carbs_g: [number, number]; steps: string[]; label: string }
  logistics: { start_time: string | null; start_custom: boolean; location: string; maps_url: string | null; url: string | null
    registration: string | null; reminders: Reminder[] }
  tracking: { on: boolean; notify_friends: boolean; status: RaceStatus | null; audience: number; note: string }
}
export type FriendRacing = RaceStatus & {
  user: SocialUser | null; event: { id: string; name: string; distance: string; type: string }; note: string
}

const base = (id: string) => `/api/raceweek/${encodeURIComponent(id)}`
export const getRaceWeekCard = () => getJSON<{ raceweek: RaceWeekCard | null }>('/api/raceweek')
export const getRaceWeek = (id: string) => getJSON<RaceWeekPage>(base(id))
export type RaceWeekPatch = { target_s?: number | null; start_time?: string | null; tracking?: boolean; notify_friends?: boolean }
export const putRaceWeek = (id: string, patch: RaceWeekPatch) => sendJSON<{ saved: RaceWeekPatch }>('PUT', base(id), patch)
export const packingAction = (id: string, body: { toggle: string } | { add: string } | { remove: string }) =>
  postJSON<Packing>(`${base(id)}/packing`, body)
export const reminderAction = (id: string, body: { add: { text: string; when?: string } } | { toggle: string } | { remove: string }) =>
  postJSON<{ reminders: Reminder[] }>(`${base(id)}/reminders`, body)
export const getFriendsRacing = () => getJSON<{ friends: FriendRacing[] }>('/api/raceweek/friends')

/** "1:23:45" / "23:45" from seconds. */
export function hms(s: number): string {
  const t = Math.max(0, Math.round(s))
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}

/** "Not started · 7:00 start" / "Racing · 1:12 since the start" / "Finished · 3:41:07". */
export function statusLine(s: RaceStatus, elapsedNow?: number | null): string {
  if (s.state === 'finished' && s.result) return `Finished · ${s.result.time}`
  if (s.state === 'racing') return `Racing · ${hms(elapsedNow ?? s.elapsed_s ?? 0)} since the planned start`
  if (s.state === 'not_started') return s.start ? `Not started · ${s.start} start` : 'Not started'
  if (s.state === 'no_result') return 'Waiting for the watch to sync'
  return 'Race day'
}

/** Prefilled "Ask Rabbit about race day" text with the plan's numbers (nothing is sent until they tap send). */
export function askText(p: RaceWeekPage): string {
  const bits = [`${p.event.name}${p.event.distance ? ` (${p.event.distance})` : ''} on ${p.event.date}`]
  if (p.pacing.target) bits.push(`target ${p.pacing.target}`)
  if (p.logistics.start_time) bits.push(`start ${p.logistics.start_time}`)
  return `About race day for ${bits.join(', ')}: `
}
