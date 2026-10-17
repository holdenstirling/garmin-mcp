// Events: races, group activities, trips, challenges and life events on the calendar. The
// main one (a race or a challenge) is what the plan builds to.
import { getJSON, sendJSON } from '@/lib/api'

export type CourseProfile = 'flat' | 'rolling' | 'hilly' | 'mountainous'
export const COURSE_PROFILES: [CourseProfile, string][] = [
  ['flat', 'Flat'], ['rolling', 'Rolling'], ['hilly', 'Hilly'], ['mountainous', 'Mountainous'],
]

export type EventType = 'triathlon' | 'running' | 'trail' | 'cycling' | 'swimming' | 'duathlon' | 'mountaineering' | 'team_sport' | 'other'

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
/** How an event repeats (server: recur.py). Older events have just {weekday, until} (weekly). */
export type Recurring = {
  freq?: 'weekly' | 'monthly'; interval?: 1 | 2; weekdays?: Weekday[]; weekday?: Weekday
  /** monthly: 1st..4th, or -1 = last */
  setpos?: 1 | 2 | 3 | 4 | -1
  until?: string | null; count?: number | null
  /** skipped dates */
  except?: string[]
}
/** How the event shows up in the plan (server: events.plan_links). */
export type PlanLink = {
  status: 'main' | 'in_plan' | 'calendar_only' | 'pending' | 'outside' | 'no_plan' | 'past'
  line: string
  /** plan days with a session made from this event (upcoming first) */
  days: string[]
  action: 'build_plan' | 'update_plan' | null
}

export type RaceEvent = {
  id: string; name: string; type: EventType; distance: string; date: string
  kind?: EventKind; end_date?: string | null; time?: string | null; recurring?: Recurring | null
  neighborhood?: string; in_plan?: boolean | null; seq?: number; series_id?: string | null
  /** from the server: "Every Tuesday and Thursday", the iCalendar rule, the next dates */
  repeat_text?: string; rrule?: string; next_dates?: string[]
  google_url?: string | null; plan?: PlanLink | null
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
/** Every change drops the cached event days (eventsOn) so the calendars show it at once. */
const fresh = <T,>(p: Promise<T>) => p.then((r) => { clearEventDays(); return r })
export const createEvent = (e: EventFields & { main?: boolean }) =>
  fresh(sendJSON<ListResp & { event: RaceEvent }>('POST', '/api/events', e))
export const updateEvent = (id: string, e: EventFields) =>
  fresh(sendJSON<ListResp & { event: RaceEvent }>('PATCH', `/api/events/${id}`, e))
export const deleteEvent = (id: string) => fresh(sendJSON<ListResp>('DELETE', `/api/events/${id}`))
export const makeMainEvent = (id: string) => sendJSON<ListResp & { event: RaceEvent }>('POST', `/api/events/${id}/main`)
export const writeDebrief = (id: string, b: { result?: string; feel?: number; notes?: string }) =>
  sendJSON<ListResp & { debrief: Debrief }>('POST', `/api/events/${id}/debrief`, b)
/** One date of a repeating event: skip it ({skip: true}), bring it back ({skip: false}) or
 * change just that date (time, place, notes...; saved as a one-off linked to the series). */
export const editOccurrence = (id: string, day: string, body: Partial<EventFields> & { skip?: boolean }) =>
  fresh(sendJSON<ListResp & { event: RaceEvent; one_off: RaceEvent | null }>('POST', `/api/events/${id}/occurrences/${day}`, body))
/** Stop a repeating event after a date. */
export const endSeries = (id: string, after: string) => fresh(sendJSON<ListResp & { event: RaceEvent }>('POST', `/api/events/${id}/end`, { after }))
/** .ics download (Apple Calendar, Outlook): a repeating event comes with its repeat rule. */
export const eventIcsUrl = (id: string) => `/app/api/events/${encodeURIComponent(id)}/calendar.ics`

export type DayEvent = Pick<RaceEvent, 'id' | 'name' | 'kind' | 'type' | 'time' | 'duration_min' | 'location' | 'neighborhood' | 'priority' | 'main' | 'series_id'> & { repeats: boolean }
/** Events on each day in [from, to] (at most 120 days): one-offs, trips and every date of a
 * repeating event. For the Day / Week / Month views. */
export const eventDays = (from: string, to: string) =>
  getJSON<{ from: string; to: string; days: Record<string, DayEvent[]> }>(`/api/events/days?from=${from}&to=${to}`)

const dayCache = new Map<string, Promise<Record<string, DayEvent[]>>>()
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
/** Events on one date, fetched in 6-week windows and cached until clearEventDays(). */
export function eventsOn(date: string): Promise<DayEvent[]> {
  const d = new Date(`${date}T12:00:00`)
  const start = new Date(d); start.setDate(d.getDate() - ((d.getDay() + 6) % 7))
  const end = new Date(start); end.setDate(start.getDate() + 41)
  const key = iso(start)
  let p = dayCache.get(key)
  if (!p) {
    p = eventDays(key, iso(end)).then((r) => r.days, (e) => { dayCache.delete(key); throw e })
    dayCache.set(key, p)
  }
  return p.then((days) => days[date] ?? [])
}
export function clearEventDays() { dayCache.clear() }

/** The private calendar link (Google / Apple subscribe to it and stay in sync). */
export type CalFeed = { on: boolean; created?: number | null; url?: string; webcal?: string }
export const getCalFeed = () => getJSON<CalFeed>('/api/calendar/feed')
/** Makes a new link (an older one stops working). */
export const makeCalFeed = () => sendJSON<CalFeed>('POST', '/api/calendar/feed', {})
export const stopCalFeed = () => sendJSON<CalFeed>('DELETE', '/api/calendar/feed', {})

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
  group_activity: 'Group ride or run, a league game, Tuesday volleyball. Repeat it weekly or monthly.',
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
  ['swimming', 'Swim'], ['duathlon', 'Duathlon'], ['mountaineering', 'Climb / hike'],
  ['team_sport', 'Volleyball / team sport'], ['other', 'Other'],
]
export const TYPE_LABEL = Object.fromEntries(EVENT_TYPES) as Record<EventType, string>

