// Traction (server: traction.py): a person's firsts, "How did you hear about rabbt?", the one
// day-7 "How likely are you to recommend rabbt?" card, and the owner's traction summary.
// Firsts ride the usage queue (lib/usage), so Do Not Track and "Don't count my usage" hold.
import { getJSON, postJSON } from '@/lib/api'
import { track, type Milestone } from '@/lib/usage'
import { markArea, markJob, markPlan } from '@/lib/newcomer'

const sent = new Set<Milestone>()
/** Report a first (the server counts it once per person; this skips repeats per page load). */
export function milestone(what: Milestone): void {
  // the Getting started checklist ticks even when usage counting is off
  if (what === 'rsvp' || what === 'run_posted') markJob()
  else if (what === 'area_set') markArea()
  else if (what === 'plan_built') markPlan()
  if (sent.has(what)) return
  sent.add(what)
  track('milestone', { what })
}

export type HeardSource = 'friend' | 'club' | 'instagram' | 'strava' | 'event' | 'search' | 'other'
export const HEARD_OPTIONS: { id: HeardSource; label: string }[] = [
  { id: 'friend', label: 'A friend or an invite' },
  { id: 'club', label: 'A club or run club' },
  { id: 'instagram', label: 'Instagram' },
  { id: 'strava', label: 'Strava' },
  { id: 'event', label: 'An event or a flyer' },
  { id: 'search', label: 'Searching online' },
  { id: 'other', label: 'Somewhere else' },
]
export const saveHeard = (source: HeardSource) => postJSON<{ ok: boolean }>('/api/heard', { source })

export const getPulse = () => getJSON<{ ask: boolean }>('/api/pulse')
export const answerPulse = (score: number, note?: string) => postJSON<{ ok: boolean }>('/api/pulse', { score, note: note || undefined })
export const dismissPulse = () => postJSON<{ ok: boolean }>('/api/pulse', { dismiss: true })

type Pct = { cohort: number; users: number; pct: number | null }
export type Traction = {
  targets: { core7_pct: number; w4_pct: number; clubs_weekly: number; rsvps_per_run: number; nps: number }
  growth: {
    signups: number; sources: { id: HeardSource; users: number }[]; answered: number
    invite_joins: number; club_joins: number; club_refs: { slug: string; users: number }[]
  }
  activation: { funnel: { id: 'signup' | 'area_set' | 'job' | 'plan_built'; users: number; pct: number | null }[]; core7: Pct; firsts: Record<Milestone, number> }
  retention: { w4: Pct }
  weeks: { week: string; active: number; denver: number }[]
  denver: { week: string; active: number; runners: number; pct: number; clubs: number; known_clubs: number; clubs_pct: number | null }
  organizers: {
    weeks: { week: string; from: string; clubs_created: number; runs_posted: number; runs_held: number; rsvps_per_run: number | null; checkin_pct: number | null }[]
    clubs: number; healthy_clubs: number; repeat_attendees: number
  }
  nps: { answers: number; promoters: number; passives: number; detractors: number; score: number | null; hist: number[] }
  notes: { name: string; score: number | null; note: string; date: string }[]
}
export const getTraction = () => getJSON<Traction>('/api/usage/traction')
