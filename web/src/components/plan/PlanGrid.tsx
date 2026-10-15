// "Build in Rabbit": a week-by-week grid for a coach (or the athlete) to type a plan in:
// quick-add sessions per day, copy/paste/repeat weeks, base/build/recovery week presets sized
// to the athlete. Preview goes to the same review as every other way in (PlanReview).
import { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Check, ClipboardPaste, Copy, Pencil, Plus, Repeat, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import { fmtDuration } from '@/lib/format'
import type { Sport } from '@/lib/api'
import {
  INTENSITY_LABEL, addDays, mondayOf, type Draft, type GridRow, type ImportApi, type Intensity, type Preview, type TemplateRow,
} from '@/lib/planimport'
import { Card, Chip, ChipRow, Field, NumberStepper, Screen, inputCls } from './ui'
import { SPORT_ICON, SPORT_LABEL, fmtDay } from './PlanParts'

const short = (d: string) => fmtDay(d, { month: 'short', day: 'numeric' })

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

export function GridBuilder({ api, onClose, onPreview }: { api: ImportApi; onClose: () => void; onPreview: (p: Preview) => void }) {
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
      <input className={inputCls} aria-label="Session title" placeholder={`Title (e.g. ${s.sport === 'run' ? 'Hill repeats' : s.sport === 'bike' ? 'Sweet spot 3x12' : 'Easy session'})`}
        maxLength={60} value={s.title} onChange={(e) => setS({ ...s, title: e.target.value })} />
      <ChipRow>
        {QUICK_INTENSITY.map((it) => <Chip key={it} selected={s.intensity === it} onClick={() => setS({ ...s, intensity: it })}>{INTENSITY_LABEL[it]}</Chip>)}
      </ChipRow>
      {!isRace && <NumberStepper label="minutes" value={s.minutes} onChange={(v) => setS({ ...s, minutes: v })} step={5} min={10} max={600} suffix="min" />}
      <input className={inputCls} aria-label="Notes" placeholder="Notes (optional): intervals, targets, cues" maxLength={400}
        value={s.notes} onChange={(e) => setS({ ...s, notes: e.target.value })} />
      <div className="flex gap-2">
        {onDelete && <Button variant="ghostDanger" className="h-11 px-3 text-[0.7647rem]" aria-label="Delete session" onClick={onDelete}><Trash2 className="size-4" /></Button>}
        <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" className="h-11 flex-1 gap-1 text-[0.7647rem]" disabled={!isRace && !s.minutes}
          onClick={() => onSave({ ...s, title: s.title.trim(), minutes: isRace ? null : s.minutes })}>
          {initial ? <><Pencil className="size-3.5" /> Save</> : <><Check className="size-3.5" /> Add</>}
        </Button>
      </div>
    </div>
  )
}
