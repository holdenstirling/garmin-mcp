// The review step of "Add plan": every session grouped by week, quick to fix before anything
// changes. "When does it start?" (next Monday, a date, or end on race day like TrainingPeaks'
// plan apply) moves the whole plan on the server. Week cards show sessions per day with
// totals and inline warnings (crowded days, big jumps, clashes with the current plan). Tap a
// session to edit sport/title/time/date/intensity, delete or duplicate it; rows Rabbit wasn't
// sure about are highlighted; rows it couldn't read can be fixed or dismissed; choose replace /
// fill empty days / add / replace only these weeks. Edits save to the server-side draft
// (debounced), so closing never loses them. After "Looks good": a small celebration (off with
// reduced motion) and, for the athlete, "Send the first 2 weeks to Garmin".
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { celebrate } from '@/components/fx'
import { BookmarkPlus, Check, ChevronDown, ChevronUp, CircleAlert, Copy, Pencil, Plus, Trash2, TriangleAlert, Watch, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { cn } from '@/lib/utils'
import { fmtDuration } from '@/lib/format'
import type { Sport } from '@/lib/api'
import { syncGarmin, type SyncResult } from '@/lib/plan'
import {
  INTENSITY_LABEL, addDays, mondayOf, shiftRows, type DraftRow, type ImportApi, type ImportIssue, type ImportMode,
  type Intensity, type Preview, type Schedule,
} from '@/lib/planimport'
import { Card, Chip, ChipRow, NumberStepper, Screen, inputCls } from './ui'
import { SPORT_ICON, SPORT_LABEL, fmtDay } from './PlanParts'

type Who = 'coach' | 'athlete'
type Row = DraftRow & { key: string }
type Editing = { key: string } | { issue: number } | { add: string } | null

let seq = 0
const keyed = (rows: DraftRow[]): Row[] => rows.map((r) => ({ ...r, key: `r${++seq}` }))
const short = (d: string) => fmtDay(d, { month: 'short', day: 'numeric' })
const SPORTS: Sport[] = ['run', 'bike', 'swim', 'brick', 'strength', 'other']
const QUICK: Intensity[] = ['easy', 'long', 'tempo', 'threshold', 'intervals', 'recovery', 'race']
const KIND_TO_INTENSITY: Record<string, Intensity> = {
  vo2: 'intervals', racepace: 'race_pace', css: 'threshold', openers: 'intervals', shakeout: 'easy', brick: 'endurance',
}
const intensityOf = (r: DraftRow): Intensity =>
  r.intensity ?? KIND_TO_INTENSITY[r.kind ?? ''] ?? ((r.kind ?? 'easy') in INTENSITY_LABEL ? r.kind as Intensity : 'easy')
const MODES: { id: ImportMode; label: string; text: string }[] = [
  { id: 'replace', label: 'Replace the plan', text: 'Everything from the first day on becomes this plan.' },
  { id: 'fill', label: 'Fill empty days only', text: 'Keeps every current session; these go only on free days.' },
  { id: 'add', label: 'Add on top', text: 'Keeps every current session and adds all of these (up to 4 a day).' },
  { id: 'weeks', label: 'Replace only these weeks', text: 'Swaps the weeks this covers; other weeks stay.' },
]
type How = Schedule['how']
type WeekView = { start: string; rows: Row[]; minutes: number; count: number }

/** Inline heads-ups for one week: crowded days, a big jump on the week before, clashes with
 *  the current plan (when they're kept). */
function weekNotes(w: WeekView, prev: WeekView | undefined, clashes: Set<string>, mode: ImportMode): { text: string; bad?: boolean }[] {
  const out: { text: string; bad?: boolean }[] = []
  const per = new Map<string, number>()
  for (const r of w.rows) if (r.sport !== 'rest') per.set(r.date, (per.get(r.date) ?? 0) + 1)
  for (const [d, n] of [...per.entries()].sort()) {
    const day = fmtDay(d, { weekday: 'short', month: 'numeric', day: 'numeric' })
    if (n > 4) out.push({ text: `${n} sessions on ${day}: up to 4 a day, move or delete some`, bad: true })
    else if (n >= 3) out.push({ text: `${n} sessions on ${day}` })
  }
  if (prev && prev.minutes >= 120 && w.minutes > prev.minutes * 1.5) {
    out.push({ text: `${Math.round((w.minutes / prev.minutes - 1) * 100)}% more time than the week before` })
  }
  const clash = [...per.keys()].filter((d) => clashes.has(d))
  if (clash.length) {
    out.push({ text: mode === 'fill'
      ? `${clash.length} day${clash.length === 1 ? '' : 's'} already planned: ${clash.length === 1 ? 'it keeps' : 'they keep'} the current session${clash.length === 1 ? '' : 's'}`
      : `${clash.length} day${clash.length === 1 ? '' : 's'} get${clash.length === 1 ? 's' : ''} these on top of the current sessions` })
  }
  return out
}

export function PlanReview({ api, initial, who, athleteName, onClose, onApplied, onSheet, canSaveTemplate }: {
  api: ImportApi; initial: Preview; who: Who; athleteName: string; onClose: () => void; onApplied: () => void
  /** read another sheet of the same workbook (replaces this draft) */
  onSheet?: (index: number) => Promise<void>
  /** coach: offer "Save as my template" */
  canSaveTemplate?: boolean
}) {
  const [server, setServer] = useState(initial)
  const [rows, setRows] = useState<Row[]>(() => keyed(initial.rows))
  const [issues, setIssues] = useState<ImportIssue[]>(initial.issues)
  const [mode, setMode] = useState<ImportMode>(initial.mode)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Editing>(null)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [allWarn, setAllWarn] = useState(false)
  const [showPast, setShowPast] = useState(false)
  const [closing, setClosing] = useState(false)
  const [how, setHow] = useState<How | null>(() => initial.schedule?.how
    ?? (initial.rows.length && mondayOf([...initial.rows].sort((x, y) => x.date.localeCompare(y.date))[0]!.date) === initial.next_monday ? 'monday' : null))
  const [moving, setMoving] = useState(false)
  const [fine, setFine] = useState(false)
  const [sync, setSync] = useState<{ busy: boolean; result: SyncResult | null; error: string | null }>({ busy: false, result: null, error: null })
  const timer = useRef<number | null>(null)
  const version = useRef(0)
  const latest = useRef({ rows, issues, mode })
  latest.current = { rows, issues, mode }
  const inflight = useRef<Promise<boolean> | null>(null)

  const save = useCallback(async (): Promise<boolean> => {
    if (timer.current) { window.clearTimeout(timer.current); timer.current = null }
    const v = ++version.current
    const { rows: rs, issues: is, mode: m } = latest.current
    setSaving(true)
    const run = api.update(server.id, rs, { mode: m, issues: is }).then((r) => {
      if (v === version.current) { setServer(r.preview); setSaveError(null) }
      return true
    }, (e) => {
      if (v === version.current) setSaveError((e as Error).message)
      return false
    }).finally(() => { if (v === version.current) setSaving(false) })
    inflight.current = run
    return run
  }, [api, server.id])

  const change = (next: { rows?: Row[]; issues?: ImportIssue[]; mode?: ImportMode }) => {
    if (next.rows) setRows(next.rows)
    if (next.issues) setIssues(next.issues)
    if (next.mode) setMode(next.mode)
    latest.current = { rows: next.rows ?? rows, issues: next.issues ?? issues, mode: next.mode ?? mode }
    setConfirm(false)
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void save(), 450)
  }
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current) }, [])

  // "When does it start?": the server moves the whole plan, then the rows come back dated.
  async function reschedule(s: Schedule) {
    if (timer.current) { window.clearTimeout(timer.current); timer.current = null }
    if (inflight.current) await inflight.current
    const v = ++version.current
    setMoving(true); setSaveError(null); setConfirm(false)
    try {
      const { rows: rs, issues: is, mode: m } = latest.current
      const r = await api.update(server.id, rs, { mode: m, issues: is, schedule: s })
      if (v !== version.current) return
      const next = keyed(r.preview.rows)
      setServer(r.preview); setRows(next); setHow(s.how)
      latest.current = { rows: next, issues: is, mode: m }
    } catch (e) {
      if (v === version.current) setSaveError((e as Error).message)
    } finally { if (v === version.current) setMoving(false) }
  }

  async function sendToGarmin() {
    setSync({ busy: true, result: null, error: null })
    try { const r = await syncGarmin(14); setSync({ busy: false, result: r.result, error: null }) } catch (e) { setSync({ busy: false, result: null, error: (e as Error).message }) }
  }

  async function flush(): Promise<boolean> {
    if (timer.current) return save()
    if (saving && inflight.current) return inflight.current
    return !saveError
  }
  const close = () => { void flush(); setClosing(true); setTimeout(onClose, 200) }

  async function apply() {
    setBusy(true); setError(null)
    try {
      if (!(await flush())) { setConfirm(false); return }
      await api.apply(server.id); setDone(true); celebrate({ x: window.innerWidth / 2, y: window.innerHeight / 3 }, 'plan')
    } catch (e) { setError((e as Error).message); setConfirm(false) } finally { setBusy(false) }
  }

  // ---- derived: weeks from the local rows (instant), diff counts from the server.
  const today = server.today
  const active = useMemo(() => rows.filter((r) => r.date >= today).sort((a, b) => a.date.localeCompare(b.date)), [rows, today])
  const past = rows.filter((r) => r.date < today)
  const weeks = useMemo(() => {
    const m = new Map<string, Row[]>()
    for (const r of active) { const k = mondayOf(r.date); m.set(k, [...(m.get(k) ?? []), r]) }
    const starts = [...m.keys()].sort()
    if (!starts.length) return []
    const out: WeekView[] = []
    for (let s = starts[0]!; s <= starts[starts.length - 1]!; s = addDays(s, 7)) {
      const rs = m.get(s) ?? []
      out.push({ start: s, rows: rs, minutes: rs.reduce((a, r) => a + (r.sport === 'rest' ? 0 : r.minutes ?? 0), 0),
        count: rs.filter((r) => r.sport !== 'rest').length })
    }
    return out
  }, [active])
  const clashes = useMemo(() => new Set((server.conflicts ?? []).map((c) => c.date)), [server.conflicts])
  const firstMonday = weeks[0]?.start ?? mondayOf(rows[0]?.date ?? server.next_monday)
  const sessions = active.filter((r) => r.sport !== 'rest').length
  const totalMin = weeks.reduce((a, w) => a + w.minutes, 0)
  const maxMin = Math.max(1, ...weeks.map((w) => w.minutes))
  const diff = new Map(server.weeks.map((w) => [w.start, w]))
  const flagged = active.filter((r) => r.warn).length
  const t = server.totals

  const updateRow = (key: string, patch: Partial<Row> | null, dup = false) => {
    const i = rows.findIndex((r) => r.key === key)
    if (i < 0) return
    const next = [...rows]
    if (patch === null) next.splice(i, 1)
    else if (dup) next.splice(i + 1, 0, { ...rows[i]!, key: `r${++seq}` })
    else next[i] = { ...rows[i]!, ...patch }
    change({ rows: next })
  }

  const whose = who === 'coach' ? `${athleteName}'s` : 'your'
  const modeLabel = !server.has_plan ? 'Load plan' : mode === 'add' ? 'Add to plan' : mode === 'weeks' ? 'Replace weeks' : mode === 'fill' ? 'Fill empty days' : 'Replace plan'
  const footer = done ? (
    <Button variant={who === 'athlete' && !sync.result ? 'default' : 'primary'} className="h-11 flex-1 text-[0.8235rem]" onClick={onApplied}>Done</Button>
  ) : confirm ? (
    <>
      <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={() => setConfirm(false)}>Back</Button>
      <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy} onClick={() => void apply()}>{modeLabel}</Button>
    </>
  ) : (
    <>
      <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={close}>Later</Button>
      <Button variant="primary" className="h-11 flex-1 gap-1 text-[0.8235rem]" disabled={!sessions || !!saveError || moving} onClick={() => setConfirm(true)}><Check className="size-4" /> Looks good</Button>
    </>
  )

  return (
    <Screen title="Review" subtitle={[server.name, server.source].filter(Boolean).join(' · ')} onBack={close} onClose={close} closing={closing} footer={footer}>
      {done ? (
        <div className="flex flex-col items-center gap-2 py-10 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)"><Check className="size-6" /></span>
          <p className="font-display text-[1.2941rem] text-(--brand)">Plan loaded</p>
          <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-muted)">
            {weeks.length} week{weeks.length === 1 ? '' : 's'}, {sessions} session{sessions === 1 ? '' : 's'}{active.length ? `, starting ${fmtDay(active[0]!.date, { weekday: 'short', month: 'short', day: 'numeric' })}` : ''}.{' '}
            {who === 'coach' ? `${athleteName} gets a message with the summary. ` : ''}You can undo it for 7 days from the Plan tab.
          </p>
          {who === 'athlete' && (
            <div className="mt-3 flex w-full max-w-xs flex-col items-stretch gap-2">
              {sync.result ? (
                <p className="flex items-center justify-center gap-1.5 text-[0.7647rem] text-(--accent)" role="status">
                  <Check className="size-4" /> {sync.result.uploaded + sync.result.unchanged} workout{sync.result.uploaded + sync.result.unchanged === 1 ? '' : 's'} on your Garmin calendar
                  {sync.result.errors.length ? ` · ${sync.result.errors.length} couldn't go` : ''}
                </p>
              ) : (
                <Button variant="primary" className="h-12 gap-1.5 text-[0.8235rem]" loading={sync.busy} onClick={() => void sendToGarmin()}>
                  <Watch className="size-4" /> Send the first 2 weeks to Garmin
                </Button>
              )}
              {sync.error && <p className="text-[0.7059rem] leading-snug text-(--danger)" role="alert">{sync.error}</p>}
            </div>
          )}
        </div>
      ) : <>
        <div className="flex items-end gap-3 px-1">
          <div className="min-w-0 flex-1">
            <p className="font-display text-[1.4118rem] leading-tight text-(--brand)">{weeks.length} week{weeks.length === 1 ? '' : 's'} · {sessions} session{sessions === 1 ? '' : 's'}</p>
            <p className="mt-1 text-[0.7647rem] text-(--text-muted)">
              {weeks.length ? `${short(active[0]!.date)} – ${short(active[active.length - 1]!.date)} · ` : ''}{fmtDuration(totalMin) || '0 min'} in total
            </p>
          </div>
          <span className="shrink-0 pb-0.5 text-[0.6471rem] text-(--text-muted)" aria-live="polite">{saving ? 'Saving…' : saveError ? '' : 'Draft saved'}</span>
        </div>

        {who === 'coach' && canSaveTemplate && <SaveDraftTemplate api={api} id={server.id} name={server.name} flush={flush} />}

        {(server.sheets?.length ?? 0) > 1 && onSheet && (
          <Card className="px-4 py-3">
            <p className="mb-2 text-[0.7647rem] text-(--text-muted)">This workbook has {server.sheets!.length} sheets. Rabbit read the one that looked like a plan.</p>
            <ChipRow>
              {server.sheets!.map((n, i) => (
                <Chip key={i} selected={server.sheet === i} disabled={moving}
                  onClick={() => { if (server.sheet !== i) { setMoving(true); setSaveError(null); onSheet(i).catch((e) => setSaveError((e as Error).message)).finally(() => setMoving(false)) } }}>{n}</Chip>
              ))}
            </ChipRow>
          </Card>
        )}

        <Card className="px-4 py-3">
          <p className="mb-2 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">When does it start?</p>
          <div role="radiogroup" aria-label="When does it start?" className="grid grid-cols-3 gap-1.5">
            {([['monday', 'Next Monday', short(server.next_monday)], ['date', 'On a date', how === 'date' ? short(firstMonday) : 'Pick a week'],
              ['race', 'End on race day', server.race_date ? short(server.race_date) : 'No race yet']] as const).map(([id, label, sub]) => (
              <button key={id} type="button" role="radio" aria-checked={how === id} disabled={moving || (id === 'race' && !server.race_date)}
                onClick={() => { if (id === 'date') { setHow('date'); return } void reschedule(id === 'race' ? { how: 'race' } : { how: 'monday' }) }}
                className={cn('flex min-h-14 flex-col items-center justify-center rounded-lg border px-1.5 py-1.5 text-center disabled:opacity-50',
                  how === id ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border)')}>
                <span className={cn('text-[0.7647rem] font-medium leading-tight', how === id ? 'text-(--accent)' : 'text-(--text)')}>{label}</span>
                <span className="text-[0.6471rem] text-(--text-muted)">{sub}</span>
              </button>
            ))}
          </div>
          {how === 'date' && (
            <label className="mt-2.5 flex flex-col gap-1">
              <span className="text-[0.7059rem] text-(--text-muted)">Week 1 is the week of</span>
              <input type="date" className={inputCls} value={firstMonday} min={mondayOf(today)}
                onChange={(e) => { if (e.target.value) void reschedule({ how: 'date', date: e.target.value }) }} />
            </label>
          )}
          <p className="mt-2 text-[0.7059rem] leading-snug text-(--text-secondary)" aria-live="polite">
            {moving ? 'Moving the plan…' : weeks.length ? <>Week 1 starts <b className="font-medium">{short(weeks[0]!.start)}</b>, the last session is <b className="font-medium">{short(active[active.length - 1]!.date)}</b>
              {server.race_date && active[active.length - 1]!.date === server.race_date ? ' (race day)' : ''}.</> : null}
          </p>
          <button type="button" className="mt-1 flex min-h-11 items-center gap-1 text-[0.7059rem] font-medium text-(--accent)" onClick={() => setFine((x) => !x)} aria-expanded={fine}>
            Nudge by a day or a week {fine ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
          {fine && (
            <div className="flex items-center justify-end gap-1.5">
              {([[-7, '−1 wk'], [-1, '−1 day'], [1, '+1 day'], [7, '+1 wk']] as const).map(([n, l]) => (
                <Button key={n} variant="default" className="h-11 px-2.5 text-[0.7059rem]" onClick={() => { setHow(null); change({ rows: shiftRows(rows, n) }) }}>{l}</Button>
              ))}
            </div>
          )}
        </Card>

        {weeks.length > 1 && <VolumeBars weeks={weeks} max={maxMin} />}

        {server.has_plan && (
          <Card className="px-4 py-3">
            <p className="mb-2 text-[0.7647rem] font-medium text-(--text)">{who === 'coach' ? `${athleteName} already has a plan` : 'You already have a plan'}</p>
            <div role="radiogroup" className="flex flex-col gap-1.5">
              {MODES.map((m) => (
                <button key={m.id} type="button" role="radio" aria-checked={mode === m.id} onClick={() => change({ mode: m.id })}
                  className={cn('flex min-h-12 items-center gap-2.5 rounded-lg border px-3 py-1.5 text-left',
                    mode === m.id ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border)')}>
                  <span className={cn('flex size-4 shrink-0 items-center justify-center rounded-full border', mode === m.id ? 'border-(--accent) bg-(--accent)' : 'border-(--border-strong)')}>
                    {mode === m.id && <span className="size-1.5 rounded-full bg-white" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={cn('block text-[0.7647rem] font-medium', mode === m.id ? 'text-(--accent)' : 'text-(--text)')}>
                      {m.label}{server.suggested_mode === m.id && server.suggested_mode !== 'replace' ? ' (suggested)' : ''}
                    </span>
                    <span className="block text-[0.6471rem] leading-snug text-(--text-muted)">{m.text}</span>
                  </span>
                </button>
              ))}
            </div>
            <div className="mt-2.5 flex flex-wrap gap-2">
              <Count n={t.added} label="added" tone="add" /><Count n={t.changed} label="changed" tone="change" /><Count n={t.removed} label="removed" tone="remove" />
            </div>
            {(server.conflict_count ?? 0) > 0 && (
              <p className="mt-2 text-[0.7059rem] leading-snug text-(--text-muted)">
                {server.conflict_count} day{server.conflict_count === 1 ? ' already has' : 's already have'} sessions in the current plan
                {mode === 'fill' ? ': those keep what they have.' : mode === 'add' ? ': both stay.' : '.'}
                {' '}First: {server.conflicts!.slice(0, 2).map((c) => `${fmtDay(c.date, { weekday: 'short', month: 'numeric', day: 'numeric' })} ${c.old[0]} → ${c.new[0]}`).join(', ')}.
              </p>
            )}
          </Card>
        )}

        {confirm && (
          <div className="rounded-xl border border-(--warning-text)/30 bg-(--bg-surface) px-3.5 py-3 text-[0.7647rem] leading-snug text-(--text)">
            {!server.has_plan ? `This becomes ${whose} plan. `
              : mode === 'add' ? `These ${sessions} sessions are added to ${whose} plan; nothing is removed. `
              : mode === 'weeks' ? `This replaces ${whose} plan for the ${weeks.length} week${weeks.length === 1 ? '' : 's'} it covers. `
              : mode === 'fill' ? `These go on the free days of ${whose} plan; days that already have sessions keep them. `
              : `This replaces ${whose} plan from ${short(server.first_day)} on. `}
            {server.garmin_synced > 0 && mode !== 'add' ? `Workouts already on Garmin are swapped at the next sync. ` : ''}
            You can undo it for 7 days.
          </div>
        )}
        {(saveError || error) && <ErrorState compact message={(saveError || error)!} />}

        {(server.warnings.length > 0 || flagged > 0) && (
          <Card className="px-4 py-3">
            <p className="flex items-center gap-1.5 text-[0.7647rem] font-medium text-(--warning-text)"><TriangleAlert className="size-4" />
              {flagged ? `${flagged} session${flagged === 1 ? '' : 's'} to check (highlighted)` : `Check ${server.warning_count === 1 ? 'this' : `these ${server.warning_count}`}`}
            </p>
            {server.warnings.length > 0 && <>
              <ul className="mt-1.5 flex flex-col gap-1 text-[0.7059rem] leading-snug text-(--text-secondary)">
                {(allWarn ? server.warnings : server.warnings.filter((w) => !/^Row /.test(w)).slice(0, 3)).map((w, i) => <li key={i}>{w}</li>)}
              </ul>
              {!allWarn && server.warnings.length > 3 && <button type="button" className="mt-1 min-h-11 text-[0.7059rem] font-medium text-(--accent)" onClick={() => setAllWarn(true)}>Show all</button>}
            </>}
          </Card>
        )}

        {issues.length > 0 && (
          <Card>
            <p className="flex items-center gap-1.5 border-b border-(--border) px-4 py-2.5 text-[0.7647rem] font-medium text-(--danger)">
              <CircleAlert className="size-4" /> {issues.length} row{issues.length === 1 ? '' : 's'} couldn't be read
            </p>
            <ul className="divide-y divide-(--border)">
              {issues.map((is, i) => (
                <li key={i} className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[0.7647rem] text-(--text)">{is.title || is.notes || `Row ${is.line ?? i + 1}`}</span>
                      <span className="block text-[0.6471rem] text-(--text-muted)">{is.reason}{is.date ? ` · ${is.date}` : ''}</span>
                    </span>
                    <Button variant="default" className="h-11 px-3 text-[0.7059rem]" onClick={() => setEditing({ issue: i })}>Fix</Button>
                    <button type="button" aria-label="Dismiss" className="hit-44 rounded p-1 text-(--text-muted)"
                      onClick={() => change({ issues: issues.filter((_, k) => k !== i) })}><X className="size-4" /></button>
                  </div>
                  {editing && 'issue' in editing && editing.issue === i && (
                    <SessionEditor initial={fromIssue(is, firstMonday)} onCancel={() => setEditing(null)}
                      onSave={(r) => { change({ rows: [...rows, { ...r, key: `r${++seq}` }], issues: issues.filter((_, k) => k !== i) }); setEditing(null) }} />
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )}

        {weeks.map((w, wi) => {
          const d = diff.get(w.start)
          const notes = weekNotes(w, weeks[wi - 1], server.has_plan && (mode === 'fill' || mode === 'add') ? clashes : new Set(), mode)
          return (
            <Card key={w.start}>
              <div id={`rw-${w.start}`} className="flex items-center gap-2 border-b border-(--border) px-4 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
                    Week {wi + 1} · {w.count} session{w.count === 1 ? '' : 's'} · {fmtDuration(w.minutes) || 'rest'}
                  </span>
                  <span className="block text-[0.7059rem] text-(--text-muted)">{short(w.start)} – {short(addDays(w.start, 6))}</span>
                </span>
                {server.has_plan && d && (d.added + d.changed + d.removed > 0) && (
                  <span className="shrink-0 text-[0.6471rem]">
                    {d.added ? <span className="text-(--accent)">+{d.added} </span> : null}
                    {d.changed ? <span className="text-(--warning-text)">~{d.changed} </span> : null}
                    {d.removed ? <span className="text-(--danger)">−{d.removed}</span> : null}
                  </span>
                )}
              </div>
              {notes.length > 0 && (
                <ul className="flex flex-col gap-0.5 border-b border-(--border) bg-(--warning-text)/5 px-4 py-1.5">
                  {notes.map((n, i) => (
                    <li key={i} className={cn('flex items-center gap-1.5 text-[0.6471rem] leading-snug', n.bad ? 'text-(--danger)' : 'text-(--warning-text)')}>
                      <TriangleAlert className="size-3 shrink-0" /> {n.text}
                    </li>
                  ))}
                </ul>
              )}
              <ul className="divide-y divide-(--border)">
                {w.rows.map((r) => {
                  const Icon = SPORT_ICON[r.sport] ?? SPORT_ICON.other
                  const open = !!editing && 'key' in editing && editing.key === r.key
                  return (
                    <li key={r.key} className={cn(r.warn && !open && 'bg-(--warning-text)/5')}>
                      <button type="button" onClick={() => setEditing(open ? null : { key: r.key })} aria-expanded={open}
                        className="flex min-h-12 w-full items-center gap-2 px-4 py-1.5 text-left active:bg-(--bg-inset)">
                        <span className="w-12 shrink-0 text-[0.7059rem] text-(--text-muted)">{fmtDay(r.date, { weekday: 'short' })} {fmtDay(r.date, { day: 'numeric' })}</span>
                        <Icon className="size-3.5 shrink-0 text-(--accent)" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[0.7647rem] text-(--text)">{r.title || SPORT_LABEL[r.sport]}</span>
                          {r.warn && <span className="flex items-center gap-1 truncate text-[0.6471rem] text-(--warning-text)"><TriangleAlert className="size-3 shrink-0" /> {r.warn}</span>}
                        </span>
                        <span className="shrink-0 text-[0.7059rem] text-(--text-muted)">{r.minutes ? fmtDuration(r.minutes) : r.kind === 'race' ? 'Race' : ''}</span>
                        <Pencil className="size-3.5 shrink-0 text-(--text-muted)" />
                      </button>
                      {open && (
                        <SessionEditor initial={r} onCancel={() => setEditing(null)}
                          onDelete={() => { updateRow(r.key, null); setEditing(null) }}
                          onDuplicate={() => { updateRow(r.key, {}, true); setEditing(null) }}
                          onSave={(x) => { updateRow(r.key, x); setEditing(null) }} />
                      )}
                    </li>
                  )
                })}
                {!w.rows.length && <li className="px-4 py-2.5 text-[0.7059rem] text-(--text-muted)">No sessions this week</li>}
              </ul>
              {editing && 'add' in editing && editing.add === w.start ? (
                <div className="border-t border-(--border)">
                  <SessionEditor initial={{ date: w.start < today ? today : w.start, sport: 'run', title: '', minutes: 45, notes: '', intensity: 'easy' }}
                    onCancel={() => setEditing(null)}
                    onSave={(x) => { change({ rows: [...rows, { ...x, key: `r${++seq}` }] }); setEditing(null) }} />
                </div>
              ) : (
                <button type="button" onClick={() => setEditing({ add: w.start })}
                  className="flex min-h-11 w-full items-center gap-1.5 border-t border-(--border) px-4 text-[0.7059rem] font-medium text-(--accent)">
                  <Plus className="size-3.5" /> Add a session
                </button>
              )}
            </Card>
          )
        })}

        {past.length > 0 && (
          <div className="px-1 text-[0.7059rem] leading-snug text-(--text-muted)">
            <button type="button" className="flex min-h-11 items-center gap-1" onClick={() => setShowPast((x) => !x)} aria-expanded={showPast}>
              {past.length} session{past.length === 1 ? ' is' : 's are'} before today and left out {showPast ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
            </button>
            {showPast && <p>Shift the dates above to bring them into the plan. First one: {short(past.map((r) => r.date).sort()[0]!)}.</p>}
          </div>
        )}
      </>}
    </Screen>
  )
}

function fromIssue(is: ImportIssue, monday: string): DraftRow {
  const sport = (SPORTS as string[]).includes(is.sport.toLowerCase()) ? is.sport.toLowerCase() as Sport : 'run'
  return {
    date: /^\d{4}-\d{2}-\d{2}$/.test(is.date) ? is.date : monday, sport, title: is.title.slice(0, 60),
    minutes: is.minutes ?? 45, notes: is.notes, intensity: 'easy',
  }
}

function VolumeBars({ weeks, max }: { weeks: { start: string; minutes: number }[]; max: number }) {
  return (
    <div className="px-1" aria-label="Hours per week">
      <div className="flex h-16 items-end gap-[3px]">
        {weeks.map((w, i) => (
          <button key={w.start} type="button" title={`Week ${i + 1}: ${fmtDuration(w.minutes) || 'rest'}`}
            aria-label={`Week ${i + 1}, ${fmtDuration(w.minutes) || 'rest'}`}
            onClick={() => document.getElementById(`rw-${w.start}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            className="flex h-full min-w-0 flex-1 items-end">
            <span className="block w-full rounded-t-sm bg-(--accent) opacity-80" style={{ height: `${Math.max(4, (w.minutes / max) * 100)}%` }} />
          </button>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[0.6471rem] text-(--text-muted)">
        <span>Week 1</span><span>Hours per week · peak {fmtDuration(max)}</span><span>Week {weeks.length}</span>
      </div>
    </div>
  )
}

function Count({ n, label, tone }: { n: number; label: string; tone: 'add' | 'change' | 'remove' }) {
  return (
    <span className={cn('rounded-full border px-2.5 py-1 text-[0.7059rem] font-medium',
      n === 0 ? 'border-(--border) text-(--text-muted)' : tone === 'remove' ? 'border-(--danger)/30 text-(--danger)' : tone === 'add' ? 'border-(--accent)/30 text-(--accent)' : 'border-(--warning-text)/30 text-(--warning-text)')}>
      {tone === 'add' ? '+' : tone === 'remove' ? '−' : '~'}{n} {label}
    </span>
  )
}

function SessionEditor({ initial, onSave, onCancel, onDelete, onDuplicate }: {
  initial: DraftRow; onSave: (r: DraftRow) => void; onCancel: () => void; onDelete?: () => void; onDuplicate?: () => void
}) {
  const [s, setS] = useState({ sport: initial.sport, title: initial.title, minutes: initial.minutes, date: initial.date, intensity: intensityOf(initial) })
  const isRace = s.intensity === 'race'
  const save = () => {
    const sportChanged = s.sport !== initial.sport
    const itChanged = s.intensity !== intensityOf(initial)
    const out: DraftRow = {
      ...initial, sport: s.sport, title: s.title.trim(), date: s.date, minutes: isRace ? null : s.minutes, warn: null,
      steps: sportChanged ? null : initial.steps,
    }
    if (sportChanged || itChanged || !initial.kind) { out.intensity = s.intensity; out.kind = null }
    onSave(out)
  }
  return (
    <div className="mx-3 mb-2.5 mt-1 flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-elevated) p-3">
      <ChipRow>
        {SPORTS.map((sp) => <Chip key={sp} selected={s.sport === sp} onClick={() => setS({ ...s, sport: sp })}>{SPORT_LABEL[sp]}</Chip>)}
      </ChipRow>
      <input className={inputCls} placeholder="Title (e.g. Hill repeats)" maxLength={60} aria-label="Title"
        value={s.title} onChange={(e) => setS({ ...s, title: e.target.value })} />
      <div className="flex gap-2">
        <input type="date" className={cn(inputCls, 'h-11 flex-1')} aria-label="Date" value={s.date}
          onChange={(e) => e.target.value && setS({ ...s, date: e.target.value })} />
      </div>
      <ChipRow>
        {QUICK.map((it) => <Chip key={it} selected={s.intensity === it} onClick={() => setS({ ...s, intensity: it })}>{INTENSITY_LABEL[it]}</Chip>)}
      </ChipRow>
      {!isRace && <NumberStepper label="minutes" value={s.minutes} onChange={(v) => setS({ ...s, minutes: v })} step={5} min={10} max={600} suffix="min" />}
      <div className="flex gap-2">
        {onDelete && <Button variant="ghostDanger" className="h-11 px-3" aria-label="Delete session" onClick={onDelete}><Trash2 className="size-4" /></Button>}
        {onDuplicate && <Button variant="ghost" className="h-11 px-3" aria-label="Duplicate session" onClick={onDuplicate}><Copy className="size-4" /></Button>}
        <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" className="h-11 flex-1 gap-1 text-[0.7647rem]" disabled={!isRace && !s.minutes} onClick={save}>
          <Check className="size-3.5" /> {onDelete ? 'Save' : 'Add'}
        </Button>
      </div>
    </div>
  )
}

/** Coach: keep this draft as "my template" (weeks 1, 2, 3…; reuse it for any athlete). */
function SaveDraftTemplate({ api, id, name, flush }: { api: ImportApi; id: string; name: string | null; flush: () => Promise<boolean> }) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState(name ?? '')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  async function save() {
    setBusy(true); setError(null)
    try {
      if (!(await flush())) throw new Error('Fix the draft first: it couldn\'t be saved.')
      const r = await api.saveMine(label.trim(), { import_id: id }); setDone(r.template.label); setOpen(false)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  if (done) return <p className="flex items-center gap-1.5 px-1 text-[0.7647rem] text-(--accent)" role="status"><Check className="size-4" /> Saved “{done}” to your templates.</p>
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="-mt-2 flex min-h-11 items-center gap-1.5 self-start px-1 text-[0.7647rem] font-medium text-(--accent)">
        <BookmarkPlus className="size-4" /> Save as my template
      </button>
    )
  }
  return (
    <Card className="flex flex-col gap-2 px-4 py-3">
      <p className="text-[0.7647rem] leading-snug text-(--text-muted)">Kept as weeks 1, 2, 3… so you can start it on any date for any of your athletes.</p>
      <input aria-label="Template name" className={inputCls} placeholder="Template name" maxLength={60} value={label} onChange={(e) => setLabel(e.target.value)} autoFocus />
      {error && <p className="text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
      <div className="flex gap-2">
        <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={() => setOpen(false)}>Cancel</Button>
        <Button variant="primary" className="h-11 flex-1 text-[0.7647rem]" loading={busy} disabled={!label.trim()} onClick={() => void save()}>Save template</Button>
      </div>
    </Card>
  )
}
