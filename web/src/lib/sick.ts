// Sick mode (server: sick.py, /app/api/plan/sick): rest or short easy days while ill, then an
// easy return. Opens from anywhere (Add sheet, Schedule tools, Home, a Rabbit check-in) through
// openSick(); components/plan/SickHost shows the sheet over whatever is on screen.
import { getJSON, postJSON } from './api'
import type { BuiltPlan } from './plan'

export type SickSeverity = 'head' | 'body'
export type SickView = {
  active: boolean
  safety?: string
  id?: string
  start?: string
  day?: number
  severity?: SickSeverity
  rest_all?: boolean
  /** 'better' (until I feel better) or the expected last sick day */
  until?: string
  /** the plan is reworked through this day */
  through?: string
  changed?: number
  race_note?: string | null
  line?: string
  returning: { day: number; days: number; until: string } | null
}
export type SickPreview = { sessions: number; rest_days: number; easy_days: number; through: string; race_note: string | null }
export type SickStart = { severity: SickSeverity; start?: string; until?: string | null; rest_all?: boolean }

export const getSick = () => getJSON<SickView>('/api/plan/sick')
export const previewSick = (b: SickStart) => postJSON<SickPreview>('/api/plan/sick/preview', b)

async function act(body: Record<string, unknown>): Promise<{ plan: BuiltPlan; sick: SickView | null }> {
  const r = await postJSON<{ plan: BuiltPlan; sick: SickView | null }>('/api/plan/sick', body)
  announceSick()
  return r
}
export const startSick = (b: SickStart) => act({ action: 'start', ...b })
export const extendSick = (days = 2) => act({ action: 'extend', days })
export const feelBetter = () => act({ action: 'better' })
export const undoSick = () => act({ action: 'undo' })

export const OPEN_SICK_EVENT = 'rabbit:open-sick'
export const SICK_CHANGED_EVENT = 'rabbit:sick-changed'

export function openSick() {
  try { window.dispatchEvent(new CustomEvent(OPEN_SICK_EVENT)) } catch { /* old browsers */ }
}
/** After a change: banners refresh and Schedule reloads the plan. */
export function announceSick() {
  try {
    window.dispatchEvent(new CustomEvent(SICK_CHANGED_EVENT))
    window.dispatchEvent(new CustomEvent('rabbit:plan-reload'))
  } catch { /* old browsers */ }
}
