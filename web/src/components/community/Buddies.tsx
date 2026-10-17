// Local → People → "Training buddies" (server: buddies.py). Opt-in: a set-up card until you turn
// it on; then matches near you at a similar easy pace and usual times, each explained in plain
// chips, with "Say hi" (opens a direct message: a request unless you're already connected) and
// "Not now". Others only ever see your pace band, usual times, race, note, city and a rounded
// distance: never your exact location, heart rate or single workouts.
import { useCallback, useEffect, useState } from 'react'
import { MessageCircle, Pause, Pencil, Play, Users, X } from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Sheet } from '@/components/ui/Sheet'
import { IconTile } from '@/components/ui/brand'
import { DurationInput } from '@/components/ui/DurationInput'
import { Field, MultiChoice, areaCls, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { formatDuration, parseDuration } from '@/lib/duration'
import { OPEN_DM_EVENT } from '@/lib/dm'
import {
  BUDDY_SPORTS, WEEKDAYS, WHEN, bandText, deleteBuddies, getBuddies, getBuddyMatches, hideBuddy, saveBuddies, sayHi, slotsText,
  type Band, type BuddyMatch, type BuddyProfile, type BuddySport, type BuddyState,
} from '@/lib/buddies'
import { PersonAvatar } from './Feed'

const KM_PER_MI = 1.609344
const LOADING = ['Looking for people your pace…', 'Lacing up…']

export function BuddiesSection({ imperial }: { imperial: boolean }) {
  const [state, setState] = useState<BuddyState | null>(null)
  const [matches, setMatches] = useState<BuddyMatch[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [hi, setHi] = useState<BuddyMatch | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const s = await getBuddies()
      setState(s); setError(null)
      if (s.profile && !s.profile.paused) setMatches((await getBuddyMatches()).matches)
      else setMatches([])
    } catch (e) { setError((e as Error).message) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function setPaused(paused: boolean) {
    if (!state?.profile) return
    setBusy('pause')
    try { await saveBuddies({ ...state.profile, paused }); await load() } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }
  async function notNow(m: BuddyMatch) {
    setMatches((xs) => xs?.filter((x) => x.person.id !== m.person.id) ?? null)
    try { await hideBuddy(m.person.id) } catch { /* it comes back on the next load */ }
  }

  if (!state) return error ? <ErrorState compact message={error} onRetry={() => void load()} /> : <RabbitLoader className="py-6" label="Loading training buddies" cycle={LOADING} />
  const p = state.profile
  return (
    <section aria-label="Training buddies" className="flex flex-col gap-1.5">
      <h2 className="px-4 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Training buddies</h2>
      {error && <ErrorState compact message={error} onRetry={() => void load()} />}
      {!p ? (
        <div className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
          <div className="flex items-start gap-3">
            <IconTile><Users className="size-5" /></IconTile>
            <div className="min-w-0">
              <p className="text-[0.8824rem] font-semibold text-(--text)">Find people your pace near you</p>
              <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
                Rabbit matches you with runners and riders {state.area.city ? `around ${state.area.city}` : 'near you'} who train at a similar easy pace and at the same times of day.
              </p>
            </div>
          </div>
          <p className="text-[0.7059rem] leading-snug text-(--text-muted)">
            Off until you turn it on. Others see your pace range, usual times, city and about how far away you are. Never your exact location, heart rate or workouts.
          </p>
          <Button variant="primary" className="h-11" onClick={() => setEditing(true)}>Find training buddies</Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5">
            <p className="min-w-0 flex-1 text-[0.7647rem] text-(--text-secondary)">
              {p.paused ? 'Paused: you don\'t show up for anyone.' : `You're visible to people your pace ${state.area.city ? `around ${state.area.city}` : 'nearby'} · within ${state.area.radius_mi} mi.`}
            </p>
            <Button variant="ghost" className="h-11 gap-1 px-2 text-[0.7647rem]" loading={busy === 'pause'} onClick={() => void setPaused(!p.paused)}
              aria-label={p.paused ? 'Resume training buddies' : 'Pause training buddies'}>
              {p.paused ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />}{p.paused ? 'Resume' : 'Pause'}
            </Button>
            <Button variant="ghost" className="h-11 w-11 p-0" aria-label="Edit my buddy profile" onClick={() => setEditing(true)}>
              <Pencil className="size-4" aria-hidden />
            </Button>
          </div>
          {!p.paused && matches === null && <RabbitLoader className="py-6" label="Finding matches" cycle={LOADING} />}
          {!p.paused && matches?.length === 0 && (
            <p className="rounded-xl border border-dashed border-(--border-strong) px-4 py-3 text-[0.7647rem] text-(--text-muted)">
              No matches yet. As more people near you turn this on, they'll show up here. A wider area (Change, at the top of Local) finds more.
            </p>
          )}
          {!p.paused && matches?.map((m) => (
            <MatchCard key={m.person.id} m={m} imperial={imperial} onHi={() => setHi(m)} onNotNow={() => void notNow(m)} />
          ))}
        </div>
      )}
      {editing && (
        <BuddyEditor state={state} imperial={imperial} onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); void load() }} />
      )}
      {hi && <SayHiSheet m={hi} onClose={() => setHi(null)} />}
    </section>
  )
}

