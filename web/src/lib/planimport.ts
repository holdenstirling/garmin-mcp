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
  can_save_templates?: boolean; race_date?: string | null
  undo: { at: number; by_name: string; until: number; restores: 'previous plan' | 'no plan' } | null
  last: ImportSummary | null
}
export type ImportSummary = {
  by_name: string; role: 'coach' | 'athlete'; at: number; weeks: number; sessions: number; first_day: string
  added: number; changed: number; removed: number; source: string; name: string | null; mode?: ImportMode
}
export type BriefSession = { date: string; sport: Sport; title: string; minutes: number | null; kind: string }
export type Change = BriefSession & { type: 'added' | 'changed' | 'removed'; was?: BriefSession }
export type PreviewWeek = {
  index: number | null; start: string; phase: string | null; recovery: boolean; hours: number; count: number
  sessions: BriefSession[]; added: number; changed: number; removed: number; changes: Change[]
}
export type ImportMode = 'replace' | 'add' | 'weeks' | 'fill'
/** One session of a draft, as the server cleaned it (edited locally, sent back on update). */
export type DraftRow = {
  line?: number | string | null; date: string; sport: Sport; kind?: string | null; intensity?: Intensity
  minutes: number | null; title: string; notes: string; steps?: unknown[] | null; warn?: string | null; past?: boolean
}
/** A row that couldn't be read, with what was there (to fix or dismiss). */
export type ImportIssue = { line: number | string | null; reason: string; date: string; sport: string; title: string; minutes: number | null; notes: string }
export type Preview = {
  id: string; source: string; name: string | null; first_day: string; last_day: string
  weeks: PreviewWeek[]; replaces: boolean; garmin_synced: number
  totals: { weeks: number; sessions: number; hours: number; added: number; changed: number; removed: number }
  warnings: string[]; warning_count: number; skipped: number
  rows: DraftRow[]; issues: ImportIssue[]; mode: ImportMode; suggested_mode: ImportMode | null; has_plan: boolean
  today: string; next_monday: string
  /** the athlete's upcoming race (for "end on race day") */
  race_date?: string | null; race_title?: string | null
  /** days where the current plan and this one both have sessions */
  conflicts?: { date: string; old: string[]; new: string[] }[]; conflict_count?: number
  /** workbook sheets (when there are several) and the one read */
  sheets?: string[]; sheet?: number | null
  schedule?: Schedule | null; relative?: boolean
}
/** "When does it start?": week 1 next Monday, the week of a date, or the plan ends on race day. */
export type Schedule = { how: 'monday' } | { how: 'date'; date: string } | { how: 'race' }
export type MapField = 'date' | 'week' | 'weekday' | 'sport' | 'title' | 'duration' | 'distance' | 'intensity' | 'notes'
/** A sheet whose columns Rabbit couldn't place: pick them, then send the same file again. */
export type ColumnMapping = {
  name: string; header_row: number; headers: string[]; sample: string[][]
  guess: Record<MapField, number | null>; fields: MapField[]; columns: number
  sheets?: string[]; sheet?: number | null
}
export type PlanTemplate = { id: string; label: string; group: string; weeks: number; blurb: string; mode: ImportMode; sessions?: number }
export type TemplateLevel = 'beginner' | 'intermediate'
export type TemplateList = {
  templates: PlanTemplate[]; groups: { id: string; label: string }[]
  levels: TemplateLevel[]; race_date: string | null; race_title: string | null
  /** a coach's own templates (null for athletes) */
  mine: PlanTemplate[] | null
}
export type UploadResult = { preview: Preview; mapping?: undefined } | { mapping: ColumnMapping; preview?: undefined }
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
    /** One request for one or several files (photos/pages read together; sheets parsed here). */
    upload: async (files: Blob[], names: string[], opts: { start?: string; via?: 'trainingpeaks'; mode?: ImportMode; map?: { header_row: number; cols: Partial<Record<MapField, number>> }; ai?: boolean; sheet?: number } = {}) => {
      const q = new URLSearchParams()
      names.forEach((n) => q.append('name', n))
      if (files.length > 1) files.forEach((f) => q.append('size', String(f.size)))
      if (opts.start) q.set('start', opts.start)
      if (opts.via) q.set('via', opts.via)
      if (opts.mode) q.set('mode', opts.mode)
      if (opts.map) q.set('map', JSON.stringify(opts.map))
      if (opts.ai) q.set('ai', '1')
      if (opts.sheet != null) q.set('sheet', String(opts.sheet))
      const body = files.length === 1 ? files[0]! : new Blob(files)
      const r = await fetch(`/app${b}/file?${q}`, {
        method: 'POST', credentials: 'same-origin', body,
        headers: { 'content-type': (files.length === 1 && files[0]!.type) || 'application/octet-stream' },
      })
      if (r.status === 401) throw new AuthError('not signed in')
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(data.error ?? `HTTP ${r.status}`)
      return data as UploadResult
    },
    update: (id: string, rows: DraftRow[], opts: { mode?: ImportMode; issues?: ImportIssue[]; schedule?: Schedule } = {}) =>
      sendJSON<{ preview: Preview }>('POST', `${b}/${id}/update`, {
        rows: rows.map(({ past: _p, ...r }) => r), mode: opts.mode, issues: opts.issues, schedule: opts.schedule,
      }),
    /** A Google Sheets/Docs link (published or shared with anyone): fetched by the server. */
    link: (url: string, opts: { start?: string } = {}) => sendJSON<UploadResult>('POST', `${b}/link`, { url, ...opts }),
    /** Coach only: keep a draft (or the athlete's current plan) as "my template". */
    saveMine: (name: string, from: { import_id: string } | { from: 'plan' }) =>
      sendJSON<{ template: PlanTemplate; mine: PlanTemplate[] }>('POST', `${b}/mine`, { name, ...from }),
    deleteMine: (id: string) => sendJSON<{ mine: PlanTemplate[] }>('POST', `${b}/mine/${encodeURIComponent(id)}/delete`, {}),
    pending: () => getJSON<{ preview: Preview | null }>(`${b}/pending`),
    discard: (id: string) => sendJSON<{ ok: boolean }>('POST', `${b}/${id}/discard`, {}),
    templates: () => getJSON<TemplateList>(`${b}/templates`),
    template: (id: string, opts: { start?: string; mode?: ImportMode; level?: TemplateLevel; end?: 'race' } = {}) =>
      sendJSON<{ preview: Preview }>('POST', `${b}/template/${encodeURIComponent(id)}`, opts),
    exportUrl: (fmt: 'csv' | 'ics') => `/app${b}/export.${fmt}`,
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

