// Body screens (server: body.py), opened from anywhere with lib/body openBody():
//   * Body & niggles: active niggles with today's quick update (better / same / worse + pain),
//     a pain trend, prehab, red flags, Rabbit's easing suggestion for the plan (a diff to
//     accept), resolve; "Log a niggle" form; resolved history.
//   * Fueling: what you've practised vs your race target, Rabbit's learnings, trend.
// Mounted once in screens/Chat.tsx. Not medical advice: the care note shows on every niggle.
import { useCallback, useEffect, useState } from 'react'
import { ArrowRight, Check, Plus, TriangleAlert, Utensils } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { EmptyState } from '@/components/ui/EmptyState'
import { RabbitNote, SectionLabel } from '@/components/ui/brand'
import { RabbitInline } from '@/components/chat/RabbitText'
import { fmtDay } from '@/components/plan/PlanParts'
import { fmtDuration } from '@/lib/format'
import { cn } from '@/lib/utils'
import { haptic } from '@/lib/haptics'
import {
  NIGGLES_CHANGED, OPEN_BODY_EVENT, PLAN_RELOAD, addNiggle, easeForNiggles, getFueling, getNiggles, toFluidUnit, updateNiggle,
  type BodyView, type FuelEntry, type FuelLearnings, type Niggle, type Niggles,
} from '@/lib/body'
import { Chips } from './FuelLog'

const BODY = 'settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]'
const TYPES = [['ache', 'Ache'], ['tight', 'Tight'], ['sharp', 'Sharp'], ['swollen', 'Swollen']] as const
const SIDES = [['left', 'Left'], ['right', 'Right'], ['both', 'Both'], ['none', 'Not sided']] as const
const SPORTS = [['run', 'Running'], ['bike', 'Cycling'], ['swim', 'Swimming']] as const
const TRENDS = [['better', 'Better'], ['same', 'Same'], ['worse', 'Worse']] as const

export function BodyHost({ imperial }: { imperial: boolean }) {
  const [view, setView] = useState<BodyView | null>(null)
  useEffect(() => {
    const on = (e: Event) => setView((e as CustomEvent<BodyView>).detail)
    window.addEventListener(OPEN_BODY_EVENT, on)
    return () => window.removeEventListener(OPEN_BODY_EVENT, on)
  }, [])
  if (!view) return null
  const close = () => setView(null)
  if (view.view === 'fueling') return <FuelingSheet imperial={imperial} onClose={close} />
  return <NigglesSheet startWithForm={view.view === 'log-niggle'} affects={view.view === 'log-niggle' ? view.affects : undefined} onClose={close} />
}

