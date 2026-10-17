// Bottom sheet for one plan session: see its structure, change sport/type/length/day,
// rename it, add notes, or delete it. In add mode it creates a new session on a day.
import { useEffect, useState } from 'react'
import { CalendarDays, MessageCircle, Mic, Send, Trash2, Zap } from 'lucide-react'
import { CheckinChips, VoiceCheckIn } from '@/components/checkin/VoiceCheckIn'
import { listCheckins, type Checkin } from '@/lib/checkins'
import { Button } from '@/components/ui/button'
import type { Sport } from '@/lib/api'
import { KIND_LABEL, ZONE_LABEL, fmtMin, stepText, type PlanSession, type Step } from '@/lib/plan'
import { Card, Choice, Field, NumberStepper, areaCls, inputCls } from './ui'
import { SPORT_LABEL, fmtDay, todayStr } from './PlanParts'
import { Sheet } from '@/components/ui/Sheet'
import type { CalNote } from '@/lib/plancal'
import { useDraft } from '@/lib/drafts'
import { DraftRestored, useUnsavedGuard } from '@/components/ui/UnsavedGuard'

export type SessionDraft = { date: string; sport: Sport; kind: string; minutes: number; title: string; detail: string; time: string }

const SPORTS: Sport[] = ['swim', 'bike', 'run', 'brick', 'strength', 'rest']

