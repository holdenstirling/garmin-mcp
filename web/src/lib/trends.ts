// Progress trends (server: trends.py) and celebrations (server: celebrate.py).
import { getJSON, postJSON } from '@/lib/api'

export type TrendSport = 'run' | 'bike' | 'swim'
export type DistWeek = { start: string; km: number; goal: number | null }
export type DistSport = { sport: TrendSport; weeks: DistWeek[]; avg4_km: number; prev4_km: number; change_pct: number | null }
export type PacePoint = { start: string; sec: number; runs: number }
export type SleepPoint = { date: string; load: number; sleep_h: number | null }
export type Trends = {
  today: string
  units: 'imperial' | 'metric'
  distance: { sports: DistSport[]; current_week: string; imperial: boolean }
  /** sec = seconds per mile (imperial) or per km at ref_hr; change_s < 0 = faster */
  pace: { points: PacePoint[]; ref_hr: number | null; change_s: number | null; since?: string; imperial: boolean; reason: string | null }
  sleep: {
    points: SleepPoint[]; measure: 'load' | 'minutes'; source: 'garmin' | 'oura' | null; nights: number
    hard_h: number | null; other_h: number | null; reason: string | null
  }
}

export const getTrends = (fresh = false) => getJSON<Trends>(`/api/progress/trends${fresh ? '?fresh=1' : ''}`)

export type Celebration = {
  id: string
  kind: 'race' | 'block' | 'pr'
  date: string
  title: string
  subtitle: string
  line: string
  stats: { label: string; value: string }[]
  activity_id?: number | null
  block_id?: string
}
export const getCelebrations = () => getJSON<{ items: Celebration[] }>('/api/celebrations')
export const markCelebrated = (id: string) => postJSON<{ ok: boolean }>(`/api/celebrations/${id}/seen`)
