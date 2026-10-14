// Find a coach: the curated coach directory (coachdir.py). Rabbit doesn't take a cut; the
// athlete contacts coaches directly.
import { getJSON, sendJSON } from '@/lib/api'
import type { CoachLink } from '@/lib/coach'

export type DirectoryCoach = {
  id: string; name: string; business: string; location: string; photo_url: string | null
  sports: string[]; specialties: string[]; credentials: string[]; bio: string; highlights: string[]
  testimonial: { quote: string; by: string } | null; services: string[]; pricing_note: string | null
  contact: { email?: string | null; phone?: string | null; website?: string | null }
  accepting: boolean; verified_by_operator: boolean
  /** the coach has a Rabbit login: "Invite as my coach" works in the app */
  can_invite: boolean
  match: { score: number; why: string }
  /** true/false only when Rabbit recorded it; null = unknown (never assume remote) */
  remote: boolean | null
  /** "~15 mi from you" (city centroids) when you saved a location in Explore */
  distance_label: string | null
}
export type DirectoryRace = { id: string | null; name: string | null; type: string | null; distance: string | null; date: string | null }
export type DirectoryResp = {
  coaches: DirectoryCoach[]; race: DirectoryRace | null
  coach_status: 'have_coach' | 'looking' | 'self_coached' | null; has_coach: boolean
  /** a saved Explore location exists (distances work); the location itself never comes back */
  has_location?: boolean; area?: string
}
export type CoachScope = 'local' | 'remote'
export type CoachFormat = 'any' | 'in_person' | 'remote'
export const DISTANCES_MI = [10, 25, 50] as const

/** A coach or club a web search found: name, specialty, area and a link. Not verified. */
export type WebCoach = { id: string; name: string; specialty: string; area: string; url: string; source: 'web'; label: string }
export type WebCoachResp = {
  coaches: WebCoach[]; area: string; label: string
  state: 'ok' | 'needs_location' | 'limit' | 'unavailable' | 'failed'
}
/** One web search per city + sport (shared, cached a week); uses 1 of the daily Explore searches on a miss. */
export const findWebCoaches = (sport?: string) =>
  sendJSON<WebCoachResp>('POST', '/api/coaches/directory/web', sport ? { sport } : {})

export const DIRECTORY_SPORTS: [string, string][] = [
  ['triathlon', 'Triathlon'], ['running', 'Running'], ['cycling', 'Cycling'], ['swimming', 'Swimming'], ['strength', 'Strength'],
]

export function getDirectory(f: { sport?: string; q?: string; scope?: CoachScope; format?: CoachFormat; within?: number } = {}) {
  const p = new URLSearchParams()
  if (f.sport) p.set('sport', f.sport)
  if (f.q?.trim()) p.set('q', f.q.trim())
  if (f.scope) p.set('scope', f.scope)
  if (f.format && f.format !== 'any') p.set('format', f.format)
  if (f.within) p.set('within', String(f.within))
  const qs = p.toString()
  return getJSON<DirectoryResp>(`/api/coaches/directory${qs ? `?${qs}` : ''}`)
}
/** View-only unless the athlete turned the permissions on in the confirmation. */
export const inviteDirectoryCoach = (id: string, perms: { can_edit_plan?: boolean; can_see_rabbit_chats?: boolean } = {}) =>
  sendJSON<{ coaches: CoachLink[] }>('POST', `/api/coaches/directory/${encodeURIComponent(id)}/invite`, {
    can_edit_plan: perms.can_edit_plan === true, can_see_rabbit_chats: perms.can_see_rabbit_chats === true })

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '?') + (parts.length > 1 ? parts[parts.length - 1]![0] : '')).toUpperCase()
}

/** "Sat, May 9" for a YYYY-MM-DD date (local, no timezone shift). */
export function raceDay(d: string | null | undefined): string {
  if (!d) return ''
  const dt = new Date(`${d}T12:00:00`)
  return Number.isNaN(dt.getTime()) ? d : dt.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

/** A friendly first email the athlete sends themselves. */
export function mailtoHref(c: DirectoryCoach, race: DirectoryRace | null, athleteName: string): string {
  const first = c.name.split(' ')[0] ?? c.name
  const raceBit = race?.name ? `${race.name}${race.date ? ` on ${raceDay(race.date)}` : ''}` : ''
  const subject = raceBit ? `Coaching for ${race!.name}` : 'Coaching inquiry'
  const body = [
    `Hi ${first},`,
    '',
    `I came across ${c.business || 'your coaching'} and I'm interested in working with a coach.` +
      (raceBit ? ` I'm training for ${raceBit}.` : ''),
    'Could you tell me how you work with athletes and what it would cost?',
    '',
    athleteName.trim() ? `Thanks,\n${athleteName.trim()}` : 'Thanks!',
  ].join('\n')
  return `mailto:${c.contact.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}
