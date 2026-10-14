// Events: races, group activities, trips, challenges and life events on the calendar. The
// main one (a race or a challenge) is what the plan builds to.
import { getJSON, sendJSON } from '@/lib/api'

export type CourseProfile = 'flat' | 'rolling' | 'hilly' | 'mountainous'
export const COURSE_PROFILES: [CourseProfile, string][] = [
  ['flat', 'Flat'], ['rolling', 'Rolling'], ['hilly', 'Hilly'], ['mountainous', 'Mountainous'],
]

export type EventType = 'triathlon' | 'running' | 'trail' | 'cycling' | 'swimming' | 'duathlon' | 'mountaineering' | 'other'

export type EventInfo = {
  summary?: string; date?: string; location?: string; start_time?: string; distances?: string
  elevation_gain?: string; terrain?: string; cutoffs?: string; typical_weather?: string; aid?: string
  registration?: string; website?: string; suggested_type?: EventType; suggested_distance?: string
  suggested_course_profile?: CourseProfile; suggested_elevation_m?: number
  sources?: string[]; fetched_at?: number
}

/** What kind of event it is. Events saved before kinds existed come back as "race". */
export type EventKind = 'race' | 'group_activity' | 'trip' | 'challenge' | 'milestone' | 'other'
export type Weekday = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
export type Recurring = { weekday: Weekday; until: string }

export type RaceEvent = {
  id: string; name: string; type: EventType; distance: string; date: string
  kind?: EventKind; end_date?: string | null; time?: string | null; recurring?: Recurring | null
  with?: string; at?: string; duration_min?: number | null; intensity?: 'easy' | 'moderate' | 'hard' | null
  location: string; url: string; priority: 'A' | 'B' | 'C'
  goal_type: 'finish' | 'time' | 'compete' | null; target_time: string | null
  course: string; notes: string; result: string; info: EventInfo | null
  elevation_m?: number | null; course_profile?: CourseProfile | null
  debrief?: Debrief | null; strategy?: RaceStrategy | null
  created: number; updated: number; main: boolean
}
export type Debrief = { summary: string; went_well: string[]; work_on: string[]; learnings: string[]; feel: number | null; created: number }
export type RaceStrategy = {
  summary: string; key_risks: string[]; pacing: string[]; fueling: string[]; training_focus: string[]
  taper_notes: string; mental: string[]; phase: string; weeks_to_race: number; created: number
}
export type EventFields = Partial<Omit<RaceEvent, 'id' | 'created' | 'updated' | 'main' | 'debrief' | 'strategy'>>
type ListResp = { events: RaceEvent[]; types: Record<EventType, string[]>; kinds?: EventKind[] }

export const listEvents = () => getJSON<ListResp>('/api/events')
export const createEvent = (e: EventFields & { main?: boolean }) =>
  sendJSON<ListResp & { event: RaceEvent }>('POST', '/api/events', e)
export const updateEvent = (id: string, e: EventFields) =>
  sendJSON<ListResp & { event: RaceEvent }>('PATCH', `/api/events/${id}`, e)
export const deleteEvent = (id: string) => sendJSON<ListResp>('DELETE', `/api/events/${id}`)
export const makeMainEvent = (id: string) => sendJSON<ListResp & { event: RaceEvent }>('POST', `/api/events/${id}/main`)
export const writeDebrief = (id: string, b: { result?: string; feel?: number; notes?: string }) =>
  sendJSON<ListResp & { debrief: Debrief }>('POST', `/api/events/${id}/debrief`, b)
export const lookupEvent = (q: { name: string; type?: string; date?: string; location?: string; event_id?: string }) =>
  sendJSON<{ info: EventInfo }>('POST', '/api/events/lookup', q)

export const EVENT_KINDS: [EventKind, string][] = [
  ['race', 'Race'], ['group_activity', 'Group activity'], ['trip', 'Trip'], ['challenge', 'Challenge'],
  ['milestone', 'Life event'], ['other', 'Other'],
]
export const KIND_LABEL = Object.fromEntries(EVENT_KINDS) as Record<EventKind, string>
/** One line under each kind chip. */
export const KIND_HINT: Record<EventKind, string> = {
  race: 'A race with a start line. Rabbit tapers you for it.',
  group_activity: 'Group ride, run, swim or a league game. Rabbit counts it as a session.',
  trip: 'Training camp, adventure or hut trip. Rabbit lightens those days.',
  challenge: 'A 14er, an FKT attempt, a solo century. Prepped like a training race.',
  milestone: 'Wedding, a move, a new baby. Rabbit plans rest around it.',
  other: 'Anything else worth having on the calendar.',
}
export const kindOf = (e: { kind?: EventKind | null } | null | undefined): EventKind => e?.kind ?? 'race'
export const isRace = (e: { kind?: EventKind | null } | null | undefined) => kindOf(e) === 'race'
/** Kinds that can be the main event (the plan builds toward it). */
export const MAIN_KINDS: EventKind[] = ['race', 'challenge', 'other']
export const WEEKDAYS: [Weekday, string][] = [
  ['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun'],
]

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
