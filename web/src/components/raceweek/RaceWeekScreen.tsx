// Race-week page (server: raceweek.py): pacing plan, course notes, packing list (saved per race),
// nutrition, logistics, Track me and friends racing; on race day the status comes first.
// Deterministic; the only AI is the optional "Ask Rabbit about race day", which prefills the chat.
import { useEffect, useRef, useState } from 'react'
import { CheckSquare, CloudSun, ExternalLink, Gauge, MapPin, Minus, Mountain, Plus, Radio, Square, Utensils, X } from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { RabbitLogo } from '@/components/RabbitLogo'
import { RacePeopleSection } from '@/components/events/RacePeople'
import { Card, Field, Screen, inputCls } from '@/components/plan/ui'
import { Switch } from '@/components/settings/Grouped'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { fmtClimb, fmtDuration, fmtSpeed } from '@/lib/format'
import {
  askText, getRaceWeek, hms, packingAction, putRaceWeek, reminderAction, statusLine,
  type Packing, type RaceWeekPage, type RaceWeekPatch, type Reminder,
} from '@/lib/raceweek'
import { cn } from '@/lib/utils'
import { ChecklistButton } from '@/components/events/ChecklistLink'

const cToF = (c: number) => Math.round(c * 9 / 5 + 32)
const SOURCE: Record<string, string> = { you: 'your target', goal: 'your goal time', estimate: 'your estimated finish' }

function TargetEditor({ p, onSave }: { p: RaceWeekPage; onSave: (s: number | null) => Promise<void> }) {
  const cur = p.pacing.target_s
  const [v, setV] = useState(cur ?? 0)
  const [busy, setBusy] = useState(false)
  useEffect(() => setV(cur ?? 0), [cur])
  if (!cur) return null
  const step = v >= 3 * 3600 ? 300 : 60
  const save = async (s: number | null) => { setBusy(true); try { await onSave(s) } finally { setBusy(false) } }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="hit-44 flex size-9 items-center justify-center rounded-full border border-(--border)"
        aria-label={`${step / 60} minutes faster`} onClick={() => setV((x) => Math.max(300, x - step))}><Minus className="size-4" /></button>
      <span className="min-w-20 text-center font-mono text-[1.1765rem] font-semibold tabular-nums text-(--text)" aria-live="polite">{hms(v)}</span>
      <button type="button" className="hit-44 flex size-9 items-center justify-center rounded-full border border-(--border)"
        aria-label={`${step / 60} minutes slower`} onClick={() => setV((x) => Math.min(72 * 3600, x + step))}><Plus className="size-4" /></button>
      {v !== cur && <Button variant="primary" className="h-9 px-3 text-[0.7647rem]" loading={busy} onClick={() => void save(v)}>Use {hms(v)}</Button>}
      {p.pacing.source === 'you' && v === cur && (
        <button type="button" className="hit-44 px-1 text-[0.7647rem] text-(--accent)" onClick={() => void save(null)}>
          Back to {p.pacing.goal_s ? 'goal time' : 'estimate'}
        </button>
      )}
    </div>
  )
}