function MatchCard({ m, imperial, onHi, onNotNow }: { m: BuddyMatch; imperial: boolean; onHi: () => void; onNotNow: () => void }) {
  const band = bandText(m.sport, m.pace, imperial)
  return (
    <article className="flex flex-col gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) p-4" aria-label={`Training buddy match: ${m.person.name}`}>
      <div className="flex items-center gap-3">
        <PersonAvatar u={m.person} size={40} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[0.8824rem] font-semibold text-(--text)">{m.person.name}</p>
          <p className="truncate text-[0.7059rem] text-(--text-muted)">
            {m.following && m.follows_you ? 'Friends' : m.following ? 'You follow them' : m.follows_you ? 'Follows you' : m.city}
          </p>
        </div>
      </div>
      <ul className="flex flex-wrap gap-1.5" aria-label="Why you match">
        {m.chips.map((c) => <li key={c} className="rounded-full bg-(--accent-subtle) px-2.5 py-1 text-[0.7059rem] font-medium text-(--accent)">{c}</li>)}
      </ul>
      <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
        {[band && `Easy ${band}`, m.slots.length ? slotsText(m.slots.slice(0, 4)) : '', m.race && `Training for ${m.race}`].filter(Boolean).join(' · ')}
      </p>
      {m.note && <p className="text-[0.7647rem] italic leading-snug text-(--text)">“{m.note}”</p>}
      <div className="flex gap-2">
        <Button variant="primary" className="h-11 flex-1 gap-1.5" onClick={onHi}><MessageCircle className="size-4" aria-hidden />Say hi</Button>
        <Button variant="default" className="h-11 gap-1.5 px-4" onClick={onNotNow} aria-label={`Not now: hide ${m.person.name}`}><X className="size-4" aria-hidden />Not now</Button>
      </div>
    </article>
  )
}

