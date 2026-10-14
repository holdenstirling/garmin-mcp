// Plan imports: a coach (or the athlete) loads a whole plan from the in-app grid, a file
// (CSV/XLSX template, TrainingPeaks export, iCal, PDF or photo read by Rabbit), with a
// preview before it replaces anything and undo for 7 days. Base: '/api' (athlete) or
// coachBase(aid).
import { AuthError, getJSON, sendJSON, type Sport } from '@/lib/api'
import type { BuiltPlan } from '@/lib/plan'

export type Intensity = 'easy' | 'recovery' | 'long' | 'endurance' | 'tempo' | 'threshold' | 'intervals'
  | 'race_pace' | 'strides' | 'technique' | 'strength' | 'mobility' | 'race'
export type GridRow = { date: string; sport: Sport; title: string; minutes: number | null; intensity: Intensity; notes?: string }
export type TemplateRow = { weekday: number; sport: Sport; title: string; minutes: number; intensity: Intensity }

export type ImportStatus = {
  can_edit: boolean; ai_left: number; ai_per_day: number; next_monday: string; today: string
  undo: { at: number; by_name: string; until: number; restores: 'previous plan' | 'no plan' } | null
  last: ImportSummary | null
}
export type ImportSummary = {
  by_name: string; role: 'coach' | 'athlete'; at: number; weeks: number; sessions: number; first_day: string
  added: number; changed: number; removed: number; source: string; name: string | null
}
export type BriefSession = { date: string; sport: Sport; title: string; minutes: number | null; kind: string }
export type Change = BriefSession & { type: 'added' | 'changed' | 'removed'; was?: BriefSession }
export type PreviewWeek = {
  index: number | null; start: string; phase: string | null; recovery: boolean; hours: number; count: number
  sessions: BriefSession[]; added: number; changed: number; removed: number; changes: Change[]
}
export type Preview = {
  id: string; source: string; name: string | null; first_day: string; last_day: string
  weeks: PreviewWeek[]; replaces: boolean; garmin_synced: number
  totals: { weeks: number; sessions: number; hours: number; added: number; changed: number; removed: number }
  warnings: string[]; warning_count: number; skipped: number
}
export type Draft = {
  rows: GridRow[]; sports: Sport[]; intensities: Intensity[]; next_monday: string; today: string
  templates: { hours: number; sports: Sport[]; weeks: Record<'base' | 'build' | 'recovery', TemplateRow[]> }
}

export const INTENSITY_LABEL: Record<Intensity, string> = {
  easy: 'Easy', recovery: 'Recovery', long: 'Long', endurance: 'Endurance', tempo: 'Tempo', threshold: 'Threshold',
  intervals: 'Intervals', race_pace: 'Race pace', strides: 'Strides', technique: 'Technique', strength: 'Strength',
  mobility: 'Mobility', race: 'Race',
}

export function importApi(base: string) {
  const b = `${base}/plan/import`
  return {
    status: () => getJSON<ImportStatus>(b),
    draft: () => getJSON<Draft>(`${b}/draft`),
    templateUrl: `/app${b}/template.csv`,
    rows: (rows: GridRow[], name?: string) => sendJSON<{ preview: Preview }>('POST', `${b}/rows`, { rows, name, source: 'grid' }),
    file: async (file: File, opts: { start?: string; via?: 'trainingpeaks' } = {}) => {
      const q = new URLSearchParams({ name: file.name })
      if (opts.start) q.set('start', opts.start)
      if (opts.via) q.set('via', opts.via)
      const r = await fetch(`/app${b}/file?${q}`, {
        method: 'POST', credentials: 'same-origin', body: file,
        headers: { 'content-type': file.type || 'application/octet-stream' },
      })
      if (r.status === 401) throw new AuthError('not signed in')
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(data.error ?? `HTTP ${r.status}`)
      return data as { preview: Preview }
    },
    apply: (id: string) => sendJSON<{ plan: BuiltPlan; summary: ImportSummary }>('POST', `${b}/${id}/apply`, {}),
    undo: () => sendJSON<{ plan: BuiltPlan | null; restored: boolean }>('POST', `${b}/undo`, {}),
  }
}
export type ImportApi = ReturnType<typeof importApi>

/** YYYY-MM-DD plus n days (local noon, so DST never shifts the day). */
export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00`)
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
/** The Monday on or before a date. */
export function mondayOf(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  return addDays(iso, -((d.getDay() + 6) % 7))
}
