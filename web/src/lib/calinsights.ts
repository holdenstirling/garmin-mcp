// Calendar insights (server: calinsights.py): the next 14 days of training against the
// athlete's Google Calendar. Each recommendation has one action; nothing changes until tapped.
import { useCallback, useEffect, useState } from 'react'
import { getJSON, sendJSON } from '@/lib/api'
import type { BuiltPlan } from '@/lib/plan'

export type CalLoad = 'light' | 'normal' | 'heavy' | 'packed'
export type CalDay = { date: string; load: CalLoad; busy_min: number; free: [string, string][]; early: number; travel: boolean }
export type CalAction =
  | { type: 'time'; session_id: string; time: string }
  | { type: 'move'; session_id: string; date: string; time: string | null }
  | { type: 'ease'; session_id: string; minutes: number }
  | { type: 'travel'; start: string; end: string; name: string }
  | { type: 'long_day'; day: string }
export type CalRec = {
  id: string; kind: 'time' | 'move' | 'ease' | 'travel' | 'long_day'; date: string; session_id?: string
  title: string; body: string; label: string; action: CalAction
}
export type CalInsights = {
  connected: boolean; available: boolean; error?: string; today?: string
  days: CalDay[]; recs: CalRec[]
}

export const getCalInsights = () => getJSON<CalInsights>('/api/calendar/insights')
export const applyCalRec = (id: string) =>
  sendJSON<{ applied: string; undo: string | null; plan: BuiltPlan }>('POST', '/api/calendar/insights', { action: 'apply', id })
export const undoCalRec = (undo: string) =>
  sendJSON<{ undone: boolean; plan: BuiltPlan }>('POST', '/api/calendar/insights', { action: 'undo', undo })
export const dismissCalRec = (id: string) => sendJSON<{ ok: boolean }>('POST', '/api/calendar/insights', { action: 'dismiss', id })

export const LOAD_LABEL: Record<CalLoad, string> = { light: 'Light', normal: 'Normal', heavy: 'Busy', packed: 'Packed' }

/** Loads insights once (and on `key` changes); `reload` after a plan change. */
export function useCalInsights(key?: unknown) {
  const [data, setData] = useState<CalInsights | null>(null)
  const reload = useCallback(() => { getCalInsights().then(setData, () => setData(null)) }, [])
  useEffect(() => { reload() }, [reload, key])
  return { data, reload }
}

const PROMPT_KEY = 'rabbit.calprompt.hidden'
/** The "Connect Google Calendar" prompt stays hidden for 30 days after "Not now". */
export function calPromptHidden(): boolean {
  try { return Number(localStorage.getItem(PROMPT_KEY) || 0) > Date.now() } catch { return false }
}
export function hideCalPrompt() {
  try { localStorage.setItem(PROMPT_KEY, String(Date.now() + 30 * 86400_000)) } catch { /* ignore */ }
}
