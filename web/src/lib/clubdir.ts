// Community -> "Clubs & leagues near you": Rabbit's public-web directory per city
// (clubdir.py, routes in clubdir_web.py).
import { getJSON, postJSON } from '@/lib/api'
import type { LocalGroup } from '@/lib/community'
import type { SocialUser } from '@/lib/social'

export type DirChip = 'run' | 'trail' | 'tri' | 'ride' | 'swim' | 'leagues'
export type DirKind = 'run_club' | 'trail' | 'tri' | 'ride' | 'swim' | 'league' | 'other'
export type Weekday = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
export type DirStatus = 'ready' | 'refreshing' | 'queued' | 'needs_location' | 'unavailable' | 'limit' | 'busy'

export const DIR_CHIPS: [DirChip, string][] = [
  ['run', 'Run'], ['trail', 'Trail'], ['tri', 'Tri'], ['ride', 'Ride'], ['swim', 'Swim'], ['leagues', 'Leagues'],
]
export const WEEKDAY_LABEL: Record<Weekday, string> = {
  mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun',
}

export type DirSession = { weekday: Weekday; time: string; note: string }
/** "I'm going" for the listing's next occurrence (clubgoing.py). Friends = people you follow. */
export type DirGoing = { date: string; count: number; me: boolean; friends: SocialUser[]; more_friends: number }
export type DirListing = {
  id: string; name: string; kind: DirKind; kind_label: string; sports: string[]; sessions: DirSession[]
  next: { weekday: Weekday; time: string; in_days: number; date?: string } | null
  meet_spot: string; pace: string; cost: 'free' | 'paid' | 'unknown'
  join_url: string; source_url: string; source: string; description: string
  /** "Meetup", "Facebook"... when we only link to it (never read). */
  link_only: string | null
  last_verified: string; linked_club: string | null; reported: boolean
  /** Geocoded public meet spot (3 decimals), null when unknown. */
  lat?: number | null; lon?: number | null
  /** Has a weekly session with a time (an .ics is available). */
  calendar?: boolean
  going?: DirGoing | null
}
export type DirView = {
  metro: { city: string; state: string; label: string } | null
  status: DirStatus
  listings: DirListing[]
  counts: Partial<Record<DirChip, number>>
  refreshed: string | null
  fallback: LocalGroup[]
  /** Metro centre for the map. */
  center?: { lat: number; lon: number } | null
}

const P = '/api/community/directory'
export function getDirectory(kind?: DirChip | null): Promise<DirView> {
  return getJSON<DirView>(`${P}${kind ? `?kind=${kind}` : ''}`)
}
export const suggestClub = (b: { name: string; url: string; city?: string; state?: string }) =>
  postJSON<{ ok: boolean; message: string }>(`${P}/suggest`, b)
export const reportListing = (id: string) =>
  postJSON<{ ok: boolean; hidden: boolean; message: string }>(`${P}/${encodeURIComponent(id)}/report`, {})
export const markGoing = (id: string, going: boolean, date?: string) =>
  postJSON<{ going: DirGoing }>(`${P}/${encodeURIComponent(id)}/going`, { going, date })
/** Weekly .ics download (same-origin link with the session cookie). */
export const calendarUrl = (id: string) => `/app${P}/${encodeURIComponent(id)}/calendar.ics`

/** OpenStreetMap embed (iframe; CSP frame-src allows www.openstreetmap.org) for one meet spot. */
export function osmEmbedUrl(lat: number, lon: number): string {
  const d = 0.006
  const bbox = [lon - d, lat - d * 0.75, lon + d, lat + d * 0.75].map((v) => v.toFixed(4)).join(',')
  return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat.toFixed(4)},${lon.toFixed(4)}`
}
export function osmLink(lat: number, lon: number): string {
  return `https://www.openstreetmap.org/?mlat=${lat.toFixed(4)}&mlon=${lon.toFixed(4)}#map=16/${lat.toFixed(4)}/${lon.toFixed(4)}`
}

export const linkListing = (id: string, clubId: string) =>
  postJSON<{ ok: boolean }>(`${P}/${encodeURIComponent(id)}/link`, { club_id: clubId })

/** "Tonight 6:00 PM", "Tomorrow 7:00 AM", "Sat 8:00 AM", "Tuesdays". */
export function nextLabel(n: DirListing['next']): string {
  if (!n) return ''
  const time = n.time ? new Date(`2000-01-01T${n.time}:00`).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : ''
  if (!time) return `${WEEKDAY_LABEL[n.weekday]}s`
  if (n.in_days === 0) return `Today ${time}`
  if (n.in_days === 1) return `Tomorrow ${time}`
  return `${WEEKDAY_LABEL[n.weekday]} ${time}`
}

/** Club sport for "Start a Rabbit group" (clubs.py SPORTS). */
export function clubSport(k: DirKind): 'running' | 'trail' | 'cycling' | 'triathlon' | 'swimming' | 'other' {
  return ({ run_club: 'running', trail: 'trail', ride: 'cycling', tri: 'triathlon', swim: 'swimming' } as const)[
    k as 'run_club' | 'trail' | 'ride' | 'tri' | 'swim'] ?? 'other'
}
