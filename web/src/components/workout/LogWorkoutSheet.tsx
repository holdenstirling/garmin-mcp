// "Log workout": the athlete writes down a workout they did (lib/worklog.ts, server worklog.py).
// Lifting gets exercises with sets (reps and weight, numeric keyboards, + / - set, add an
// exercise, "Last time" from their history); any other sport gets time, distance and effort.
// Prefilled from the planned session when opened from one, so logging a planned lift is
// mostly typing the weights. Saving marks that session done.
import { useEffect, useMemo, useState } from 'react'
import { Minus, Plus, Trash2 } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  LOG_SPORTS, deleteLogged, exerciseHistory, logSportOf, logWorkout, setLine, updateLogged, worklogChanged,
  type LogExercise, type LogRequest, type LogSet, type LogSport, type WeightUnit,
} from '@/lib/worklog'

const KM_PER_MI = 1.609344
const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const firstReps = (r: string | number | null | undefined): string => {
  if (r == null || r === '') return ''
  return String(r).trim()
}

type ExDraft = { name: string; sets: { reps: string; weight: string }[] }

function fromPlan(req: LogRequest): ExDraft[] {
  return (req.session?.exercises ?? []).slice(0, 30).map((e) => ({
    name: e.name,
    sets: Array.from({ length: Math.min(20, Math.max(1, Number(e.sets) || 3)) }, () => ({ reps: firstReps(e.reps), weight: '' })),
  }))
}