function PacingCard({ p, onSave }: { p: RaceWeekPage; onSave: (s: number | null) => Promise<void> }) {
  const pc = p.pacing
  const [effort, setEffort] = useState(false)
  return (
    <Card>
      <Field label="Pacing plan" hint={pc.source ? `Based on ${SOURCE[pc.source]}${pc.estimate ? ` · estimate ${pc.estimate.text}` : ''}` : undefined}>
        {pc.target ? <TargetEditor p={p} onSave={onSave} />
          : <p className="text-[0.8235rem] text-(--text-secondary)">Add a goal time to this race (or connect Garmin for an estimate) to see splits.</p>}
        {pc.mode === 'tri' && (
          <table className="mt-2 w-full text-[0.7647rem]">
            <thead><tr className="text-left font-mono text-[0.6471rem] uppercase tracking-wider text-(--text-muted)">
              <th className="py-1 font-semibold">Leg</th><th className="font-semibold">Time</th><th className="font-semibold">Pace</th><th className="text-right font-semibold">Clock</th></tr></thead>
            <tbody>
              {pc.legs.map((l) => (
                <tr key={l.leg} className="border-t border-(--border)">
                  <td className="py-1.5 font-medium text-(--text)">{l.label}</td>
                  <td className="font-mono tabular-nums text-(--text)">{l.time}</td>
                  <td className="font-mono text-[0.7059rem] tabular-nums text-(--text-secondary)">{l.pace ?? ''}</td>
                  <td className="text-right font-mono tabular-nums text-(--text-muted)">{l.cum}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {pc.splits && pc.splits.rows.length > 0 && (
          <>
            <p className="mt-1 text-[0.8235rem] text-(--text)">
              {pc.splits.pace ? <>Even pace <b className="font-mono tabular-nums">{pc.splits.pace}</b>{pc.splits.band ? <span className="text-(--text-muted)"> · band {pc.splits.band}</span> : null}</>
                : <>Average <b className="font-mono tabular-nums">{pc.splits.speed}</b></>}
            </p>
            <table className="mt-1 w-full text-[0.7647rem]">
              <thead><tr className="text-left font-mono text-[0.6471rem] uppercase tracking-wider text-(--text-muted)">
                <th className="py-1 font-semibold">At</th><th className="font-semibold">{pc.mode === 'speed' ? 'Speed' : 'Pace'}</th><th className="text-right font-semibold">Clock</th></tr></thead>
              <tbody>
                {pc.splits.rows.map((r) => (
                  <tr key={r.label} className="border-t border-(--border)">
                    <td className="py-1.5 text-(--text)">{r.label}</td>
                    <td className="font-mono tabular-nums text-(--text-secondary)">{r.pace ?? r.speed}</td>
                    <td className="text-right font-mono tabular-nums text-(--text)">{r.cum}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {pc.notes.map((n) => <p key={n} className="text-[0.7059rem] leading-snug text-(--text-muted)">{n}</p>)}
        {pc.effort.length > 0 && (
          <>
            <button type="button" className="hit-44 self-start text-[0.7647rem] font-medium text-(--accent)" aria-expanded={effort}
              onClick={() => setEffort((x) => !x)}>{effort ? 'Hide' : 'How to pace it'} (power, HR, effort)</button>
            {effort && pc.effort.map((x) => (
              <div key={x.leg}>
                <p className="flex items-baseline gap-2"><Gauge className="size-3.5 shrink-0 translate-y-0.5 text-(--accent)" aria-hidden />
                  <span className="text-[0.8235rem] font-medium text-(--text)">{x.leg}</span>
                  <span className="ml-auto text-[0.8235rem] text-(--accent)">{x.target}</span></p>
                <p className="pl-5.5 text-[0.7059rem] leading-snug text-(--text-muted)">{x.detail}</p>
              </div>
            ))}
          </>
        )}
      </Field>
    </Card>
  )
}

function PackingCard({ eventId, packing, onChange }: { eventId: string; packing: Packing; onChange: (p: Packing) => void }) {
  const [text, setText] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const act = async (body: Parameters<typeof packingAction>[1]) => {
    setErr(null)
    try { onChange(await packingAction(eventId, body)) } catch (e) { setErr((e as Error).message) }
  }
  const groups = [...new Set(packing.items.map((i) => i.group))]
  return (
    <Card>
      <div id="raceweek-packing" />
      <Field label={`Packing list · ${packing.done}/${packing.total}`} hint="Saved for this race on every device.">
        {groups.map((g) => (
          <div key={g} className="flex flex-col">
            <p className="mt-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-wider text-(--text-muted)">{g}</p>
            {packing.items.filter((i) => i.group === g).map((i) => (
              <div key={i.id} className="flex items-center">
                <button type="button" role="checkbox" aria-checked={i.done} onClick={() => void act({ toggle: i.id })}
                  className="flex min-h-11 flex-1 items-center gap-2.5 py-1 text-left text-[0.8235rem]">
                  {i.done ? <CheckSquare className="size-4 shrink-0 text-(--accent)" aria-hidden /> : <Square className="size-4 shrink-0 text-(--text-muted)" aria-hidden />}
                  <span className={i.done ? 'text-(--text-muted) line-through' : 'text-(--text)'}>{i.text}</span>
                </button>
                {i.custom && (
                  <button type="button" className="hit-44 p-1 text-(--text-muted)" aria-label={`Remove ${i.text}`}
                    onClick={() => void act({ remove: i.id })}><X className="size-3.5" /></button>
                )}
              </div>
            ))}
          </div>
        ))}
        <form className="mt-1 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { void act({ add: text }); setText('') } }}>
          <input className={inputCls} value={text} maxLength={80} placeholder="Add your own item" aria-label="Add your own packing item"
            onChange={(e) => setText(e.target.value)} />
          <Button type="submit" variant="default" className="h-10 px-3" disabled={!text.trim()}>Add</Button>
        </form>
        {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      </Field>
    </Card>
  )
}

function LogisticsCard({ p, onStart, onReminders }: {
  p: RaceWeekPage; onStart: (hhmm: string | null) => Promise<void>; onReminders: (r: Reminder[]) => void
}) {
  const lg = p.logistics
  const [start, setStart] = useState(lg.start_time ?? '')
  const [text, setText] = useState('')
  const [when, setWhen] = useState('')
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => setStart(lg.start_time ?? ''), [lg.start_time])
  const rem = async (body: Parameters<typeof reminderAction>[1]) => {
    setErr(null)
    try { onReminders((await reminderAction(p.event.id, body)).reminders) } catch (e) { setErr((e as Error).message) }
  }
  return (
    <Card>
      <Field label="Logistics">
        <label className="flex items-center gap-3 text-[0.8235rem] text-(--text)">
          <span className="w-24 shrink-0 text-(--text-secondary)">Start time</span>
          <input type="time" className={cn(inputCls, 'w-32')} value={start} onChange={(e) => setStart(e.target.value)}
            onBlur={() => { if (start !== (lg.start_time ?? '')) void onStart(start || null) }} />
        </label>
        {lg.location && (
          <p className="flex items-start gap-2 text-[0.8235rem] text-(--text)"><MapPin className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />
            <span className="min-w-0 flex-1">{lg.location}</span>
            {lg.maps_url && <a className="hit-44 shrink-0 text-[0.7647rem] text-(--accent)" href={lg.maps_url} target="_blank" rel="noopener noreferrer">Map</a>}
          </p>
        )}
        {lg.registration && <p className="text-[0.7647rem] text-(--text-secondary)">Check-in: {lg.registration}</p>}
        {lg.url && (
          <a className="hit-44 inline-flex items-center gap-1 self-start text-[0.7647rem] text-(--accent)" href={lg.url} target="_blank" rel="noopener noreferrer">
            Race website <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
        <p className="mt-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-wider text-(--text-muted)">Your reminders</p>
        {lg.reminders.length === 0 && <p className="text-[0.7647rem] text-(--text-muted)">Travel, bib pick-up, bike check-in: add what you need to remember.</p>}
        {lg.reminders.map((r) => (
          <div key={r.id} className="flex items-center">
            <button type="button" role="checkbox" aria-checked={r.done} onClick={() => void rem({ toggle: r.id })}
              className="flex min-h-11 flex-1 items-center gap-2.5 py-1 text-left text-[0.8235rem]">
              {r.done ? <CheckSquare className="size-4 shrink-0 text-(--accent)" aria-hidden /> : <Square className="size-4 shrink-0 text-(--text-muted)" aria-hidden />}
              <span className={r.done ? 'text-(--text-muted) line-through' : 'text-(--text)'}>{r.text}</span>
              {r.when && <span className="ml-auto shrink-0 font-mono text-[0.7059rem] text-(--text-muted)">
                {new Date(`${r.when.slice(0, 10)}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}{r.when.length > 10 ? ` ${r.when.slice(11)}` : ''}</span>}
            </button>
            <button type="button" className="hit-44 p-1 text-(--text-muted)" aria-label={`Remove ${r.text}`} onClick={() => void rem({ remove: r.id })}>
              <X className="size-3.5" />
            </button>
          </div>
        ))}
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { void rem({ add: { text, when: when || undefined } }); setText(''); setWhen('') } }}>
          <input className={cn(inputCls, 'min-w-0 flex-1')} value={text} maxLength={80} placeholder="e.g. Pick up bib" aria-label="Reminder" onChange={(e) => setText(e.target.value)} />
          <input type="date" className={cn(inputCls, 'w-40')} value={when} aria-label="Reminder date" onChange={(e) => setWhen(e.target.value)} />
          <Button type="submit" variant="default" className="h-10 px-3" disabled={!text.trim()}>Add</Button>
        </form>
        {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      </Field>
    </Card>
  )
}

function TrackCard({ p, onPatch }: { p: RaceWeekPage; onPatch: (x: RaceWeekPatch) => Promise<void> }) {
  const t = p.tracking
  const st = t.status
  return (
    <Card>
      <Field label={p.race_day || st ? 'Race day' : 'Track me on race day'} hint={t.note}>
        {st && (
          <p className={cn('flex items-center gap-2 text-[0.9412rem] font-semibold', st.state === 'finished' ? 'text-(--accent)' : 'text-(--text)')} role="status">
            <Radio className="size-4 shrink-0" aria-hidden /> {statusLine(st)}
          </p>
        )}
        {st?.state === 'finished' && st.result && (
          <p className="text-[0.7647rem] text-(--text-secondary)">From Garmin: {st.result.name}{st.result.distance_km ? ` · ${st.result.distance_km} km` : ''}</p>
        )}
        {st && st.state !== 'finished' && <p className="text-[0.7059rem] text-(--text-muted)">Your result shows here once your watch syncs.</p>}
        <div className="flex items-center gap-3">
          <span className="min-w-0 flex-1 text-[0.8235rem] text-(--text)">Track me
            <span className="block text-[0.7059rem] text-(--text-muted)">{t.audience ? `${t.audience} friend${t.audience === 1 ? '' : 's'} who follow you back can see it` : 'Friends who follow you back can see it'}</span></span>
          <Switch checked={t.on} label="Track me" onChange={(v) => void onPatch({ tracking: v })} />
        </div>
        {t.on && (
          <div className="flex items-center gap-3">
            <span className="min-w-0 flex-1 text-[0.8235rem] text-(--text)">Tell them when I start and finish
              <span className="block text-[0.7059rem] text-(--text-muted)">One push at your planned start and one when your finish syncs. Not during their quiet hours.</span></span>
            <Switch checked={t.notify_friends} label="Tell friends when I start and finish" onChange={(v) => void onPatch({ notify_friends: v })} />
          </div>
        )}
      </Field>
    </Card>
  )
}

export function RaceWeekScreen({ eventId, section, onClose, onAsk }: {
  eventId: string; section?: string; onClose: () => void
  /** "Ask Rabbit about race day": opens the chat with the race's numbers prefilled */
  onAsk: (text: string) => void
}) {
  const [p, setP] = useState<RaceWeekPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const scrolled = useRef(false)
  const load = () => { setError(null); getRaceWeek(eventId).then(setP, (e) => setError((e as Error).message)) }
  useEffect(load, [eventId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!p || scrolled.current || section !== 'packing') return
    scrolled.current = true
    document.getElementById('raceweek-packing')?.scrollIntoView({ block: 'start' })
  }, [p, section])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const patch = async (x: RaceWeekPatch) => {
    setMsg(null)
    try { await putRaceWeek(eventId, x); load() } catch (e) { setMsg((e as Error).message) }
  }
  const imperial = p?.imperial ?? true
  const temp = (c: number | null) => c == null ? '–' : imperial ? `${cToF(c)}°F` : `${Math.round(c)}°C`
  const c = p?.course
  const hasCourse = !!c && !!(c.text || c.profile || c.climb_m || c.elevation_m || c.terrain || c.weather || c.typical_weather)
  const day = p ? (p.days === 0 ? 'Race day!' : p.days === 1 ? 'Tomorrow' : p.days > 1 ? `${p.days} days to go` : 'Done') : undefined
  const n = p?.nutrition

  return (
    <Screen title={p?.race_day ? 'Race day' : 'Race week'} subtitle={p ? `${p.event.name} · ${day}` : undefined}
      closing={closing} onClose={close}
      footer={p ? (
        <Button variant="default" className="h-11 flex-1 gap-2 text-[0.8235rem]" onClick={() => onAsk(askText(p))}>
          <RabbitLogo current size={16} /> Ask rabbt about race day
        </Button>
      ) : undefined}>
      {!p && !error && <RabbitLoader className="py-16" label="Building your race week" cycle={['Splitting your pace…', 'Checking the course…', 'Packing your bag…']} />}
      {error && <ErrorState message={error} onRetry={load} />}
      {msg && <p className="text-[0.7647rem] text-(--danger)" role="alert">{msg}</p>}
      {p && (
        <>
          {(p.days <= 0) && <TrackCard p={p} onPatch={patch} />}
          {p.days > 0 && (
            <Card>
              <Field label="This week">
                <p className="text-[0.8235rem] text-(--text)">{p.taper.text}</p>
                {p.today.map((s) => (
                  <p key={`${s.id}-${s.title}`} className="text-[0.7647rem] text-(--text-secondary)">Today: {s.title}{s.minutes ? ` · ${fmtDuration(s.minutes)}` : ''}</p>
                ))}
              </Field>
            </Card>
          )}
          <PacingCard p={p} onSave={(s) => patch({ target_s: s })} />
          {hasCourse && c && (
            <Card>
              <Field label="Course" hint={c.weather ? 'Forecast from Open-Meteo; check again the day before.' : undefined}>
                {c.text && <p className="text-[0.8235rem] text-(--text)">{c.text}</p>}
                {(c.profile || c.climb_m || c.elevation_m) && (
                  <p className="flex flex-wrap items-center gap-1.5 text-[0.7647rem] text-(--text-secondary)">
                    <Mountain className="size-4 text-(--accent)" aria-hidden />
                    {[c.profile ? c.profile[0]!.toUpperCase() + c.profile.slice(1) : null,
                      c.climb_m ? `+${fmtClimb(c.climb_m, imperial)} climbing` : null,
                      c.elevation_m ? `${fmtClimb(c.elevation_m, imperial)} altitude` : null].filter(Boolean).join(' · ')}
                  </p>
                )}
                {c.terrain && <p className="text-[0.7647rem] text-(--text-secondary)">Terrain: {c.terrain}</p>}
                {c.weather ? (
                  <p className="flex items-center gap-2 text-[0.8235rem] text-(--text)"><CloudSun className="size-4 text-(--accent)" aria-hidden />
                    {c.weather.place}: {temp(c.weather.low_c)} – {temp(c.weather.high_c)}, rain {c.weather.rain_pct ?? '–'}%, wind {c.weather.wind_kmh != null ? fmtSpeed(c.weather.wind_kmh, imperial) : '–'}
                  </p>
                ) : c.typical_weather ? <p className="text-[0.7647rem] text-(--text-secondary)">Typical weather: {c.typical_weather}</p> : null}
                {c.weather_tips.map((t) => <p key={t} className="text-[0.7647rem] text-(--warning-text)">{t}</p>)}
              </Field>
            </Card>
          )}
          <ChecklistButton eventId={p.event.id} />
          <PackingCard eventId={p.event.id} packing={p.packing} onChange={(pk) => setP((x) => x ? { ...x, packing: pk } : x)} />
          {n && (
            <Card>
              <Field label="Nutrition plan" hint={n.label}>
                <p className="flex items-center gap-2 text-[0.8235rem] text-(--text)"><Utensils className="size-4 text-(--accent)" aria-hidden />
                  {n.carbs_g_per_h[1] ? <><b className="font-mono tabular-nums">{n.carbs_g_per_h[0]}–{n.carbs_g_per_h[1]}</b> g carbs/h · about {n.total_carbs_g[0]}–{n.total_carbs_g[1]} g over ~{fmtDuration(n.hours * 60)}</>
                    : 'No carbs needed during a race this short.'}
                </p>
                <p className="text-[0.7059rem] text-(--text-muted)">Fluid {n.fluid_ml_per_h[0]}–{n.fluid_ml_per_h[1]} ml/h · sodium {n.sodium_mg_per_h[0]}–{n.sodium_mg_per_h[1]} mg/h</p>
                <ul className="flex flex-col gap-1 text-[0.7647rem] leading-snug text-(--text-secondary)">{n.steps.map((s) => <li key={s}>• {s}</li>)}</ul>
              </Field>
            </Card>
          )}
          <LogisticsCard p={p} onStart={(hhmm) => patch({ start_time: hhmm })}
            onReminders={(r) => setP((x) => x ? { ...x, logistics: { ...x.logistics, reminders: r } } : x)} />
          {p.days > 0 && <TrackCard p={p} onPatch={patch} />}
          <section aria-label="Friends racing">
            <p className="mb-2 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-wider text-(--text-muted)">Friends racing</p>
            <RacePeopleSection eventId={p.event.id} eventName={p.event.name} />
          </section>
        </>
      )}
    </Screen>
  )
}