// ------------------------------------------------------------------ niggles --
function NigglesSheet({ startWithForm, affects, onClose }: { startWithForm: boolean; affects?: string; onClose: () => void }) {
  const [data, setData] = useState<Niggles | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [form, setForm] = useState(startWithForm)
  const load = useCallback(() => { getNiggles().then((d) => { setData(d); setErr(null) }, (e: Error) => setErr(e.message)) }, [])
  useEffect(() => { load() }, [load])
  const changed = (d: Niggles) => {
    setData(d)
    try { window.dispatchEvent(new CustomEvent(NIGGLES_CHANGED)) } catch { /* ignore */ }
  }

  if (form) {
    return (
      <NiggleForm affects={affects} areas={data?.areas} onCancel={() => (startWithForm && !data?.active.length ? onClose() : setForm(false))}
        onSaved={(d) => { changed(d); setForm(false); haptic() }} />
    )
  }
  return (
    <Sheet title="Body & niggles" className="modal--tall" onClose={onClose} bodyClassName={BODY}
      footer={<Button variant="primary" className="h-11 w-full gap-1.5 text-[0.8235rem]" onClick={() => setForm(true)}><Plus className="size-4" aria-hidden />Log a niggle</Button>}>
      {!data && !err && <RabbitLoader className="py-10" label="Checking in on your body" />}
      {err && <p className="text-[0.7647rem] text-(--danger)" role="alert">{err}</p>}
      {data && data.proposal && <EaseCard p={data.proposal} onDone={() => { load(); try { window.dispatchEvent(new CustomEvent(PLAN_RELOAD)) } catch { /* ignore */ } }} />}
      {data && data.active.length === 0 && (
        <EmptyState compact title="Nothing's bugging you"
          body="Log an ache or a tight spot early. Rabbit eases the plan around it and suggests prehab, so small things stay small." />
      )}
      {data && data.active.map((n) => <NiggleCard key={n.id} n={n} onChanged={changed} />)}
      {data && data.resolved.length > 0 && (
        <section aria-label="Resolved" className="flex flex-col gap-1.5">
          <SectionLabel as="h3">Resolved</SectionLabel>
          <ul className="flex flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-1">
            {data.resolved.map((n) => (
              <li key={n.id} className="flex min-h-11 items-center gap-2 text-[0.7647rem]">
                <Check className="size-4 text-(--accent)" aria-hidden />
                <span className="flex-1 text-(--text)">{n.label}</span>
                <span className="text-(--text-muted)">{fmtDay(n.created, { month: 'short', day: 'numeric' })}{n.resolved ? ` – ${fmtDay(n.resolved, { month: 'short', day: 'numeric' })}` : ''}</span>
                <button type="button" className="hit-44 font-medium text-(--accent)" onClick={() => void updateNiggle(n.id, { reopen: true }).then(changed)}>Reopen</button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {data && <p className="m-0 px-1 text-[0.7059rem] leading-snug text-(--text-muted)">{data.care_note}</p>}
    </Sheet>
  )
}

function NiggleCard({ n, onChanged }: { n: Niggle; onChanged: (d: Niggles) => void }) {
  const a = n.assess
  const [trend, setTrend] = useState<'better' | 'same' | 'worse' | null>(null)
  const [pain, setPain] = useState(a?.pain ?? n.pain)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const today = n.history[n.history.length - 1]?.date
  async function run(key: string, body: Record<string, unknown>) {
    setBusy(key); setErr(null)
    try { onChanged(await updateNiggle(n.id, body)); setTrend(null) } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <article aria-label={n.label} className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
      <header className="flex items-start gap-3">
        <PainBadge pain={a?.pain ?? n.pain} />
        <div className="min-w-0 flex-1">
          <h3 className="m-0 text-[0.9412rem] font-semibold text-(--text)">{n.label}</h3>
          <p className="m-0 text-[0.7059rem] text-(--text-muted)">
            {[n.type[0]!.toUpperCase() + n.type.slice(1), n.affects.map((s) => SPORTS.find(([v]) => v === s)?.[1] ?? s).join(', '),
              a ? (a.age_days ? `day ${a.age_days + 1}` : 'new today') : '', a?.trend ? `last: ${a.trend}` : ''].filter(Boolean).join(' · ')}
          </p>
        </div>
      </header>
      {n.history.length > 1 && <PainTrend h={n.history} />}
      {a && a.red_flag.length > 0 && (
        <div role="alert" className="flex gap-2 rounded-lg border border-(--danger)/30 bg-(--danger)/5 px-3 py-2.5">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-(--danger)" aria-hidden />
          <p className="m-0 text-[0.7647rem] leading-snug text-(--text)">
            <b className="font-semibold">Stop training this and see a physio or doctor.</b> {a.red_flag.join('; ')}.
          </p>
        </div>
      )}
      {a && !a.red_flag.length && a.ease && (
        <p className="m-0 text-[0.7647rem] text-(--text-secondary)"><RabbitInline text={`**Easy for ${a.days} days** for ${n.affects.map((s) => SPORTS.find(([v]) => v === s)?.[1].toLowerCase() ?? s).join(' and ')}: no hard efforts, shorter sessions${a.swap ? ', and runs swapped for an easy ride or swim' : ''}.`} /></p>
      )}
      {n.needs_update && (
        <div className="flex flex-col gap-2 rounded-lg bg-(--bg-inset) p-3">
          <span className="text-[0.7647rem] font-medium text-(--text)">How is it today?</span>
          <Chips label="Compared with last time" value={trend} options={TRENDS} onChange={setTrend} />
          <label className="flex flex-col gap-1">
            <span className="flex justify-between text-[0.7647rem] text-(--text)"><span>Pain</span><span className="font-mono tabular-nums text-(--accent)">{pain}/10</span></span>
            <input type="range" min={0} max={10} value={pain} onChange={(e) => setPain(Number(e.target.value))}
              aria-valuetext={`${pain} out of 10`} className="h-11 w-full accent-(--accent)" />
          </label>
          <Button variant="primary" className="h-11 text-[0.8235rem]" disabled={!trend} loading={busy === 'up'}
            onClick={() => void run('up', { trend, pain })}>{trend ? 'Save today' : 'Pick better, same or worse'}</Button>
        </div>
      )}
      {!n.needs_update && today && <p className="m-0 text-[0.7059rem] text-(--text-muted)">Updated today. Check back tomorrow.</p>}
      {n.prehab.length > 0 && (
        <details className="group rounded-lg border border-(--border)">
          <summary className="flex min-h-11 cursor-pointer list-none items-center px-3 text-[0.7647rem] font-medium text-(--accent) [&::-webkit-details-marker]:hidden">
            Prehab for your {n.area_label.toLowerCase()}
          </summary>
          <ul className="flex flex-col gap-1.5 px-3 pb-3">
            {n.prehab.map((e) => (
              <li key={e.name} className="flex gap-2 text-[0.7647rem]"><span className="flex-1 text-(--text)">{e.name}</span><span className="text-(--text-muted)">{e.dose}</span></li>
            ))}
          </ul>
        </details>
      )}
      {err && <p className="m-0 text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant="default" className="h-11 gap-1.5 px-3 text-[0.7647rem]" loading={busy === 'res'} onClick={() => void run('res', { resolve: true })}>
          <Check className="size-4" aria-hidden />It's gone
        </Button>
        <Button variant="ghost" className="h-11 px-3 text-[0.7647rem] text-(--text-muted)" loading={busy === 'del'} onClick={() => void run('del', { delete: true })}>Delete</Button>
      </div>
    </article>
  )
}

function PainBadge({ pain }: { pain: number }) {
  const tone = pain >= 7 ? 'bg-(--danger)/10 text-(--danger)' : pain >= 4 ? 'bg-(--warning-subtle) text-(--warning-text)' : 'bg-(--accent-subtle) text-(--accent)'
  return (
    <span className={cn('flex size-11 shrink-0 flex-col items-center justify-center rounded-xl font-mono leading-none', tone)}
      aria-label={`Pain ${pain} out of 10`}>
      <span className="text-[0.9412rem] font-semibold tabular-nums">{pain}</span><span className="text-[0.6471rem]">/10</span>
    </span>
  )
}

/** Pain over time: a small line, 0-10, last 30 entries. */
function PainTrend({ h }: { h: Niggle['history'] }) {
  const pts = h.slice(-30)
  const W = 280, H = 56
  const x = (i: number) => (pts.length === 1 ? W / 2 : (i / (pts.length - 1)) * (W - 8) + 4)
  const y = (p: number) => H - 6 - (p / 10) * (H - 12)
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.pain).toFixed(1)}`).join(' ')
  const first = pts[0]!, last = pts[pts.length - 1]!
  return (
    <figure className="m-0 flex flex-col gap-1">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-14 w-full" role="img"
        aria-label={`Pain from ${first.pain} on ${fmtDay(first.date, { month: 'short', day: 'numeric' })} to ${last.pain} on ${fmtDay(last.date, { month: 'short', day: 'numeric' })}`}>
        <line x1="4" x2={W - 4} y1={y(4)} y2={y(4)} stroke="var(--border)" strokeDasharray="3 3" />
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {pts.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.pain)} r="2.5" fill="var(--accent)" />)}
      </svg>
      <figcaption className="flex justify-between text-[0.6471rem] text-(--text-muted)">
        <span>{fmtDay(first.date, { month: 'short', day: 'numeric' })}</span><span>dashed: 4/10, when Rabbit eases off</span><span>{fmtDay(last.date, { month: 'short', day: 'numeric' })}</span>
      </figcaption>
    </figure>
  )
}

function EaseCard({ p, onDone }: { p: NonNullable<Niggles['proposal']>; onDone: () => void }) {
  const [busy, setBusy] = useState<'apply' | 'dismiss' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  async function act(a: 'apply' | 'dismiss') {
    setBusy(a); setErr(null)
    try { await easeForNiggles(p.id, a); if (a === 'apply') haptic(); onDone() } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  const SPORT = { run: 'run', bike: 'ride', swim: 'swim', brick: 'brick' } as Record<string, string>
  return (
    <RabbitNote title="Rabbit suggests easing your plan">
      <p className="m-0 text-[0.7647rem] text-(--text-secondary)"><RabbitInline text={p.why} /></p>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {p.changes.map((c) => (
          <li key={c.session_id} className="flex flex-wrap items-center gap-x-1.5 text-[0.7647rem] text-(--text)">
            <span className="w-16 shrink-0 text-(--text-muted)">{fmtDay(c.date, { weekday: 'short', day: 'numeric' })}</span>
            <span className="line-through decoration-(--text-muted)">{c.from.title} {c.from.minutes ? fmtDuration(c.from.minutes) : ''}</span>
            <ArrowRight className="size-3.5 text-(--text-muted)" aria-label="becomes" />
            <b className="font-semibold">Easy {SPORT[c.to.sport] ?? c.to.sport} {fmtDuration(c.to.minutes)}</b>
          </li>
        ))}
      </ul>
      {err && <p className="m-0 text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      <div className="flex gap-2">
        <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy === 'apply'} onClick={() => void act('apply')}>Ease my plan</Button>
        <Button variant="ghost" className="h-11 px-3 text-[0.8235rem]" loading={busy === 'dismiss'} onClick={() => void act('dismiss')}>Not now</Button>
      </div>
    </RabbitNote>
  )
}

function NiggleForm({ affects, areas, onCancel, onSaved }: {
  affects?: string; areas?: Record<string, string>; onCancel: () => void; onSaved: (d: Niggles) => void
}) {
  const AREA_LIST = Object.entries(areas ?? { foot: 'Foot', ankle: 'Ankle', achilles: 'Achilles', calf: 'Calf', shin: 'Shin', knee: 'Knee',
    it_band: 'IT band', hamstring: 'Hamstring', quad: 'Quad', hip: 'Hip', glute: 'Glute', lower_back: 'Lower back', shoulder: 'Shoulder', other: 'Other' })
  const [area, setArea] = useState<string | null>(null)
  const [side, setSide] = useState<string | null>(null)
  const [pain, setPain] = useState(3)
  const [type, setType] = useState<string | null>('ache')
  const [sports, setSports] = useState<string[]>(affects && ['run', 'bike', 'swim'].includes(affects) ? [affects] : ['run'])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function save() {
    setBusy(true); setErr(null)
    try { onSaved(await addNiggle({ area, side: side ?? 'none', pain, type: type ?? 'ache', affects: sports, note })) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const PAIN_WORD = pain >= 7 ? 'Bad' : pain >= 4 ? 'Noticeable' : pain >= 1 ? 'Mild' : 'None'
  return (
    <Sheet title="Log a niggle" className="modal--tall" onClose={onCancel} bodyClassName={BODY}
      footer={(
        <div className="flex gap-2">
          <Button variant="default" className="h-11 px-5 text-[0.8235rem]" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy} disabled={!area || !sports.length} onClick={() => void save()}>
            {!area ? 'Pick where it hurts' : !sports.length ? 'Pick a sport' : 'Save'}
          </Button>
        </div>
      )}>
      <Chips label="Where" value={area} options={AREA_LIST as unknown as readonly (readonly [string, string])[]} onChange={setArea} />
      <Chips label="Side" value={side} options={SIDES} onChange={setSide} />
      <label className="flex flex-col gap-1">
        <span className="flex justify-between text-[0.7647rem] text-(--text)"><span>Pain</span>
          <span className="font-mono tabular-nums text-(--accent)">{pain}/10 · {PAIN_WORD}</span></span>
        <input type="range" min={0} max={10} value={pain} onChange={(e) => setPain(Number(e.target.value))}
          aria-valuetext={`${pain} out of 10, ${PAIN_WORD}`} className="h-11 w-full accent-(--accent)" />
      </label>
      <Chips label="What it feels like" value={type} options={TYPES} onChange={setType} />
      <div className="flex flex-col gap-1.5">
        <span className="text-[0.7647rem] text-(--text)">It bothers me when</span>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Sports it affects">
          {SPORTS.map(([v, l]) => (
            <button key={v} type="button" aria-pressed={sports.includes(v)} onClick={() => setSports((s) => (s.includes(v) ? s.filter((x) => x !== v) : [...s, v]))}
              className={cn('plan-chip min-h-11', sports.includes(v) && 'plan-chip--on')}>{l}</button>
          ))}
        </div>
      </div>
      <textarea value={note} onChange={(e) => setNote(e.target.value.slice(0, 300))} rows={2} aria-label="Note"
        placeholder="When it started, what makes it worse (optional)"
        className="min-h-11 w-full rounded-md border border-input bg-transparent px-3 py-2 text-[0.8235rem] text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
      {err && <p className="m-0 text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      <p className="m-0 text-[0.7059rem] leading-snug text-(--text-muted)">
        Not medical advice. If pain is sharp, getting worse or changes how you move, see a physio or doctor.
      </p>
    </Sheet>
  )
}

// ------------------------------------------------------------------ fueling --
function FuelingSheet({ imperial, onClose }: { imperial: boolean; onClose: () => void }) {
  const [d, setD] = useState<{ learnings: FuelLearnings; target: number; entries: FuelEntry[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { getFueling().then(setD, (e: Error) => setErr(e.message)) }, [])
  const fl = imperial ? 'fl oz' : 'ml'
  return (
    <Sheet title="Fueling" className="modal--tall" onClose={onClose} bodyClassName={BODY}>
      {!d && !err && <RabbitLoader className="py-10" label="Counting your gels" />}
      {err && <p className="text-[0.7647rem] text-(--danger)" role="alert">{err}</p>}
      {d && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Race target" value={d.target ? `${d.target} g/h` : 'Water is enough'} />
            <Stat label="Practised well" value={d.learnings.learned_rate != null ? `${d.learnings.learned_rate} g/h` : '–'} />
          </div>
          {d.learnings.lines.length > 0 && (
            <RabbitNote title="What Rabbit's learned">
              {d.learnings.lines.map((l) => <p key={l} className="m-0 text-[0.7647rem] text-(--text-secondary)"><RabbitInline text={l} /></p>)}
            </RabbitNote>
          )}
          {d.learnings.trend.length > 0 ? (
            <section aria-label="Carbs per hour on your long sessions" className="flex flex-col gap-1.5">
              <SectionLabel as="h3">Carbs per hour, recent long workouts</SectionLabel>
              <FuelBars t={d.learnings.trend} target={d.target} />
            </section>
          ) : (
            <EmptyState compact icon={<Utensils className="size-6" />} title="No fueling logged yet"
              body="Open any session of an hour or more and tap Log fueling. After a few, Rabbit shows what works for you." />
          )}
          {d.entries.length > 0 && (
            <section aria-label="Logged sessions" className="flex flex-col gap-1.5">
              <SectionLabel as="h3">Logged</SectionLabel>
              <ul className="flex flex-col divide-y divide-(--border) rounded-xl border border-(--border) bg-(--bg-surface) px-3.5">
                {d.entries.map((e) => (
                  <li key={e.key} className="flex min-h-12 items-center gap-2 py-2 text-[0.7647rem]">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-(--text)">{e.title || 'Session'}</span>
                      <span className="block text-[0.7059rem] text-(--text-muted)">{e.date ? fmtDay(e.date, { month: 'short', day: 'numeric' }) : ''} · {e.minutes} min
                        {e.gi === 'issues' ? ' · gut issues' : ''}{e.energy === 'bonked' ? ' · bonked' : e.energy === 'strong' ? ' · strong' : ''}</span>
                    </span>
                    <span className="text-right font-mono tabular-nums text-(--text)">{e.g_per_h ?? 0} g/h
                      {e.ml_per_h != null && <span className="block text-[0.6471rem] text-(--text-muted)">{toFluidUnit(e.ml_per_h, imperial)} {fl}/h</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </Sheet>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
      <span className="text-[0.7059rem] text-(--text-muted)">{label}</span>
      <span className="font-mono text-[1.0588rem] font-semibold tabular-nums text-(--text)">{value}</span>
    </div>
  )
}

/** One bar per logged long session (g/h), coloured by how it went; the race target as a line. */
function FuelBars({ t, target }: { t: FuelLearnings['trend']; target: number }) {
  const W = 300, H = 120, top = Math.max(100, target + 10, ...t.map((x) => x.g_per_h))
  const bw = Math.min(28, (W - 8) / t.length - 6)
  const y = (v: number) => H - 16 - (v / top) * (H - 26)
  const color = (x: FuelLearnings['trend'][number]) =>
    x.gi === 'issues' || x.energy === 'bonked' ? 'var(--warning)' : x.energy === 'strong' ? 'var(--accent)' : 'var(--text-muted)'
  return (
    <figure className="m-0 rounded-xl border border-(--border) bg-(--bg-surface) p-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-32 w-full" role="img"
        aria-label={t.map((x) => `${x.date}: ${x.g_per_h} grams per hour${x.gi === 'issues' ? ', gut issues' : ''}${x.energy ? `, ${x.energy}` : ''}`).join('; ')}>
        {t.map((x, i) => {
          const cx = 4 + i * ((W - 8) / t.length) + ((W - 8) / t.length - bw) / 2
          return (
            <g key={i}>
              <rect x={cx} y={y(x.g_per_h)} width={bw} height={H - 16 - y(x.g_per_h)} rx="3" fill={color(x)} />
              <text x={cx + bw / 2} y={H - 4} textAnchor="middle" fontSize="9" fill="var(--text-muted)">{x.date ? x.date.slice(5).replace('-', '/') : ''}</text>
            </g>
          )
        })}
        {target > 0 && (
          <>
            <line x1="0" x2={W} y1={y(target)} y2={y(target)} stroke="var(--brand)" strokeDasharray="4 3" strokeWidth="1.5" />
            <text x={W - 2} y={y(target) - 3} textAnchor="end" fontSize="9" fill="var(--brand)">race {target} g/h</text>
          </>
        )}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-3 text-[0.6471rem] text-(--text-muted)">
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-(--accent)" aria-hidden />Strong</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-(--text-muted)" aria-hidden />Faded</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-(--warning)" aria-hidden />Gut issues or bonked</span>
      </figcaption>
    </figure>
  )
}