export function LogWorkoutSheet({ req, imperial, onClose, onToast }: {
  req: LogRequest; imperial: boolean; onClose: () => void; onToast?: (m: string) => void
}) {
  const unit: WeightUnit = imperial ? 'lb' : 'kg'
  const edit = req.edit
  const [sport, setSport] = useState<LogSport>(edit?.sport ?? (req.session ? logSportOf(req.session.sport) : 'strength'))
  const [date, setDate] = useState(edit?.date ?? req.session?.date ?? req.date ?? todayIso())
  const [title, setTitle] = useState(edit?.title ?? req.session?.title ?? '')
  const [minutes, setMinutes] = useState(edit?.minutes != null ? String(edit.minutes) : req.session?.minutes ? String(req.session.minutes) : '')
  const [dist, setDist] = useState(edit?.km != null ? String(Math.round((imperial ? edit.km / KM_PER_MI : edit.km) * 100) / 100) : '')
  const [rpe, setRpe] = useState<number | null>(edit?.rpe ?? null)
  const [notes, setNotes] = useState(edit?.notes ?? '')
  const [exs, setExs] = useState<ExDraft[]>(() => edit
    ? edit.exercises.map((e) => ({ name: e.name, sets: e.sets.map((s) => ({ reps: s.reps, weight: s.weight != null ? String(s.weight) : '' })) }))
    : fromPlan(req))
  const [last, setLast] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const lifting = sport === 'strength'
  const maxDate = todayIso()

  // "Last time" for each named exercise (newest log first).
  const names = useMemo(() => [...new Set(exs.map((e) => e.name.trim().toLowerCase()).filter(Boolean))], [exs])
  useEffect(() => {
    let live = true
    for (const n of names) {
      if (n in last) continue
      exerciseHistory(n).then((r) => {
        const prev = r.items.find((h) => h.workout_id !== edit?.id)
        if (live) setLast((m) => ({ ...m, [n]: prev ? `Last time: ${prev.line}` : '' }))
      }, () => { if (live) setLast((m) => ({ ...m, [n]: '' })) })
    }
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [names.join('|')])

  const putEx = (i: number, f: (e: ExDraft) => ExDraft) => setExs((xs) => xs.map((e, j) => (j === i ? f(e) : e)))
  const addSet = (i: number) => putEx(i, (e) => (e.sets.length >= 20 ? e : { ...e, sets: [...e.sets, { ...(e.sets[e.sets.length - 1] ?? { reps: '', weight: '' }) }] }))
  const dropSet = (i: number) => putEx(i, (e) => ({ ...e, sets: e.sets.slice(0, -1) }))

  async function save() {
    setErr(null)
    const exercises: LogExercise[] = lifting
      ? exs.filter((e) => e.name.trim()).map((e) => ({
        name: e.name.trim(),
        sets: e.sets.filter((s) => s.reps.trim()).map((s): LogSet => ({ reps: s.reps.trim(), weight: s.weight.trim() ? Number(s.weight) : null, unit })),
      })).filter((e) => e.sets.length)
      : []
    if (lifting && !exercises.length && !minutes.trim()) { setErr('Add at least one exercise with a set, or how long it took.'); return }
    if (!lifting && !minutes.trim() && !dist.trim()) { setErr('Add how long it took or how far you went.'); return }
    const km = dist.trim() ? Math.round((imperial ? Number(dist) * KM_PER_MI : Number(dist)) * 100) / 100 : null
    const body = {
      sport, date, title: title.trim(), minutes: minutes.trim() ? Number(minutes) : null, km, rpe, notes: notes.trim(),
      session_id: edit?.session_id ?? req.session?.id ?? null, exercises,
    }
    setBusy('save')
    try {
      if (edit) await updateLogged(edit.id, body)
      else await logWorkout(body)
      worklogChanged()
      onToast?.(edit ? 'Workout updated' : 'Workout logged. Nice work.')
      onClose()
    } catch (e) { setErr((e as Error).message || "Couldn't save just now.") } finally { setBusy(null) }
  }

  async function remove() {
    if (!edit) return
    setBusy('delete')
    try { await deleteLogged(edit.id); worklogChanged(); onToast?.('Removed'); onClose() }
    catch (e) { setErr((e as Error).message || "Couldn't remove it just now.") } finally { setBusy(null) }
  }

  const input = 'h-11 w-full rounded-lg border border-(--border-strong) bg-(--bg-surface) px-3 text-body text-(--text)'
  return (
    <Sheet title={edit ? 'Edit workout' : 'Log workout'} onClose={onClose} portal bodyClassName="gap-5"
      footer={
        <div className="flex gap-2">
          {edit && (
            confirmDelete
              ? <Button variant="default" className="h-12 px-4 text-body text-(--danger)" loading={busy === 'delete'} onClick={() => void remove()}>Remove it</Button>
              : <Button variant="ghost" className="h-12 px-3 text-body" aria-label="Remove this workout" onClick={() => setConfirmDelete(true)}><Trash2 className="size-5" aria-hidden /></Button>
          )}
          <Button variant="primary" className="h-12 flex-1 text-body" loading={busy === 'save'} disabled={busy !== null} onClick={() => void save()}>
            {edit ? 'Save changes' : 'Save workout'}
          </Button>
        </div>
      }>
      {!req.session && !edit && (
        <div role="group" aria-label="Sport" className="flex flex-wrap gap-2">
          {LOG_SPORTS.map(([id, label]) => (
            <button key={id} type="button" aria-pressed={sport === id} onClick={() => setSport(id)}
              className={cn('min-h-11 rounded-full border px-4 text-body font-medium',
                sport === id ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border) bg-(--bg-surface) text-(--text)')}>
              {label}
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-small text-(--text-secondary)">
          Day
          <input type="date" className={input} value={date} max={maxDate} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-small text-(--text-secondary)">
          Minutes
          <input inputMode="numeric" pattern="[0-9]*" className={input} value={minutes} placeholder="45"
            onChange={(e) => setMinutes(e.target.value.replace(/[^0-9]/g, '').slice(0, 4))} />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-small text-(--text-secondary)">
        Name <span className="sr-only">(optional)</span>
        <input className={input} value={title} maxLength={80} placeholder={lifting ? 'Lower body' : 'Easy run'} onChange={(e) => setTitle(e.target.value)} />
      </label>

      {!lifting && sport !== 'other' && (
        <label className="flex flex-col gap-1 text-small text-(--text-secondary)">
          Distance ({imperial ? 'mi' : 'km'})
          <input inputMode="decimal" className={input} value={dist} placeholder={imperial ? '3.1' : '5'}
            onChange={(e) => setDist(e.target.value.replace(/[^0-9.]/g, '').slice(0, 6))} />
        </label>
      )}

      {lifting && (
        <section aria-label="Exercises" className="flex flex-col gap-3">
          {exs.map((e, i) => {
            const hint = last[e.name.trim().toLowerCase()]
            return (
              <div key={i} className="flex flex-col gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
                <div className="flex items-center gap-2">
                  <input aria-label={`Exercise ${i + 1} name`} className={cn(input, 'font-semibold')} value={e.name} placeholder="Back squat" maxLength={60}
                    onChange={(ev) => putEx(i, (x) => ({ ...x, name: ev.target.value }))} />
                  <button type="button" aria-label={`Remove ${e.name || 'this exercise'}`} onClick={() => setExs((xs) => xs.filter((_, j) => j !== i))}
                    className="flex size-11 shrink-0 items-center justify-center rounded-lg text-(--text-muted) active:bg-(--bg-inset)">
                    <Trash2 className="size-5" aria-hidden />
                  </button>
                </div>
                {hint && <p className="m-0 text-meta text-(--text-muted)">{hint}</p>}
                <div className="grid grid-cols-[2.5rem_1fr_1fr] items-center gap-2 text-meta text-(--text-muted)">
                  <span>Set</span><span>Reps</span><span>Weight ({unit})</span>
                  {e.sets.map((s, k) => (
                    <SetRow key={k} n={k + 1} s={s} input={input}
                      onChange={(ns) => putEx(i, (x) => ({ ...x, sets: x.sets.map((y, m) => (m === k ? ns : y)) }))} />
                  ))}
                </div>
                <div className="flex gap-2">
                  <Button variant="default" className="h-11 flex-1 gap-1.5 text-body" disabled={e.sets.length >= 20} onClick={() => addSet(i)}>
                    <Plus className="size-5" aria-hidden /> Add set
                  </Button>
                  <Button variant="ghost" className="h-11 gap-1.5 px-3 text-body" disabled={e.sets.length <= 1} onClick={() => dropSet(i)} aria-label="Remove the last set">
                    <Minus className="size-5" aria-hidden />
                  </Button>
                </div>
                {e.sets.some((s) => s.reps) && (
                  <p className="m-0 text-meta text-(--text-secondary)">{setLine(e.sets.filter((s) => s.reps).map((s) => ({ reps: s.reps, weight: s.weight ? Number(s.weight) : null, unit })))}</p>
                )}
              </div>
            )
          })}
          <Button variant="default" className="h-11 gap-1.5 text-body" disabled={exs.length >= 30}
            onClick={() => setExs((xs) => [...xs, { name: '', sets: [{ reps: '', weight: '' }, { reps: '', weight: '' }, { reps: '', weight: '' }] }])}>
            <Plus className="size-5" aria-hidden /> Add exercise
          </Button>
        </section>
      )}

      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-2 text-small text-(--text-secondary)">How hard was it? {rpe ? <span className="font-semibold text-(--text)">{rpe} of 10</span> : <span>(optional)</span>}</legend>
        <div className="grid grid-cols-10 gap-1">
          {Array.from({ length: 10 }, (_, k) => k + 1).map((n) => (
            <button key={n} type="button" aria-pressed={rpe === n} aria-label={`Effort ${n} of 10`} onClick={() => setRpe(rpe === n ? null : n)}
              className={cn('h-11 rounded-lg border text-body font-semibold tabular-nums',
                rpe === n ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border) bg-(--bg-surface) text-(--text)')}>
              {n}
            </button>
          ))}
        </div>
      </fieldset>

      <label className="flex flex-col gap-1 text-small text-(--text-secondary)">
        Notes <span className="sr-only">(optional)</span>
        <textarea className="min-h-20 w-full rounded-lg border border-(--border-strong) bg-(--bg-surface) p-3 text-body text-(--text)" value={notes} maxLength={600}
          placeholder="Felt strong on squats" onChange={(e) => setNotes(e.target.value)} />
      </label>

      <p className="m-0 text-meta leading-snug text-(--text-muted)">Friends only ever see the sport and time, never your sets or weights.</p>
      {err && <p role="alert" className="m-0 text-small text-(--danger)">{err}</p>}
    </Sheet>
  )
}

function SetRow({ n, s, input, onChange }: { n: number; s: { reps: string; weight: string }; input: string; onChange: (s: { reps: string; weight: string }) => void }) {
  return (
    <>
      <span className="text-center text-body font-semibold tabular-nums text-(--text)">{n}</span>
      <input aria-label={`Set ${n} reps`} inputMode="numeric" className={input} value={s.reps} placeholder="8"
        onChange={(e) => onChange({ ...s, reps: e.target.value.slice(0, 24) })} />
      <input aria-label={`Set ${n} weight`} inputMode="decimal" className={input} value={s.weight} placeholder="0"
        onChange={(e) => onChange({ ...s, weight: e.target.value.replace(/[^0-9.]/g, '').slice(0, 6) })} />
    </>
  )
}
