// Loading a whole plan: "Add a plan" (AddPlan.tsx: drop/paste/pick files, any format, or a
// template) or build it week by week in Rabbit. Every path ends in the editable review
// (PlanReview.tsx), then Apply, with undo for 7 days. Used by a coach on an athlete's Plan tab
// and by the athlete from their plan.
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowDown, ArrowUp, CalendarRange, Check, ClipboardPaste, Copy, Download,
  LayoutGrid, Pencil, Plus, Repeat, Trash2, Undo2, Upload,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import { fmtDuration } from '@/lib/format'
import type { Sport } from '@/lib/api'
import type { BuiltPlan, PlanApi } from '@/lib/plan'
import {
  INTENSITY_LABEL, addDays, mondayOf, type Draft, type GridRow, type ImportApi, type ImportStatus, type Intensity,
  type Preview, type TemplateRow,
} from '@/lib/planimport'
import { Card, Chip, ChipRow, Field, NumberStepper, Screen, inputCls } from './ui'
import { SPORT_ICON, SPORT_LABEL, fmtDay } from './PlanParts'
import { AddPlanFlow } from './AddPlan'
import { PlanReview } from './PlanReview'

type Who = 'coach' | 'athlete'
type Open = { kind: 'grid' } | { kind: 'add' } | { kind: 'preview'; preview: Preview } | null

const short = (d: string) => fmtDay(d, { month: 'short', day: 'numeric' })

/** The coach's Plan tab for one athlete (or the athlete's own "load a plan" entry). */
export function PlanImportHub({ api, plans, who, athleteName, onOpenPlan, onChanged }: {
  api: ImportApi; plans: PlanApi; who: Who; athleteName: string
  onOpenPlan: () => void; onChanged?: () => void
}) {
  const [status, setStatus] = useState<ImportStatus | null>(null)
  const [plan, setPlan] = useState<BuiltPlan | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Open>(null)
  const load = useCallback(() => {
    setError(null)
    Promise.all([api.status(), plans.getPlan()]).then(([s, p]) => { setStatus(s); setPlan(p.plan) },
      (e) => setError((e as Error).message))
  }, [api, plans])
  useEffect(load, [load])
  const first = athleteName.split(' ')[0] || 'your athlete'

  if (error) return <ErrorState message={error} onRetry={load} />
  if (!status || plan === undefined) return <RabbitLoader className="py-16" label="Opening the plan" cycle={['Opening the plan…', 'Counting weeks…']} />

  const lastWeek = plan?.weeks[plan.weeks.length - 1]
  return (
    <>
      {status.undo && <UndoBanner api={api} status={status} who={who} onDone={() => { load(); onChanged?.() }} />}
      {plan ? (
        <Card className="px-4 py-3.5">
          <p className="text-[0.9412rem] font-medium text-(--text)">{plan.weeks.length} weeks · {short(plan.first_day)} – {lastWeek ? short(addDays(lastWeek.start, 6)) : ''}</p>
          <p className="mt-0.5 text-[0.7647rem] text-(--text-muted)">
            {plan.origin ? `Loaded by ${plan.origin.kind === 'coach' ? plan.origin.by_name : `${first} (from a file)`}` : 'Built in Rabbit'}
            {plan.current_week ? ` · week ${plan.current_week} now` : ''}
          </p>
          <Button variant="primary" className="mt-3 h-11 w-full text-[0.8235rem]" onClick={onOpenPlan}>Open plan</Button>
        </Card>
      ) : (
        <div className="px-1">
          <p className="font-display text-[1.2941rem] leading-tight text-(--brand)">{who === 'coach' ? `Load ${first}'s plan` : 'Load your plan'}</p>
          <p className="mt-1 text-[0.7647rem] leading-snug text-(--text-muted)">Pick how you have it. You'll see every week before anything changes, and you can undo for 7 days.</p>
        </div>
      )}
      {!status.can_edit ? (
        <p className="px-1 text-[0.7647rem] text-(--text-muted)">View only: {first} hasn't given you edit access to the plan.</p>
      ) : (
        <section className="flex flex-col gap-2">
          {plan && <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Add to or replace the plan</h3>}
          <BigOption icon={<Upload />} title="Add a plan" big={!plan}
            text="Drop a file (spreadsheet, TrainingPeaks, PDF, photo, Zwift), paste text or pick a template."
            onClick={() => setOpen({ kind: 'add' })} />
          <BigOption icon={<LayoutGrid />} title="Build week by week" big={false}
            text="Quick-add sessions, copy weeks, start from a base, build or recovery week."
            onClick={() => setOpen({ kind: 'grid' })} />
        </section>
      )}
      {plan && (
        <div className="flex flex-wrap items-center gap-x-3 px-1 text-[0.7059rem] text-(--text-muted)">
          <span>Download the plan:</span>
          <a className="inline-flex min-h-11 items-center gap-1 font-medium text-(--accent)" href={api.exportUrl('csv')} download><Download className="size-3.5" /> CSV</a>
          <a className="inline-flex min-h-11 items-center gap-1 font-medium text-(--accent)" href={api.exportUrl('ics')} download><CalendarRange className="size-3.5" /> Calendar (.ics)</a>
        </div>
      )}
      {open?.kind === 'grid' && <GridBuilder api={api} onClose={() => setOpen(null)} onPreview={(p) => setOpen({ kind: 'preview', preview: p })} />}
      {open?.kind === 'add' && (
        <AddPlanFlow api={api} status={status} who={who} athleteName={first} hasPlan={!!plan}
          onClose={() => setOpen(null)} onApplied={() => { setOpen(null); load(); onChanged?.() }} />
      )}
      {open?.kind === 'preview' && (
        <PlanReview api={api} initial={open.preview} who={who} athleteName={first}
          onClose={() => setOpen(null)} onApplied={() => { setOpen(null); load(); onChanged?.() }} />
      )}
    </>
  )
}

