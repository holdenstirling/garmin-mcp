// One recorded workout (server: activitypage.py, GET /app/api/activity/{id}).
import { getJSON } from '@/lib/api'
import type { Checkin } from '@/lib/checkins'
import type { WorkoutFeedback } from '@/lib/workout'
import type { Went } from '@/lib/plancal'

export type ActivityNumbers = Partial<{
  km: number; moving_s: number; elapsed_s: number; pace_s_per_km: number; pace_s_per_100m: number; speed_kmh: number
  avg_hr: number; max_hr: number; cadence: number; cadence_unit: 'spm' | 'rpm'; elevation_gain_m: number
  avg_power_w: number; norm_power_w: number; calories: number; aerobic_te: number; anaerobic_te: number
  training_load: number; te_label: string; swolf: number; stroke_rate: number
}>
export type ActivityLap = { n: number; km: number; s: number; pace_s_per_km: number; hr?: number; gain_m?: number }
export type ActivityZones = { basis: 'laps' | 'average'; zones: { zone: number; label: string; low: number; high: number; s: number }[] }
export type ActivityView = {
  id: number | string; key: string; source: string; ai: boolean
  sport: string; name: string; start: string | null
  numbers: ActivityNumbers; laps: ActivityLap[]; zones: ActivityZones | null
  planned: { id: string; date: string; title: string; kind: string; went: Went | null } | null
  checkin: Checkin | null; feedback: WorkoutFeedback | null; garmin_url: string | null
}

export const getActivity = (id: string) => getJSON<ActivityView>(`/api/activity/${encodeURIComponent(id)}`)

/** A check-in's activity_id for this workout (server: activitypage.checkin_ref). */
export const checkinRef = (key: string) => key.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 64)
