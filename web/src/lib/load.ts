// Fitness (CTL), fatigue (ATL) and form (TSB), with the plan's forecast to race day.
import { getJSON } from '@/lib/api'

export type LoadPoint = { date: string; load: number; ctl: number; atl: number; tsb: number; planned: boolean }
export type Load = {
  today: string; series: LoadPoint[]; now: LoadPoint | null; race_day: LoadPoint | null
  race_date: string | null; has_plan: boolean; advice: string
}
export const getLoad = (base = '/api') => getJSON<Load>(`${base}/load`)
