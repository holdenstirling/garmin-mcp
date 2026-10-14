// The review step of "Add plan": every session grouped by week, quick to fix before anything
// changes. Tap a session to edit sport/title/time/date/intensity, delete or duplicate it;
// rows Rabbit wasn't sure about are highlighted; rows it couldn't read can be fixed or
// dismissed; shift all dates or pick the start week; choose replace / add / replace only these
// weeks. Edits save to the server-side draft (debounced), so closing never loses them.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronUp, CircleAlert, Copy, Pencil, Plus, Trash2, TriangleAlert, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { cn } from '@/lib/utils'
import { fmtDuration } from '@/lib/format'
import type { Sport } from '@/lib/api'
import {
  INTENSITY_LABEL, addDays, daysBetween, mondayOf, shiftRows, type DraftRow, type ImportApi, type ImportIssue, type ImportMode,
  type Intensity, type Preview,
} from '@/lib/planimport'
import { Card, Chip, ChipRow, Field, NumberStepper, Screen, inputCls } from './ui'
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
  { id: 'replace', label: 'Replace my plan', text: 'Everything from the first day on becomes this plan.' },
  { id: 'add', label: 'Add to my plan', text: 'Keeps every session you have and adds these.' },
  { id: 'weeks', label: 'Replace only these weeks', text: 'Swaps the weeks this covers; other weeks stay.' },
]

export function PlanReview({ api, initial, who, athleteName, onClose, onApplied }: {
  api: ImportApi; initial: Preview; who: Who; athleteName: string; onClose: () => void; onApplied: () => void
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
      await api.apply(server.id); setDone(true)
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
    const out: { start: string; rows: Row[]; minutes: number }[] = []
    for (let s = starts[0]!; s <= starts[starts.length - 1]!; s = addDays(s, 7)) {
      const rs = m.get(s) ?? []
      out.push({ start: s, rows: rs, minutes: rs.reduce((a, r) => a + (r.sport === 'rest' ? 0 : r.minutes ?? 0), 0) })
    }
    return out
  }, [active])
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
  const modeLabel = !server.has_plan ? 'Load plan' : mode === 'add' ? 'Add to plan' : mode === 'weeks' ? 'Replace weeks' : 'Replace plan'
  const footer = done ? (
    <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" onClick={onApplied}>Done</Button>
  ) : confirm ? (
    <>
      <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={() => setConfirm(false)}>Back</Button>
      <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy} onClick={() => void apply()}>{modeLabel}</Button>
    </>
  ) : (
    <>
      <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={close}>Later</Button>
      <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" disabled={!sessions || !!saveError} onClick={() => setConfirm(true)}>Apply</Button>
    </>
  )

  return (
    <Screen title="Review" subtitle={[server.name, server.source].filter(Boolean).join(' · ')} onBack={close} onClose={close} closing={closing} footer={footer}>
      {done ? (
        <div className="flex flex-col items-center gap-2 py-10 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)"><Check className="size-6" /></span>
          <p className="font-display text-[1.2941rem] text-(--brand)">Plan loaded</p>
          <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-muted)">
            {who === 'coach' ? `${athleteName} gets a message with the summary. ` : ''}You can undo it for 7 days from the Plan tab.
            {server.garmin_synced > 0 ? ' Garmin updates on the next sync.' : ''}
          </p>
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
          </Card>
        )}

        <Card className="px-4 py-3">
          <div className="flex items-end gap-3">
            <Field label="Starts the week of" className="min-w-0 flex-1">
              <input type="date" className={inputCls} value={firstMonday}
                onChange={(e) => { if (e.target.value) change({ rows: shiftRows(rows, daysBetween(firstMonday, mondayOf(e.target.value))) }) }} />
            </Field>
          </div>
          <div className="mt-2 flex items-center gap-1.5">
            <span className="mr-auto text-[0.7059rem] text-(--text-muted)">Shift all dates</span>
            {([[-7, '−1 wk'], [-1, '−1 day'], [1, '+1 day'], [7, '+1 wk']] as const).map(([n, l]) => (
              <Button key={n} variant="default" className="h-11 px-2.5 text-[0.7059rem]" onClick={() => change({ rows: shiftRows(rows, n) })}>{l}</Button>
            ))}
          </div>
        </Card>

        {confirm && (
          <div className="rounded-xl border border-(--warning-text)/30 bg-(--bg-surface) px-3.5 py-3 text-[0.7647rem] leading-snug text-(--text)">
            {!server.has_plan ? `This becomes ${whose} plan. `
              : mode === 'add' ? `These ${sessions} sessions are added to ${whose} plan; nothing is removed. `
              : mode === 'weeks' ? `This replaces ${whose} plan for the ${weeks.length} week${weeks.length === 1 ? '' : 's'} it covers. `
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
          return (
            <Card key={w.start}>
              <div id={`rw-${w.start}`} className="flex items-center gap-2 border-b border-(--border) px-4 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
                    Week {wi + 1} · {fmtDuration(w.minutes) || 'rest'}
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