function SayHiSheet({ m, onClose }: { m: BuddyMatch; onClose: () => void }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function send() {
    setBusy(true); setErr(null)
    try {
      const r = await sayHi(m.person.id, text.trim() || undefined)
      onClose()
      try { window.dispatchEvent(new CustomEvent(OPEN_DM_EVENT, { detail: { id: r.conv.id } })) } catch { /* ignore */ }
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Sheet title={`Say hi to ${m.person.name}`} onClose={onClose} portal
      footer={
        <div className="flex gap-2 border-t border-(--border) bg-(--bg) px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          <Button variant="primary" className="h-11 flex-1" loading={busy} onClick={() => void send()}>Send</Button>
        </div>
      }>
      <div className="flex flex-col gap-3 p-4">
        <Field label="Message (optional)" hint={m.following && m.follows_you ? 'You\'re friends, so this goes straight to their messages.' : 'They\'ll get it as a message request they can accept or decline.'}>
          <textarea className={areaCls} maxLength={400} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={`Hi ${m.person.name}! Rabbit matched us as training buddies. Want to train together sometime?`} />
        </Field>
        {err && <p role="alert" className="text-[0.7647rem] text-(--danger)">{err}</p>}
      </div>
    </Sheet>
  )
}

// ---------------------------------------------------------------- editor --
const toUnit = (secPerKm: number, imperial: boolean) => formatDuration(Math.round(secPerKm * (imperial ? KM_PER_MI : 1)))
const fromUnit = (v: string, imperial: boolean) => {
  const s = parseDuration(v, 'minutes')
  return s == null ? null : s / (imperial ? KM_PER_MI : 1)
}

function BuddyEditor({ state, imperial, onClose, onSaved }: { state: BuddyState; imperial: boolean; onClose: () => void; onSaved: () => void }) {
  const base: BuddyProfile = state.profile ?? { sports: state.suggested.sports.length ? state.suggested.sports : ['run'], pace: state.suggested.pace,
    slots: state.suggested.slots, race: '', note: '', paused: false }
  const [sports, setSports] = useState<BuddySport[]>(base.sports)
  const [slots, setSlots] = useState<string[]>(base.slots)
  const [race, setRace] = useState(base.race)
  const [note, setNote] = useState(base.note)
  const [runPace, setRunPace] = useState<[string, string]>(() => {
    const b = base.pace.run ?? base.pace.trail
    return b ? [toUnit(b[0], imperial), toUnit(b[1], imperial)] : ['', '']
  })
  const [rideMph, setRideMph] = useState<[string, string]>(() => {
    const b = base.pace.ride
    const f = imperial ? 1 / KM_PER_MI : 1
    return b ? [String(Math.round(b[0] * f)), String(Math.round(b[1] * f))] : ['', '']
  })
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const toggle = (s: string) => setSlots((xs) => xs.includes(s) ? xs.filter((x) => x !== s) : [...xs, s])

  async function save() {
    setBusy('save'); setErr(null)
    const pace: BuddyProfile['pace'] = {}
    const lo = fromUnit(runPace[0], imperial), hi = fromUnit(runPace[1], imperial)
    if (lo && hi) for (const s of ['run', 'trail'] as const) if (sports.includes(s)) pace[s] = [Math.min(lo, hi), Math.max(lo, hi)] as Band
    const f = imperial ? KM_PER_MI : 1
    const r0 = Number(rideMph[0]) * f, r1 = Number(rideMph[1]) * f
    if (sports.includes('ride') && r0 > 0 && r1 > 0) pace.ride = [Math.min(r0, r1), Math.max(r0, r1)]
    if (sports.includes('swim') && base.pace.swim) pace.swim = base.pace.swim
    try { await saveBuddies({ sports, pace, slots, race, note, paused: false }); onSaved() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  async function turnOff() {
    setBusy('off'); setErr(null)
    try { await deleteBuddies(); onSaved() } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  const unit = imperial ? 'mi' : 'km'
  return (
    <Sheet title="Your buddy profile" onClose={onClose} portal bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4"
      footer={
        <div className="flex gap-2 border-t border-(--border) bg-(--bg) px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          {state.profile && <Button variant="default" className="h-11 px-4" loading={busy === 'off'} onClick={() => void turnOff()}>Turn off</Button>}
          <Button variant="primary" className="h-11 flex-1" loading={busy === 'save'} disabled={!sports.length} onClick={() => void save()}>
            {!sports.length ? 'Pick a sport' : state.profile ? 'Save' : 'Turn on and find buddies'}
          </Button>
        </div>
      }>
      <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
        Filled in from your recent workouts; change anything. Others see these ranges, your usual times, city and about how far away you are. Never your exact location, heart rate or workouts.
      </p>
      <Field label="Sports"><MultiChoice value={sports} options={BUDDY_SPORTS} onChange={setSports} /></Field>
      {(sports.includes('run') || sports.includes('trail')) && (
        <Field label={`Easy run pace, per ${unit}`} hint="The pace you can chat at. A range works best.">
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-[0.7059rem] text-(--text-muted)">From (faster)</span>
              <DurationInput label="Easy pace, faster end" withHours={false} value={runPace[0]} onChange={(v) => setRunPace(([, b]) => [v, b])} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[0.7059rem] text-(--text-muted)">To (slower)</span>
              <DurationInput label="Easy pace, slower end" withHours={false} value={runPace[1]} onChange={(v) => setRunPace(([a]) => [a, v])} />
            </div>
          </div>
        </Field>
      )}
      {sports.includes('ride') && (
        <Field label={`Easy ride speed, ${imperial ? 'mph' : 'km/h'}`}>
          <div className="flex items-center gap-2">
            <input className={inputCls} inputMode="numeric" aria-label="Easy ride speed, low" value={rideMph[0]} onChange={(e) => setRideMph(([, b]) => [e.target.value.replace(/\D/g, '').slice(0, 2), b])} />
            <span className="text-(--text-muted)" aria-hidden>to</span>
            <input className={inputCls} inputMode="numeric" aria-label="Easy ride speed, high" value={rideMph[1]} onChange={(e) => setRideMph(([a]) => [a, e.target.value.replace(/\D/g, '').slice(0, 2)])} />
          </div>
        </Field>
      )}
      <Field label="Usual times" hint={slots.length ? slotsText(slots) : 'Tap the times you usually train.'}>
        <div role="group" aria-label="Usual training times" className="grid grid-cols-[auto_repeat(7,minmax(0,1fr))] items-center gap-1">
          <span />
          {WEEKDAYS.map((d) => <span key={d} className="text-center text-[0.6471rem] font-semibold uppercase text-(--text-muted)">{d.slice(0, 2)}</span>)}
          {WHEN.map((w) => (
            <SlotRow key={w} when={w} slots={slots} onToggle={toggle} />
          ))}
        </div>
      </Field>
      <Field label="Training for (optional)">
        <input className={inputCls} maxLength={60} value={race} onChange={(e) => setRace(e.target.value)} placeholder="e.g. Denver Half" />
      </Field>
      <Field label="A short note (optional)">
        <textarea className={areaCls} maxLength={160} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Easy miles, coffee after" />
      </Field>
      {err && <p role="alert" className="text-[0.7647rem] text-(--danger)">{err}</p>}
    </Sheet>
  )
}

function SlotRow({ when, slots, onToggle }: { when: string; slots: string[]; onToggle: (s: string) => void }) {
  return (
    <>
      <span className="pr-1 text-[0.7059rem] capitalize text-(--text-secondary)">{when}</span>
      {WEEKDAYS.map((d) => {
        const k = `${d}-${when}`
        const on = slots.includes(k)
        return (
          <button key={k} type="button" aria-pressed={on} aria-label={`${d} ${when}`} onClick={() => onToggle(k)}
            className={cn('h-11 rounded-md border text-[0.7059rem]', on ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border) bg-(--bg-surface) text-(--text-muted)')}>
            {on ? '✓' : ''}
          </button>
        )
      })}
    </>
  )
}
