// Body logs (server: body.py): the fueling & hydration log for long sessions, and the niggle
// tracker (aches and small injuries) with Rabbit's conservative easing suggestions.
// Screens open from anywhere with openBody(): components/body/BodyHost.tsx listens.
import { getJSON, sendJSON } from '@/lib/api'

export type Product = { label: string; g: number }
export type FuelItem = { product: string; count: number; g: number }
export type FuelEntry = {
  key: string; minutes: number; items: FuelItem[]; carbs_g: number; fluids_ml: number | null; sodium_mg: number | null
  every_min: number | null; gi: 'great' | 'ok' | 'issues' | null; energy: 'strong' | 'faded' | 'bonked' | null
  note: string; sport: string; title: string; date: string
  g_per_h: number | null; ml_per_h: number | null; mg_per_h: number | null
}
export type FuelLearnings = {
  sessions: number; learned_rate: number | null; target: number | null; lines: string[]
  trend: { date: string; title: string; sport: string; g_per_h: number; ml_per_h: number | null; gi: string | null; energy: string | null }[]
}

export const getFuel = (key: string) =>
  getJSON<{ entry: FuelEntry | null; products: Record<string, Product>; target: number }>(`/api/body/fuel?key=${encodeURIComponent(key)}`)
export const saveFuel = (key: string, body: Record<string, unknown>) =>
  sendJSON<{ entry: FuelEntry; learnings: FuelLearnings }>('POST', '/api/body/fuel', { key, ...body })
export const deleteFuel = (key: string) => sendJSON<{ entry: null }>('POST', '/api/body/fuel', { key, delete: true })
export const getFueling = () =>
  getJSON<{ learnings: FuelLearnings; target: number; entries: FuelEntry[]; products: Record<string, Product> }>('/api/body/fueling')

export type NiggleAssess = {
  ease: boolean; days: number; swap: boolean; red_flag: string[]; reasons: string[]; pain: number
  trend: 'better' | 'same' | 'worse' | null; age_days: number
}
export type Niggle = {
  id: string; area: string; side: string; pain: number; type: string; affects: string[]; note: string
  status: 'active' | 'resolved'; created: string; resolved: string | null
  updates: { date: string; trend: 'better' | 'same' | 'worse'; pain: number; note?: string }[]
  label: string; area_label: string; assess: NiggleAssess | null; needs_update: boolean
  prehab: { name: string; dose: string }[]; history: { date: string; pain: number; trend?: string }[]; care_note: string
}
export type EaseChange = {
  session_id: string; date: string; action: 'ease' | 'shorten' | 'swap_sport'
  from: { title: string; sport: string; kind: string; minutes: number }
  to: { sport: string; kind: string; minutes: number }; why: string
}
export type Niggles = {
  active: Niggle[]; resolved: Niggle[]; areas: Record<string, string>; care_note: string
  proposal: { id: string; changes: EaseChange[]; days: number; why: string } | null
}

export const getNiggles = () => getJSON<Niggles>('/api/body/niggles')
export const addNiggle = (body: Record<string, unknown>) => sendJSON<Niggles>('POST', '/api/body/niggles', body)
export const updateNiggle = (id: string, body: Record<string, unknown>) => sendJSON<Niggles>('POST', `/api/body/niggles/${id}`, body)
export const easeForNiggles = (id: string, action: 'apply' | 'dismiss') =>
  sendJSON<unknown>('POST', '/api/body/niggles/ease', { id, action })

export const NIGGLES_CHANGED = 'rabbit:niggles-changed'
export const PLAN_RELOAD = 'rabbit:paces-changed' // PlanEditor reloads plan + calendar on this event

export type BodyView = { view: 'niggles' } | { view: 'log-niggle'; affects?: string } | { view: 'fueling' }
export const OPEN_BODY_EVENT = 'rabbit:open-body'
export function openBody(v: BodyView) {
  try { window.dispatchEvent(new CustomEvent<BodyView>(OPEN_BODY_EVENT, { detail: v })) } catch { /* old browsers */ }
}

/** Carbs/fluids helpers in the athlete's units. */
export const ML_PER_FLOZ = 29.5735
export const toFluidUnit = (ml: number, imperial: boolean) => imperial ? Math.round(ml / ML_PER_FLOZ) : Math.round(ml)
export const fromFluidUnit = (v: number, imperial: boolean) => imperial ? Math.round(v * ML_PER_FLOZ) : Math.round(v)
