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
}
export type DirectoryRace = { id: string | null; name: string | null; type: string | null; distance: string | null; date: string | null }
export type DirectoryResp = {
  coaches: DirectoryCoach[]; race: DirectoryRace | null
  coach_status: 'have_coach' | 'looking' | 'self_coached' | null; has_coach: boolean
}

export const DIRECTORY_SPORTS: [string, string][] = [
  ['triathlon', 'Triathlon'], ['running', 'Running'], ['cycling', 'Cycling'], ['swimming', 'Swimming'], ['strength', 'Strength'],
]

export function getDirectory(f: { sport?: string; q?: string } = {}) {
  const p = new URLSearchParams()
  if (f.sport) p.set('sport', f.sport)
  if (f.q?.trim()) p.set('q', f.q.trim())
  const qs = p.toString()
  return getJSON<DirectoryResp>(`/api/coaches/directory${qs ? `?${qs}` : ''}`)
}
export const inviteDirectoryCoach = (id: string) =>
  sendJSON<{ coaches: CoachLink[] }>('POST', `/api/coaches/directory/${encodeURIComponent(id)}/invite`, {})

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
