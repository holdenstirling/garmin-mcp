// Race fit (deterministic athlete-vs-event factors), the AI race strategy, and the coach's
// race notes for one event.
import { getJSON, sendJSON } from '@/lib/api'
import type { CourseProfile, RaceStrategy } from '@/lib/events'
import type { Note } from '@/lib/coach'

export type Impact = 'helps' | 'neutral' | 'watch' | 'risk'
export type FitFactor = { id: string; title: string; impact: Impact; detail: string; tip: string }
export type RaceFit = {
  factors: FitFactor[]; summary: string
  elevation: { m: number; high_m: number | null; source: string } | null
  course_profile: CourseProfile | null; climb_m_per_km: number | null
}
export type RaceView = {
  event: { id: string; name: string; date: string; type: string; distance: string; location: string; main: boolean }
  racefit: RaceFit; strategy: RaceStrategy | null; coach_notes: Note[]
}

export const getRaceView = (eventId: string) => getJSON<RaceView>(`/api/events/${encodeURIComponent(eventId)}/strategy`)
export const makeStrategy = (eventId: string) => sendJSON<RaceView>('POST', `/api/events/${encodeURIComponent(eventId)}/strategy`)

export const IMPACT_LABEL: Record<Impact, string> = { helps: 'Helps', neutral: 'Neutral', watch: 'Watch', risk: 'Risk' }