/** Every row moved by n days. */
export function shiftRows<T extends { date: string }>(rows: T[], n: number): T[] {
  return n ? rows.map((r) => ({ ...r, date: addDays(r.date, n) })) : rows
}
/** Whole days from a to b (YYYY-MM-DD). */
export function daysBetween(a: string, b: string): number {
  return Math.round((new Date(`${b}T12:00:00`).getTime() - new Date(`${a}T12:00:00`).getTime()) / 86_400_000)
}
/** A Google Sheets/Docs link Rabbit can fetch (published to the web, or shared with anyone). */
export function isGoogleDocLink(text: string): boolean {
  return /^https:\/\/docs\.google\.com\/(spreadsheets|document)\/d\/(e\/)?[A-Za-z0-9_-]{10,}/.test(text.trim()) && !/\s/.test(text.trim())
}
/** A paste that's only a link Rabbit can't fetch: what to do instead. */
export function linkHelp(text: string): string | null {
  const t = text.trim()
  if (!/^https?:\/\/\S+$/i.test(t) || isGoogleDocLink(t)) return null
  if (/^https?:\/\/(docs|drive|sheets)\.google\.com\//i.test(t)) {
    const sheets = t.includes('/spreadsheets/')
    return `That's a Google ${sheets ? 'Sheets' : 'Docs'} link, and Rabbit can't open private documents. In Google ${sheets ? 'Sheets' : 'Docs'} choose File → Download → ${sheets ? 'CSV' : 'PDF'}, then drop the file here.`
  }
  if (/trainingpeaks\.com/i.test(t)) return 'That\'s a TrainingPeaks link. Export the workouts (CSV) or save the calendar (.ics) from TrainingPeaks, then drop the file here.'
  return 'Rabbit can\'t open links. Download the file and drop it here, or paste the plan\'s text.'
}
/** Files Rabbit reads with the model (vs parsed instantly). */
export const READ_BY_RABBIT = /\.(pdf|png|jpe?g|webp|gif|heic|heif|txt|md|eml|rtf|docx?|odt)$/i
export const ACCEPT = '.csv,.tsv,.xlsx,.ods,.ics,.pdf,.txt,.md,.docx,.odt,.zwo,.erg,.mrc,.fit,text/csv,text/plain,text/calendar,application/pdf,image/*'