/** Distances that fit each type (mirrors the server; used before the list loads). */
export const TYPE_DISTANCES: Record<EventType, string[]> = {
  triathlon: ['sprint triathlon', 'olympic triathlon', '70.3', '140.6'],
  running: ['5k', '10k', 'half marathon', 'marathon'],
  trail: ['10k', 'half marathon', 'marathon', 'ultra'],
  cycling: ['century ride', 'other'],
  swimming: ['other'], duathlon: ['other'], mountaineering: ['other'], team_sport: ['other'], other: ['other'],
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

/** Open one event's page from anywhere (a plan day's "From: …" line, search): screens/Chat
 * switches to the tab that shows events on OPEN_EVENT_EVENT; EventsScreen opens the event from
 * sessionStorage on mount, or from the event while it's already showing. */
export const OPEN_EVENT_EVENT = 'rabbit:open-event'
export const OPEN_EVENT_KEY = 'rabbit.events.open'
export function openEvent(id: string) {
  try { sessionStorage.setItem(OPEN_EVENT_KEY, id) } catch { /* the event still carries the id */ }
  try { window.dispatchEvent(new CustomEvent(OPEN_EVENT_EVENT, { detail: id })) } catch { /* old browsers */ }
}
export function takeOpenEvent(): string | null {
  try { const id = sessionStorage.getItem(OPEN_EVENT_KEY); sessionStorage.removeItem(OPEN_EVENT_KEY); return id } catch { return null }
}
/** Still ahead: a one-off on or after today, or a repeating event with dates left. */
export function isUpcoming(e: RaceEvent): boolean {
  if (e.recurring) return (e.next_dates?.length ?? 0) > 0 || daysUntil(e.date) >= 0
  return daysUntil(e.end_date || e.date) >= 0
}
/** The date the event card counts down to: the next date of a repeating event. */
export const nextDate = (e: RaceEvent) => (e.recurring && e.next_dates?.[0]) || e.date
