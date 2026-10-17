// Community -> "Clubs & leagues near you": Rabbit's public-web directory per city
// (clubdir.py, routes in clubdir_web.py).
import { getJSON, postJSON, sendJSON } from '@/lib/api'
import type { LocalGroup } from '@/lib/community'
import type { SocialUser } from '@/lib/social'
import { counted } from '@/lib/usage'
import type { ActivityId, GroupType } from '@/lib/activity'

const P = '/api/community/directory'

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
  /** "search" when someone looked this club up by name (directory = found by Rabbit's own update). */
  found_by?: 'directory' | 'search'
  /** What it's for (icon + filter) and what it is: Club | League | Meetup (activity.py) */
  activity?: ActivityId; type?: GroupType; type_label?: string
  /** From the middle of my area; null = no mapped spot ("in your city") */
  distance_km?: number | null
}
/** My area (area.py): my spot or the city centre, and my radius. */
export type DirArea = { label: string; radius_mi: number; radii_mi: number[]; has_point: boolean; source: 'device' | 'manual' | 'city' | null }
export type TimeOfDay = 'morning' | 'midday' | 'evening'
export const TIME_OF_DAY: [TimeOfDay, string][] = [['morning', 'Mornings'], ['midday', 'Midday'], ['evening', 'Evenings']]
export type DirFilters = { activity?: ActivityId | null; weekday?: Weekday | null; when?: TimeOfDay | null }
function filterQuery(f: DirFilters, extra: Record<string, string> = {}): string {
  const p = new URLSearchParams(extra)
  if (f.activity) p.set('activity', f.activity)
  if (f.weekday) p.set('weekday', f.weekday)
  if (f.when) p.set('when', f.when)
  const q = p.toString()
  return q ? `?${q}` : ''
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
  /** The owner's partners for this city (partners.py), always shown labelled "Partner". */
  partners?: Partner[]
  area?: DirArea | null
  /** listings per activity inside my area (filter chips) */
  activities?: Partial<Record<ActivityId, number>>
  /** left out for being farther than my radius */
  farther?: number
}

// ------------------------------------------------------------------ partners --
export type PartnerKind = 'run_club' | 'tri_club' | 'ride' | 'swim' | 'trail' | 'store' | 'coach' | 'other'
export type Partner = {
  id: string; label: 'Partner' | 'Sponsored partner'; name: string; kind: PartnerKind; kind_label: string; tagline: string
  description: string; schedule: string; website: string; instagram: string; signup: string; monogram: string
  /** paid placement: shown as "Sponsored partner" in the find-clubs flows */
  sponsored?: boolean
  /** "Why am I seeing this?" (sponsored cards only) */
  why?: string
}
/** Where a sponsored card shows (one per screen; Hide keeps it off that screen for 30 days). */
export type SponsorPlacement = 'local' | 'home' | 'discover' | 'explore' | 'directory_empty' | 'search'
export type PartnerCount = 'view' | 'website' | 'instagram' | 'signup' | 'interested'
export type PartnerAdmin = Partner & {
  metros: { city: string; state: string }[]; starts: string | null; ends: string | null; active: boolean; live: boolean
  stats: Record<PartnerCount, number>
  /** sponsored-card counts by placement (last 30 days) */
  placements?: Partial<Record<SponsorPlacement, { impression: number; tap: number; hide: number }>>
}
export type PartnerAdminList = { partners: PartnerAdmin[]; kinds: { id: PartnerKind; label: string }[]; stats_days: number }
export type PartnerDraft = {
  name: string; kind: PartnerKind; tagline: string; description: string; schedule: string
  website: string; instagram: string; signup: string; metros: string[]; starts: string | null; ends: string | null; active: boolean
  sponsored: boolean
}
const A = '/api/partners'
export const getPartner = (id: string) => getJSON<Partner>(`${A}/${encodeURIComponent(id)}`)
/** Anonymous count (once per person, partner, kind and day; skipped when usage counting is off). */
export const countPartner = (id: string, what: PartnerCount) =>
  postJSON<{ counted: boolean }>(`${A}/${encodeURIComponent(id)}/count`, { what })
/** One sponsored partner card for a find-clubs screen (or null); `zip` = a zip just searched or set. */
export const getSponsored = (placement: SponsorPlacement, zip?: string) =>
  getJSON<{ card: Partner | null }>(`${A}/sponsored?placement=${placement}${zip ? `&zip=${encodeURIComponent(zip)}` : ''}`)
export const hideSponsored = (id: string, placement: SponsorPlacement) =>
  postJSON<{ hidden: boolean }>(`${A}/${encodeURIComponent(id)}/hide`, { placement })
export const countSponsored = (id: string, what: 'impression' | 'tap', placement: SponsorPlacement) =>
  postJSON<{ counted: boolean }>(`${A}/${encodeURIComponent(id)}/count`, { what, placement })
export const listPartnersAdmin = () => getJSON<PartnerAdminList>(`${A}/admin`)
export const addPartner = (d: PartnerDraft) => postJSON<PartnerAdminList & { id: string }>(`${A}/admin`, d)
export const editPartner = (id: string, d: PartnerDraft) => sendJSON<PartnerAdminList & { id: string }>('PUT', `${A}/admin/${encodeURIComponent(id)}`, d)
export const removePartner = (id: string) => sendJSON<PartnerAdminList>('DELETE', `${A}/admin/${encodeURIComponent(id)}`, {})

// ---------------------------------------------------------------- name search --
export type DirSearch = {
  q: string; metro: { city: string; state: string; label: string } | null
  partners: Partner[]; listings: DirListing[]; can_look_up: boolean
  area?: DirArea | null; farther?: number
}
export type DirLookup = { status: 'found' | 'none' | 'limit' | 'unavailable'; listings: DirListing[] }
export const searchDirectory = (q: string, f: DirFilters = {}) => getJSON<DirSearch>(`${P}/search${filterQuery(f, { q })}`)
export const lookUpClub = (q: string) => postJSON<DirLookup>(`${P}/lookup`, { q })

export function getDirectory(f: DirFilters = {}): Promise<DirView> {
  return getJSON<DirView>(`${P}${filterQuery(f)}`)
}
export const suggestClub = (b: { name: string; url: string; city?: string; state?: string }) =>
  postJSON<{ ok: boolean; message: string }>(`${P}/suggest`, b)
export const reportListing = (id: string) =>
  postJSON<{ ok: boolean; hidden: boolean; message: string }>(`${P}/${encodeURIComponent(id)}/report`, {})
export const markGoing = (id: string, going: boolean, date?: string) =>
  going ? counted(postJSON<{ going: DirGoing }>(`${P}/${encodeURIComponent(id)}/going`, { going, date }), 'rsvp', { kind: 'group' })
    : postJSON<{ going: DirGoing }>(`${P}/${encodeURIComponent(id)}/going`, { going, date })
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
