// Google Calendar (read-only) and travel mode.
import { getJSON, sendJSON } from '@/lib/api'
import type { BuiltPlan } from '@/lib/plan'

export type Travel = { start: string; end: string; title: string; location: string }
export type CalendarSummary = {
  available: boolean; connected: boolean; error?: string
  days?: number; start?: string; end?: string
  busy?: Record<string, number>; travel?: Travel[]
}
export type TripOptions = { gym: boolean; treadmill: boolean; pool: boolean; bike: boolean }

export const getCalendar = (days = 42) => getJSON<CalendarSummary>(`/api/calendar?days=${days}`)
export const disconnectCalendar = () => sendJSON<{ connected: false }>('DELETE', '/api/calendar')
export const CALENDAR_CONNECT_URL = '/app/auth/calendar/start'
export const addTravel = (b: { start: string; end: string; label: string } & TripOptions) =>
  sendJSON<{ plan: BuiltPlan }>('POST', '/api/plan/travel', b)
export const removeTravel = (id: string) => sendJSON<{ plan: BuiltPlan }>('DELETE', `/api/plan/travel/${id}`)
