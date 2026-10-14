// Events: every race or challenge on the calendar. The main one is what the plan builds to.
import { getJSON, sendJSON } from '@/lib/api'

export type EventType = 'triathlon' | 'running' | 'trail' | 'cycling' | 'swimming' | 'duathlon' | 'mountaineering' | 'other'

export type EventInfo = {
  summary?: string; date?: string; location?: string; start_time?: string; distances?: string
  elevation_gain?: string; terrain?: string; cutoffs?: string; typical_weather?: string; aid?: string
  registration?: string; website?: string; suggested_type?: EventType; suggested_distance?: string
  sources?: string[]; fetched_at?: number
}

export type RaceEvent = {
  id: string; name: string; type: EventType; distance: string; date: string
  location: string; url: string; priority: 'A' | 'B' | 'C'
  goal_type: 'finish' | 'time' | 'compete' | null; target_time: string | null
  course: string; notes: string; result: string; info: EventInfo | null
  created: number; updated: number; main: boolean
}
export type EventFields = Partial<Omit<RaceEvent, 'id' | 'created' | 'updated' | 'main'>>
type ListResp = { events: RaceEvent[]; types: Record<EventType, string[]> }

export const listEvents = () => getJSON<ListResp>('/api/events')
export const createEvent = (e: EventFields & { main?: boolean }) =>
  sendJSON<ListResp & { event: RaceEvent }>('POST', '/api/events', e)
export const updateEvent = (id: string, e: EventFields) =>
  sendJSON<ListResp & { event: RaceEvent }>('PATCH', `/api/events/${id}`, e)
export const deleteEvent = (id: string) => sendJSON<ListResp>('DELETE', `/api/events/${id}`)
export const makeMainEvent = (id: string) => sendJSON<ListResp & { event: RaceEvent }>('POST', `/api/events/${id}/main`)
export const lookupEvent = (q: { name: string; type?: string; date?: string; location?: string; event_id?: string }) =>
  sendJSON<{ info: EventInfo }>('POST', '/api/events/lookup', q)

export const EVENT_TYPES: [EventType, string][] = [
  ['triathlon', 'Triathlon'], ['running', 'Road run'], ['trail', 'Trail / ultra'], ['cycling', 'Cycling'],
  ['swimming', 'Swim'], ['duathlon', 'Duathlon'], ['mountaineering', 'Climb / hike'], ['other', 'Other'],
]
export const TYPE_LABEL = Object.fromEntries(EVENT_TYPES) as Record<EventType, string>

/** Distances that fit each type (mirrors the server; used before the list loads). */
export const TYPE_DISTANCES: Record<EventType, string[]> = {
  triathlon: ['sprint triathlon', 'olympic triathlon', '70.3', '140.6'],
  running: ['5k', '10k', 'half marathon', 'marathon'],
  trail: ['10k', 'half marathon', 'marathon', 'ultra'],
  cycling: ['century ride', 'other'],
  swimming: ['other'], duathlon: ['other'], mountaineering: ['other'], other: ['other'],
}
export const DISTANCE_LABEL: Record<string, string> = {
  'sprint triathlon': 'Sprint', 'olympic triathlon': 'Olympic', '70.3': '70.3', '140.6': 'Ironman',
  '5k': '5K', '10k': '10K', 'half marathon': 'Half marathon', marathon: 'Marathon', ultra: 'Ultra',
  'century ride': 'Century', other: 'Other',
}

export const INFO_LABEL: [keyof EventInfo, string][] = [
  ['date', 'Date'], ['location', 'Where'], ['start_time', 'Start'], ['distances', 'Distances'],
  ['elevation_gain', 'Climbing'], ['terrain', 'Course'], ['cutoffs', 'Cutoffs'],
  ['typical_weather', 'Weather'], ['aid', 'Aid & rules'], ['registration', 'Registration'],
]

export function daysUntil(d: string): number {
  const t = new Date(); t.setHours(12, 0, 0, 0)
  return Math.round((new Date(`${d}T12:00:00`).getTime() - t.getTime()) / 86_400_000)
}
export function countdown(d: string): string {
  const n = daysUntil(d)
  if (n === 0) return 'Today'
  if (n < 0) return n === -1 ? 'Yesterday' : `${-n} days ago`
  if (n < 14) return `${n} day${n === 1 ? '' : 's'}`
  if (n < 70) return `${Math.round(n / 7)} weeks`
  return `${Math.round(n / 30.4)} months`
}
