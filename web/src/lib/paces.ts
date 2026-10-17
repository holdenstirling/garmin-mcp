// Training paces (server: paces.py): current thresholds + zones with provenance, and
// "your threshold moved" suggestions with one-tap accept, Not now / Never and 24 h undo.
import { getJSON, postJSON, sendJSON } from '@/lib/api'

export type PaceSport = 'run' | 'bike' | 'swim'
export type PaceZone = { zone: number; name: string; lo: number; hi: number }
export type PaceSource = { how: 'suggested' | 'manual'; label: string; date?: string; activity_ids?: number[] }
export type PaceRow = {
  /** run: s/km, bike: W, swim: s/100m */
  value: number | null
  zones: PaceZone[]
  source: PaceSource | null
  /** false after "Never for this" */
  suggestions: boolean
}
export type PaceEffort = { label: string; detail: string; date: string; activity_id: number | null; kind: string }
export type PaceSuggestion = {
  id: string; sport: PaceSport; field: string
  direction: 'faster' | 'slower' | 'set'
  old: number | null; new: number; capped: boolean; created: string
  /** full sentence in the athlete's units */
  headline: string
  efforts: PaceEffort[]
  skipped: { label: string; reason: string }[]
}
export type PaceUndo = { id: string; sport: PaceSport; summary: string; until: number }
export type PacesView = {
  units: 'metric' | 'imperial'; threshold_hr: number | null
  run: PaceRow; bike: PaceRow; swim: PaceRow
  pending: PaceSuggestion[]
  undo: PaceUndo | null
}
export type PaceAccepted = { summary: string; updated: number; undo: { id: string; until: number; sport: PaceSport }; field: string; value: number }

export const getPaces = () => getJSON<PacesView>('/api/paces')
/** Fired after paces change (accept / undo): the plan's targets were re-computed. */
export const PACES_CHANGED_EVENT = 'rabbit:paces-changed'
const changed = <T,>(r: T): T => { try { window.dispatchEvent(new CustomEvent(PACES_CHANGED_EVENT)) } catch { /* ignore */ } return r }
export const acceptPace = (sid: string) => postJSON<PaceAccepted>(`/api/paces/${encodeURIComponent(sid)}/accept`).then(changed)
export const dismissPace = (sid: string, never = false) =>
  postJSON<{ ok: boolean }>(`/api/paces/${encodeURIComponent(sid)}/dismiss`, { never })
export const undoPace = (id: string) => sendJSON<{ field: string; value: number | null }>('POST', '/api/paces/undo', { id }).then(changed)
export const setPaceSuggestions = (sport: PaceSport, on: boolean) =>
  postJSON<{ ok: boolean }>('/api/paces/suggestions', { sport, on })

export const SPORT_NAME: Record<PaceSport, string> = { run: 'Run threshold', bike: 'Bike FTP', swim: 'Swim CSS' }

/** Open the suggestion sheet from anywhere (a moment chip, Profile). `accept`: apply at once. */
export type PaceOpen = { sport?: string; sid?: string; accept?: boolean }
export function openPaceSuggestion(detail: PaceOpen = {}) {
  window.dispatchEvent(new CustomEvent<PaceOpen>('rabbit:pace', { detail }))
}
