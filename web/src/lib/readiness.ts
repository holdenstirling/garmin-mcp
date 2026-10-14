// Race readiness: one deterministic grade per race (readiness.py), with what would most raise it.
import { getJSON } from '@/lib/api'
import { coachBase } from '@/lib/coach'

export type ReadinessStatus = 'ahead' | 'on_track' | 'behind' | 'at_risk'
export type Confidence = 'low' | 'medium' | 'high'
export type ReadinessComponent = { id: string; label: string; score: number; weight: number; detail: string; tip: string }
export type Readiness = {
  event_id: string; grade: string; score: number; status: ReadinessStatus; confidence: Confidence
  headline: string; summary: string; components: ReadinessComponent[]; actions: string[]
  weeks_to_race: number; days_to_race: number; projected_fitness: number; current_fitness: number
  target_fitness: number; forecast: boolean; updated: number
}
export type RaceGrade = {
  event_id: string; name: string; date: string; main: boolean; grade: string; score: number
  status: ReadinessStatus; headline: string; confidence: Confidence
}

export const getReadiness = (eventId: string) => getJSON<Readiness>(`/api/events/${encodeURIComponent(eventId)}/readiness`)
export const listReadiness = () => getJSON<{ races: RaceGrade[] }>('/api/readiness')
export const getAthleteReadiness = (aid: string) => getJSON<{ races: RaceGrade[] }>(`${coachBase(aid)}/readiness`)

export const STATUS_LABEL: Record<ReadinessStatus, string> = {
  ahead: 'Ahead', on_track: 'On track', behind: 'Behind', at_risk: 'At risk',
}

/** The race the plan builds toward, else the next one. */
export function mainRace(races: RaceGrade[]): RaceGrade | null {
  return races.find((r) => r.main) ?? races[0] ?? null
}