function BigOption({ icon, title, text, onClick, big }: { icon: React.ReactNode; title: string; text: string; onClick: () => void; big?: boolean }) {
  return (
    <button type="button" onClick={onClick}
      className={cn('flex w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 text-left active:bg-(--bg-inset)',
        big ? 'min-h-20 py-4' : 'min-h-14 py-2.5')}>
      <span className={cn('flex shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent) [&>svg]:size-5', big ? 'size-11' : 'size-9')}>{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.9412rem] font-medium text-(--text)">{title}</span>
        <span className="block text-[0.7059rem] leading-snug text-(--text-muted)">{text}</span>
      </span>
    </button>
  )
}

function UndoBanner({ api, status, who, onDone }: { api: ImportApi; status: ImportStatus; who: Who; onDone: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const u = status.undo!
  const until = new Date(u.until * 1000).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
  const what = u.restores === 'previous plan' ? 'puts the previous plan back' : 'removes this plan'
  async function run() {
    setBusy(true); setError(null)
    try { await api.undo(); onDone() } catch (e) { setError((e as Error).message) } finally { setBusy(false); setConfirm(false) }
  }
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5">
      <div className="flex items-center gap-3">
        <Undo2 className="size-4 shrink-0 text-(--accent)" />
        <p className="min-w-0 flex-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
          {who === 'coach' && u.by_name ? `${u.by_name} loaded this plan.` : 'This plan was loaded from outside the builder.'} Undo {what} (until {until}).
        </p>
        {!confirm && <Button variant="default" className="h-11 px-3 text-[0.7647rem]" onClick={() => setConfirm(true)}>Undo</Button>}
      </div>
      {confirm && (
        <div className="flex gap-2">
          <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={() => setConfirm(false)}>Keep it</Button>
          <Button variant="destructive" className="h-11 flex-1 text-[0.7647rem]" loading={busy} onClick={() => void run()}>Undo the import</Button>
        </div>
      )}
      {error && <p className="text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
    </div>
  )
}

// ------------------------------------------------------------------ grid --
type GSession = { sport: Sport; title: string; minutes: number | null; intensity: Intensity; notes: string }
type GWeek = { key: string; days: GSession[][] }  // days[0] = Monday
let keySeq = 0
const newWeek = (days?: GSession[][]): GWeek => ({ key: `w${++keySeq}`, days: days ?? Array.from({ length: 7 }, () => []) })
const cloneDays = (w: GWeek) => w.days.map((d) => d.map((s) => ({ ...s })))
const weekMinutes = (w: GWeek) => w.days.flat().reduce((a, s) => a + (s.minutes ?? 0), 0)
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const QUICK_INTENSITY: Intensity[] = ['easy', 'long', 'tempo', 'threshold', 'intervals', 'recovery', 'race']

function fromTemplate(rows: TemplateRow[]): GSession[][] {
  const days: GSession[][] = Array.from({ length: 7 }, () => [])
  for (const r of rows) days[r.weekday]?.push({ sport: r.sport, title: r.title, minutes: r.minutes, intensity: r.intensity, notes: '' })
  return days
}

function GridBuilder({ api, onClose, onPreview }: { api: ImportApi; onClose: () => void; onPreview: (p: Preview) => void }) {
  const [draft, setDraft] = useState<Draft | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [start, setStart] = useState('')
  const [weeks, setWeeks] = useState<GWeek[]>([])
  const [clip, setClip] = useState<GSession[][] | null>(null)
  const [editing, setEditing] = useState<{ w: number; d: number; i: number | null } | null>(null)
  const [repeat, setRepeat] = useState<Record<string, number>>({})
  const [busy, setBusy] = useState(false)
  const [closing, setClosing] = useState(false)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  useEffect(() => {
    api.draft().then((d) => {
      setDraft(d)
      if (d.rows.length) {
        // Edit the current plan: group its sessions into Monday weeks.
        const mon = mondayOf(d.rows[0]!.date)
        const byWeek: GSession[][][] = []
        for (const r of d.rows) {
          const off = Math.round((new Date(`${r.date}T12:00:00`).getTime() - new Date(`${mon}T12:00:00`).getTime()) / 86_400_000)
          const wi = Math.floor(off / 7), di = off % 7
          while (byWeek.length <= wi) byWeek.push(Array.from({ length: 7 }, () => []))
          byWeek[wi]![di]!.push({ sport: r.sport, title: r.title, minutes: r.minutes, intensity: r.intensity, notes: r.notes ?? '' })
        }
        setStart(mon); setWeeks(byWeek.slice(0, 60).map((days) => newWeek(days)))
      } else {
        setStart(d.next_monday); setWeeks([newWeek()])
      }
    }, (e) => setError((e as Error).message))
  }, [api])

  const update = (fn: (ws: GWeek[]) => GWeek[]) => setWeeks((ws) => fn(ws.map((w) => ({ ...w, days: w.days.map((d) => [...d]) }))))
  const rows = useMemo(() => {
    const out: GridRow[] = []
    weeks.forEach((w, wi) => w.days.forEach((d, di) => d.forEach((s) => out.push({
      date: addDays(start, wi * 7 + di), sport: s.sport, title: s.title, minutes: s.minutes, intensity: s.intensity, notes: s.notes,
    }))))
    return out
  }, [weeks, start])

  async function preview() {
    setBusy(true); setError(null)
    try { onPreview((await api.rows(rows)).preview) } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const footer = (
    <>
      <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" disabled={weeks.length >= 60}
        onClick={() => update((ws) => [...ws, newWeek()])}><Plus className="size-4" /> Add week</Button>
      <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy} disabled={!rows.length} onClick={() => void preview()}>Preview</Button>
    </>
  )
  return (
    <Screen title="Build in Rabbit" subtitle={`${weeks.length} week${weeks.length === 1 ? '' : 's'} · ${rows.length} sessions`} onBack={close} onClose={close} closing={closing} footer={draft ? footer : undefined}>
      {!draft && !error && <RabbitLoader className="py-16" label="Getting the grid ready" cycle={['Getting the grid ready…', 'Sizing weeks to their hours…']} />}
      {error && <ErrorState compact message={error} />}
      {draft && <>
        <Card>
          <Field label="Week 1 starts" hint="Weeks run Monday to Sunday. Days before today are left out when you apply.">
            <input type="date" className={inputCls} value={start} onChange={(e) => e.target.value && setStart(mondayOf(e.target.value))} />
          </Field>
        </Card>
        <p className="-mt-2 px-1 text-[0.7059rem] leading-snug text-(--text-muted)">
          Templates are sized to about {draft.templates.hours} h a week (their usual hours).
          <InfoTip label="Templates" text="Base: mostly easy with one long session per sport. Build: adds threshold work, about 10% more time. Recovery: about two thirds of the time, all easy." />
        </p>
        {weeks.map((w, wi) => {
          const ws = addDays(start, wi * 7)
          const n = repeat[w.key] ?? 1
          return (
            <Card key={w.key}>
              <div className="flex items-center gap-2 border-b border-(--border) px-4 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Week {wi + 1} · {fmtDuration(weekMinutes(w)) || 'empty'}</span>
                  <span className="block text-[0.7059rem] text-(--text-muted)">{short(ws)} – {short(addDays(ws, 6))}</span>
                </span>
                <IconBtn label="Move week up" disabled={wi === 0} onClick={() => update((xs) => { [xs[wi - 1], xs[wi]] = [xs[wi]!, xs[wi - 1]!]; return xs })}><ArrowUp /></IconBtn>
                <IconBtn label="Move week down" disabled={wi === weeks.length - 1} onClick={() => update((xs) => { [xs[wi], xs[wi + 1]] = [xs[wi + 1]!, xs[wi]!]; return xs })}><ArrowDown /></IconBtn>
                <IconBtn label="Delete week" disabled={weeks.length === 1} onClick={() => update((xs) => xs.filter((_, i) => i !== wi))}><Trash2 /></IconBtn>
              </div>
              <div className="flex flex-wrap items-center gap-1.5 border-b border-(--border) px-3 py-2">
                {(['base', 'build', 'recovery'] as const).map((t) => (
                  <Chip key={t} onClick={() => update((xs) => { xs[wi] = { ...xs[wi]!, days: fromTemplate(draft.templates.weeks[t]) }; return xs })}>
                    {t === 'base' ? 'Base week' : t === 'build' ? 'Build week' : 'Recovery week'}
                  </Chip>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-1.5 border-b border-(--border) px-3 py-2">
                <Button variant="ghost" className="h-11 gap-1 px-2 text-[0.7059rem]" onClick={() => setClip(cloneDays(w))}><Copy className="size-3.5" /> Copy</Button>
                <Button variant="ghost" className="h-11 gap-1 px-2 text-[0.7059rem]" disabled={!clip}
                  onClick={() => clip && update((xs) => { xs[wi] = { ...xs[wi]!, days: clip.map((d) => d.map((s) => ({ ...s }))) }; return xs })}><ClipboardPaste className="size-3.5" /> Paste</Button>
                <span className="ml-auto flex items-center gap-1">
                  <button type="button" className="hit-44 rounded px-1.5 text-[0.7647rem] text-(--text-muted)" aria-label="Fewer repeats"
                    onClick={() => setRepeat((r) => ({ ...r, [w.key]: Math.max(1, n - 1) }))}>−</button>
                  <Button variant="default" className="h-11 gap-1 px-2.5 text-[0.7059rem]" disabled={weeks.length + n > 60}
                    onClick={() => update((xs) => [...xs.slice(0, wi + 1), ...Array.from({ length: n }, () => newWeek(cloneDays(w))), ...xs.slice(wi + 1)])}>
                    <Repeat className="size-3.5" /> Repeat ×{n}
                  </Button>
                  <button type="button" className="hit-44 rounded px-1.5 text-[0.7647rem] text-(--text-muted)" aria-label="More repeats"
                    onClick={() => setRepeat((r) => ({ ...r, [w.key]: Math.min(12, n + 1) }))}>+</button>
                </span>
              </div>
              <div className="divide-y divide-(--border)">
                {w.days.map((d, di) => (
                  <div key={di} className="px-3 py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="w-10 shrink-0 text-center leading-tight">
                        <span className="block text-[0.6471rem] font-semibold uppercase text-(--text-muted)">{DAY_NAMES[di]}</span>
                        <span className="block text-[0.7059rem] text-(--text-secondary)">{fmtDay(addDays(ws, di), { day: 'numeric' })}</span>
                      </span>
                      <div className="flex min-w-0 flex-1 flex-wrap gap-1.5 py-1">
                        {d.map((s, i) => {
                          const Icon = SPORT_ICON[s.sport]
                          return (
                            <button key={i} type="button" onClick={() => setEditing({ w: wi, d: di, i })}
                              className={cn('flex min-h-11 items-center gap-1.5 rounded-lg border px-2 text-left text-[0.7059rem]',
                                editing?.w === wi && editing.d === di && editing.i === i ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-elevated)')}>
                              <Icon className="size-3.5 shrink-0 text-(--accent)" />
                              <span className="max-w-[9rem] truncate text-(--text)">{s.title || SPORT_LABEL[s.sport]}</span>
                              {s.minutes ? <span className="text-(--text-muted)">{fmtDuration(s.minutes)}</span> : null}
                            </button>
                          )
                        })}
                        {!d.length && <span className="self-center text-[0.7059rem] text-(--text-muted)">Rest</span>}
                      </div>
                      {d.length < 4 && (
                        <button type="button" aria-label={`Add a session on ${DAY_NAMES[di]}`} onClick={() => setEditing({ w: wi, d: di, i: null })}
                          className="hit-44 flex size-7 shrink-0 items-center justify-center rounded-full border border-dashed border-(--border-strong) text-(--text-muted)">
                          <Plus className="size-3.5" />
                        </button>
                      )}
                    </div>
                    {editing?.w === wi && editing.d === di && (
                      <QuickAdd key={`${editing.i}`} sports={draft.sports} initial={editing.i != null ? d[editing.i] : undefined}
                        onCancel={() => setEditing(null)}
                        onDelete={editing.i != null ? () => { const i = editing.i!; update((xs) => { xs[wi]!.days[di] = xs[wi]!.days[di]!.filter((_, k) => k !== i); return xs }); setEditing(null) } : undefined}
                        onSave={(s) => {
                          const i = editing.i
                          update((xs) => { const day = xs[wi]!.days[di]!; if (i == null) day.push(s); else day[i] = s; return xs })
                          setEditing(null)
                        }} />
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )
        })}
      </>}
    </Screen>
  )
}

function IconBtn({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} disabled={disabled} onClick={onClick}
      className="hit-44 rounded p-1.5 text-(--text-muted) disabled:opacity-30 [&>svg]:size-4">{children}</button>
  )
}

function QuickAdd({ sports, initial, onSave, onCancel, onDelete }: {
  sports: Sport[]; initial?: GSession; onSave: (s: GSession) => void; onCancel: () => void; onDelete?: () => void
}) {
  const [s, setS] = useState<GSession>(initial ?? { sport: 'run', title: '', minutes: 45, intensity: 'easy', notes: '' })
  const isRace = s.intensity === 'race'
  return (
    <div className="mt-1.5 mb-2 flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-elevated) p-3">
      <ChipRow>
        {sports.map((sp) => <Chip key={sp} selected={s.sport === sp} onClick={() => setS({ ...s, sport: sp })}>{SPORT_LABEL[sp]}</Chip>)}
      </ChipRow>
      <input className={inputCls} placeholder={`Title (e.g. ${s.sport === 'run' ? 'Hill repeats' : s.sport === 'bike' ? 'Sweet spot 3x12' : 'Easy session'})`}
        maxLength={60} value={s.title} onChange={(e) => setS({ ...s, title: e.target.value })} />
      <ChipRow>
        {QUICK_INTENSITY.map((it) => <Chip key={it} selected={s.intensity === it} onClick={() => setS({ ...s, intensity: it })}>{INTENSITY_LABEL[it]}</Chip>)}
      </ChipRow>
      {!isRace && <NumberStepper label="minutes" value={s.minutes} onChange={(v) => setS({ ...s, minutes: v })} step={5} min={10} max={600} suffix="min" />}
      <input className={inputCls} placeholder="Notes (optional): intervals, targets, cues" maxLength={400}
        value={s.notes} onChange={(e) => setS({ ...s, notes: e.target.value })} />
      <div className="flex gap-2">
        {onDelete && <Button variant="ghostDanger" className="h-11 px-3 text-[0.7647rem]" onClick={onDelete}><Trash2 className="size-4" /></Button>}
        <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" className="h-11 flex-1 gap-1 text-[0.7647rem]" disabled={!isRace && !s.minutes}
          onClick={() => onSave({ ...s, title: s.title.trim(), minutes: isRace ? null : s.minutes })}>
          {initial ? <><Pencil className="size-3.5" /> Save</> : <><Check className="size-3.5" /> Add</>}
        </Button>
      </div>
    </div>
  )
}

/** The athlete's own entry point (from the plan screen): Add plan -> review -> apply. */
export function OwnPlanImport({ api, status, hasPlan, onClose, onApplied }: {
  api: ImportApi; status: ImportStatus; hasPlan: boolean; onClose: () => void; onApplied: () => void
}) {
  return <AddPlanFlow api={api} status={status} who="athlete" athleteName="" hasPlan={hasPlan} onClose={onClose} onApplied={onApplied} />
}