export function SessionSheet({ session, date, kinds, sports, raceDate, today = todayStr(), onSave, onDelete, onAsk, onMessage, messageLabel, readOnly, checkIn, onOpenWorkout, onClose, onDismissed, closing, note, meta, onMove }: {
  session: PlanSession | null          // null = add mode
  date: string
  kinds: Record<string, string[]>
  sports: Sport[]
  raceDate: string
  /** the athlete's date from the server (defaults to the device's) */
  today?: string
  onSave: (d: SessionDraft, changed: Partial<SessionDraft>) => Promise<void>
  onDelete?: () => Promise<void>
  onAsk?: () => void
  onMessage?: () => void
  messageLabel?: string
  readOnly?: boolean
  /** athlete's own past/today session: offer a voice check-in ("How did it feel?") */
  checkIn?: boolean
  /** today's session: open the pre-workout screen */
  onOpenWorkout?: () => void
  onClose: () => void; onDismissed: () => void; closing: boolean
  /** the session's "why + how" (plan calendar) and its distance/pace line */
  note?: CalNote | null
  meta?: string
  /** open the calendar's Move sheet (pick a day / swap days) */
  onMove?: () => void
}) {
  const adding = !session
  const initial: SessionDraft = {
    date,
    sport: session?.sport ?? sports[0] ?? 'run',
    kind: session?.kind ?? 'easy',
    minutes: session?.minutes ?? (session?.legs.reduce((a, l) => a + l.minutes, 0) || 45),
    title: session?.title ?? '',
    detail: session?.detail ?? '',
    time: session?.time ?? '',
  }
  // Unsaved edits are kept per session (or new-session day) on this device until saved.
  const [d, setD, draft] = useDraft<SessionDraft>(readOnly ? null : `session.${session?.id ?? `new.${date}`}`, initial,
    { label: session ? `changes to ${session.title}` : 'new session' })
  const guard = useUnsavedGuard(draft.dirty, draft.discard)
  const close = guard.wrap(onClose)
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const isRace = session?.kind === 'race'
  const past = date < today
  const sportKinds = (kinds[d.sport] ?? []).filter((k) => k !== 'race')
  const locked = isRace || past || !!readOnly
  const choices = [...new Set([...SPORTS.filter((s) => s === 'brick' ? sports.length > 1 : s === 'strength' || s === 'rest' || sports.includes(s)), ...(session ? [session.sport] : [])])]

  const set = (p: Partial<SessionDraft>) => setD((x) => {
    const n = { ...x, ...p }
    if (p.sport && !(kinds[p.sport] ?? []).includes(n.kind)) n.kind = (kinds[p.sport] ?? ['easy'])[0] ?? 'easy'
    return n
  })

  const changed = Object.fromEntries(
    (Object.keys(d) as (keyof SessionDraft)[]).filter((k) => d[k] !== initial[k]).map((k) => [k, d[k]]),
  ) as Partial<SessionDraft>

  async function save() {
    setBusy('save'); setError(null)
    try { await onSave(d, changed); draft.clear(); onClose() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }
  async function remove() {
    if (!onDelete) return
    setBusy('delete'); setError(null)
    try { await onDelete(); draft.discard(); onClose() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }

  const steps: { label?: string; steps: Step[] }[] = session
    ? session.legs.length
      ? session.legs.map((l) => ({ label: `${SPORT_LABEL[l.sport]} · ${fmtMin(l.minutes)}`, steps: l.steps }))
      : session.steps.length ? [{ steps: session.steps }] : []
    : []

  const [confirmDelete, setConfirmDelete] = useState(false)
  const section = 'font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted) px-1 -mb-2'
  return (
    <Sheet title={session ? session.title : 'Add a session'} className="modal--tall" footer={!locked ? (
        // Pinned under the form so Save is always in reach (also with the keyboard open).
        <div className="flex gap-2">
          <Button variant="default" className="h-11 px-5 text-[0.8235rem]" disabled={!!busy} onClick={close}>Cancel</Button>
          <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy === 'save'}
            disabled={!adding && Object.keys(changed).length === 0} onClick={() => void save()}>
            {adding ? 'Add session' : Object.keys(changed).length === 0 ? 'No changes yet' : 'Save changes'}
          </Button>
        </div>
      ) : undefined} onClose={close} closing={closing} onDismissed={onDismissed} extra={guard.dialog} dismissible={!busy}
      bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      {draft.restored && <DraftRestored onDiscard={draft.discard} />}
      <p className="px-1 text-[0.7647rem] text-(--text-muted)">
        {fmtDay(d.date, { weekday: 'long', month: 'long', day: 'numeric' })}{d.time ? ` at ${d.time}` : ''}
        {session?.synced && ' · on your Garmin calendar'}
      </p>
      {meta && <p className="-mt-3 px-1 font-mono text-[0.7647rem] tabular-nums text-(--text-secondary)">{meta}</p>}

      {locked ? (
        <p className="px-1 text-[0.7647rem] text-(--text-muted)">
          {readOnly ? 'You can view this plan but not change it.' : isRace ? 'Race day stays put. Change the race date by rebuilding the plan.' : 'This day has passed, so it can\'t be changed.'}
        </p>
      ) : (
        <>
          <h3 className={section}>What</h3>
          <Card>
            <Field label="Sport">
              <Choice value={d.sport} options={choices.map((s) => [s, SPORT_LABEL[s]] as [Sport, string])} onChange={(v) => v && set({ sport: v })} />
            </Field>
            {sportKinds.length > 1 && (
              <Field label="Type" className="border-t border-(--border)">
                <Choice value={d.kind} options={sportKinds.map((k) => [k, KIND_LABEL[k] ?? k] as [string, string])} onChange={(v) => v && set({ kind: v })} />
              </Field>
            )}
            <Field label="Name" className="border-t border-(--border)" hint={adding ? 'Leave blank for a name like "Easy run".' : undefined}>
              <input className={inputCls} maxLength={60} value={d.title} placeholder={`${KIND_LABEL[d.kind] ?? ''} ${SPORT_LABEL[d.sport].toLowerCase()}`.trim()}
                onChange={(e) => set({ title: e.target.value })} />
            </Field>
          </Card>

          <h3 className={section}>When</h3>
          <Card>
            <Field label="Day">
              <input type="date" className={inputCls} value={d.date} min={today} max={raceDate}
                onChange={(e) => e.target.value && set({ date: e.target.value })} />
            </Field>
            {d.sport !== 'rest' && (
              <Field label="Start time" className="border-t border-(--border)"
                hint="Optional. Puts it at that time in your day and your calendar.">
                <div className="flex items-center gap-2">
                  <input type="time" className={inputCls} value={d.time ?? ''} step={300} aria-label="Start time"
                    onChange={(e) => set({ time: e.target.value })} />
                  {d.time && <Button variant="ghost" className="h-11 shrink-0 px-3 text-[0.7647rem]" onClick={() => set({ time: '' })}>Clear</Button>}
                </div>
              </Field>
            )}
            {onMove && session && !isRace && (
              <div className="border-t border-(--border) px-4 py-2">
                <Button variant="ghost" className="h-11 gap-1.5 px-0 text-[0.7647rem] text-(--accent)" onClick={onMove}>
                  <CalendarDays className="size-4" /> Move or swap with another day
                </Button>
              </div>
            )}
          </Card>

          {d.sport !== 'rest' && (
            <>
              <h3 className={section}>How long</h3>
              <Card>
                <Field label="Length" hint={d.sport === 'swim' ? 'Swims sync to Garmin by distance, worked out from this time and your swim pace.' : 'Rabbit rebuilds the steps to fit.'}>
                  <NumberStepper label="minutes" value={d.minutes} min={10} max={600} step={5} suffix="min"
                    typical={[20, 30, 45, 60, 75, 90, 120]} onChange={(v) => set({ minutes: v ?? 10 })} />
                </Field>
              </Card>
            </>
          )}
        </>
      )}

      {(steps.length > 0 || note || session?.fuel || (session?.exercises?.length ?? 0) > 0 || !adding) && <h3 className={section}>Details</h3>}
      {note && (
        <Card>
          <Field label={note.source === 'coach' ? 'Coach notes' : 'Why + how'}>
            <div className="flex flex-col gap-1 text-[0.8235rem] leading-snug">
              <p className="text-(--text)">{note.why}</p>
              {note.how && <p className="text-(--text-secondary)">{note.how}</p>}
              {note.cues && <p className="text-(--text-muted)">{note.cues}</p>}
            </div>
          </Field>
        </Card>
      )}
      {steps.length > 0 && (
        <Card>
          <Field label="The workout" hint={session?.synced ? 'Changes go to your watch on the next sync.' : undefined}>
            <div className="flex flex-col gap-2">
              {steps.map((g, i) => (
                <div key={i} className="flex flex-col gap-1">
                  {g.label && <span className="text-[0.7059rem] font-medium text-(--text-secondary)">{g.label}</span>}
                  <ol className="flex flex-col gap-1">
                    {g.steps.map((s, j) => <StepItem key={j} s={s} />)}
                  </ol>
                </div>
              ))}
            </div>
          </Field>
        </Card>
      )}
      {session && (session.exercises?.length ?? 0) > 0 && (
        <Card>
          <Field label={session.kind === 'mobility' ? 'Mobility' : 'Exercises'}>
            <ul className="flex flex-col gap-1.5">
              {session.exercises!.map((e) => (
                <li key={e.name} className="flex gap-2 text-[0.8235rem]"><span className="flex-1 text-(--text)">{e.name}</span><span className="text-(--text-muted)">{e.dose}</span></li>
              ))}
            </ul>
          </Field>
          {(session.prehab?.length ?? 0) > 0 && (
            <Field label="Prehab for your injury notes" className="border-t border-(--border)"
              hint="General prehab, not a diagnosis. If pain is sharp, getting worse or changes how you move, see a physio.">
              <ul className="flex flex-col gap-1.5">
                {session.prehab!.map((e) => (
                  <li key={e.name} className="flex gap-2 text-[0.8235rem]"><span className="flex-1 text-(--text)">{e.name}</span><span className="text-(--text-muted)">{e.dose}</span></li>
                ))}
              </ul>
            </Field>
          )}
        </Card>
      )}
      {session?.fuel && (
        <Card>
          <Field label="Fueling">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[0.8235rem] text-(--text)">
              <span><b className="font-display text-[1.1rem]">{session.fuel.carbs_g_per_h}</b> g carbs/h</span>
              {session.fuel.total_carbs_g != null && <span className="text-(--text-muted)">≈{session.fuel.total_carbs_g} g total</span>}
              {session.fuel.fluid_ml_per_h && <span className="text-(--text-muted)">{session.fuel.fluid_ml_per_h} ml fluid/h</span>}
              {session.fuel.sodium_mg_per_h && <span className="text-(--text-muted)">{session.fuel.sodium_mg_per_h} mg sodium/h</span>}
            </div>
            <p className="text-[0.7059rem] leading-snug text-(--text-muted)">{session.fuel.note}</p>
          </Field>
        </Card>
      )}
      {session?.detail && locked && steps.length === 0 && (
        <p className="px-1 text-[0.8235rem] text-(--text-secondary)">{session.detail}</p>
      )}
      {!locked && !adding && (
        <Card>
          <Field label="Notes">
            <textarea className={areaCls} maxLength={400} value={d.detail} placeholder="Anything to remember for this one"
              onChange={(e) => set({ detail: e.target.value })} />
          </Field>
        </Card>
      )}

      {checkIn && session && session.sport !== 'rest' && <SessionCheckIn session={session} />}

      {(onOpenWorkout && session && date === today && session.sport !== 'rest' && session.kind !== 'race') || onAsk || onMessage ? (
        <div className="flex flex-wrap gap-2">
          {onOpenWorkout && session && date === today && session.sport !== 'rest' && session.kind !== 'race' && (
            <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={onOpenWorkout}>
              <Zap className="size-4" /> Today's workout
            </Button>
          )}
          {onAsk && (
            <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={onAsk}>
              <MessageCircle className="size-4" /> Ask Rabbit
            </Button>
          )}
          {onMessage && (
            <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={onMessage}>
              <Send className="size-4" /> {messageLabel ?? 'Message'}
            </Button>
          )}
        </div>
      ) : null}

      {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}

      {onDelete && !locked && (
        <div className="mt-2 border-t border-(--border) pt-4">
          {confirmDelete ? (
            <div className="flex flex-col gap-2 rounded-xl border border-(--danger)/40 px-3.5 py-3" role="alertdialog" aria-label="Delete this session?">
              <p className="text-[0.8235rem] text-(--text)">Delete {session?.title ?? 'this session'}? {session?.synced ? 'It comes off your watch on the next sync.' : ''}</p>
              <div className="flex gap-2">
                <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={() => setConfirmDelete(false)}>Keep it</Button>
                <Button variant="default" className="h-11 flex-1 text-[0.7647rem] text-(--danger)" loading={busy === 'delete'} onClick={() => void remove()}>Delete</Button>
              </div>
            </div>
          ) : (
            <Button variant="ghost" className="h-11 w-full gap-1.5 text-[0.7647rem] text-(--danger)" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="size-4" /> Delete this session
            </Button>
          )}
        </div>
      )}
    </Sheet>
  )
}

/** "How did it feel?": the latest check-in for this session, and the voice check-in. */
function SessionCheckIn({ session }: { session: PlanSession }) {
  const [latest, setLatest] = useState<Checkin | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let live = true
    listCheckins(60, session.id).then((r) => { if (live) setLatest(r.checkins[0] ?? null) }, () => {})
    return () => { live = false }
  }, [session.id])
  return (
    <Card>
      <Field label="How did it feel?">
        {latest && <CheckinChips c={latest} />}
        <Button variant="default" className="h-10 gap-1.5 self-start px-3.5 text-[0.7647rem]" onClick={() => setOpen(true)}>
          <Mic className="size-4" /> {latest ? 'Check in again' : 'How did it feel?'}
        </Button>
      </Field>
      <VoiceCheckIn open={open} onClose={() => setOpen(false)} sessionId={session.id} title={session.title}
        onSaved={(c) => setLatest(c)} />
    </Card>
  )
}

export function StepItem({ s }: { s: Step }) {
  if (s.type === 'repeat') {
    return (
      <li className="rounded-lg border border-(--border) px-3 py-2">
        <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">{s.reps} times</span>
        <ol className="mt-1 flex flex-col gap-1">{s.steps.map((x, i) => <StepItem key={i} s={x} />)}</ol>
      </li>
    )
  }
  const tone = s.type === 'work' ? 'bg-(--accent)' : s.type === 'steady' ? 'bg-(--accent)/60' : 'bg-(--bg-elevated)'
  return (
    <li className="flex items-center gap-2.5 text-[0.8235rem]">
      <span className={`h-5 w-1 shrink-0 rounded-full ${tone}`} />
      <span className="flex-1 text-(--text)">{stepText(s)}</span>
      <span className="text-[0.7059rem] text-(--text-muted)">{ZONE_LABEL[s.zone] ?? ''}</span>
    </li>
  )
}
