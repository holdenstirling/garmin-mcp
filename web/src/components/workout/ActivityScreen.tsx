// The page for one recorded workout (server: activitypage.py): key numbers, laps, time in heart-
// rate zones, the plan session it counted for ("How it went"), your check-in and Rabbit's
// feedback. Opened from anywhere a finished workout shows (lib/activitynav openActivity).
// Workouts another app recorded (Oura) are display-only: no "Ask Rabbit" for them.
import { RabbitInline } from '@/components/chat/RabbitText'
import { useCallback, useEffect, useState } from 'react'
import { Activity, Bike, CalendarDays, ExternalLink, Footprints, HeartPulse, MessageCircle, Mountain, Sparkles, Waves } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { shareToFriends } from '@/lib/dm'
import { ShareButton } from '@/components/ui/ShareSheet'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Screen } from '@/components/plan/ui'
import { fmtDay } from '@/components/plan/PlanParts'
import { HowItWent } from '@/components/plan/WorkoutTargets'
import { ShareWorkoutButton } from '@/components/community/ShareWorkout'
import { FEELS, Hero, RPE_WORD, SectionCard, TONE } from './WorkoutDayScreen'
import { checkinRef, getActivity, type ActivityView } from '@/lib/activitypage'
import { checkinChips, createCheckin } from '@/lib/checkins'
import { fmtDist, fmtDuration, fmtPaceKm, fmtSpeed, fmtSwim100 } from '@/lib/format'
import { openWorkout } from '@/lib/workoutnav'
import { cn } from '@/lib/utils'

const ICON: Record<string, typeof Bike> = { run: Footprints, walk: Footprints, hike: Mountain, bike: Bike, swim: Waves }
const SOURCE: Record<string, string> = { garmin: 'Garmin', oura: 'Oura', whoop: 'WHOOP', coros: 'COROS', apple: 'Apple Watch' }
const LOADING = ['Pulling up your workout…', 'Counting the laps…', 'Reading your heart rate…']

const hms = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.round(s % 60)
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`
}
const distSport = (sport: string) => (sport === 'swim' ? 'swim' : sport === 'bike' ? 'bike' : 'run')

export function ActivityScreen({ id, imperial, onClose, onAsk }: {
  id: string; imperial: boolean; onClose: () => void; onAsk?: (text: string) => void
}) {
  const [v, setV] = useState<ActivityView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const load = useCallback(() => { setError(null); getActivity(id).then(setV, (e: Error) => setError(e.message)) }, [id])
  useEffect(() => { load() }, [load])
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }

  const when = v?.start ? `${fmtDay(v.start.slice(0, 10), { weekday: 'long', month: 'short', day: 'numeric' })}${v.start.length > 11 ? ` · ${new Date(v.start.replace(' ', 'T')).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}` : ''}` : undefined
  const ask = onAsk && v?.ai ? () => onAsk(askText(v, imperial)) : undefined

  return (
    <Screen title={v?.name ?? 'Workout'} subtitle={when} onClose={close} closing={closing}
      footer={v ? (
        <>
          {typeof v.id === 'number' && <div className="flex-1"><ShareWorkoutButton activityId={v.id} /></div>}
          {v.key && (
            <ShareButton iconOnly hrOption={v.source === 'garmin'} target={{ kind: 'activity', ref: String(v.key), label: v.name ?? 'Workout' }}
              onSendInRabbit={typeof v.id === 'number'
                ? () => shareToFriends({ type: 'workout', ref: { kind: 'activity', id: String(v.id) }, label: v.name ?? 'Workout' })
                : undefined} />
          )}
          {ask && (
            <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={ask}>
              <MessageCircle className="size-4" aria-hidden /> Ask Rabbit
            </Button>
          )}
        </>
      ) : undefined}>
      {!v && !error && (
        <div className="flex flex-col gap-3" aria-busy="true">
          <div className="skeleton h-[112px] rounded-2xl" aria-hidden />
          <div className="skeleton h-[150px] rounded-xl" aria-hidden />
          <div className="skeleton h-[200px] rounded-xl" aria-hidden />
          <RabbitLoader className="py-4" label="Loading your workout" cycle={LOADING} />
        </div>
      )}
      {error && (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <p className="text-[0.8235rem] text-(--text-muted)">{error}</p>
          <Button variant="default" onClick={load}>Try again</Button>
        </div>
      )}
      {v && <ActivityBody v={v} imperial={imperial} onAsk={ask} onSaved={load} onClose={close} />}
    </Screen>
  )
}

function ActivityBody({ v, imperial, onAsk, onSaved, onClose }: {
  v: ActivityView; imperial: boolean; onAsk?: () => void; onSaved: () => void; onClose: () => void
}) {
  const n = v.numbers
  const ds = distSport(v.sport)
  const metaBits = [n.km ? fmtDist(n.km, imperial, ds) : '', n.moving_s ? fmtDuration(Math.round(n.moving_s / 60)) : '', `via ${SOURCE[v.source] ?? v.source}`]
  const stats: [string, string][] = []
  if (n.km) stats.push(['Distance', fmtDist(n.km, imperial, ds)])
  if (n.moving_s) stats.push(['Moving time', hms(n.moving_s)])
  if (n.elapsed_s && n.moving_s && Math.abs(n.elapsed_s - n.moving_s) > 30) stats.push(['Elapsed', hms(n.elapsed_s)])
  if (n.pace_s_per_km) stats.push(['Avg pace', fmtPaceKm(n.pace_s_per_km, imperial)])
  if (n.pace_s_per_100m) stats.push(['Avg pace', fmtSwim100(n.pace_s_per_100m, imperial)])
  if (n.speed_kmh && !n.pace_s_per_km && !n.pace_s_per_100m) stats.push(['Avg speed', fmtSpeed(n.speed_kmh, imperial)])
  if (n.avg_hr) stats.push(['Avg HR', `${Math.round(n.avg_hr)} bpm`])
  if (n.max_hr) stats.push(['Max HR', `${Math.round(n.max_hr)} bpm`])
  if (n.cadence) stats.push(['Cadence', `${n.cadence} ${n.cadence_unit ?? ''}`.trim()])
  if (n.elevation_gain_m) stats.push(['Climb', imperial ? `${Math.round(n.elevation_gain_m * 3.28084)} ft` : `${Math.round(n.elevation_gain_m)} m`])
  if (n.avg_power_w) stats.push(['Avg power', `${Math.round(n.avg_power_w)} W`])
  if (n.norm_power_w) stats.push(['Norm. power', `${Math.round(n.norm_power_w)} W`])
  if (n.swolf) stats.push(['SWOLF', String(Math.round(n.swolf))])
  if (n.stroke_rate) stats.push(['Stroke rate', `${Math.round(n.stroke_rate)}/min`])
  if (n.calories) stats.push(['Calories', String(Math.round(n.calories))])
  if (n.training_load) stats.push(['Training load', String(Math.round(n.training_load))])
  if (n.aerobic_te) stats.push(['Aerobic effect', n.aerobic_te.toFixed(1)])
  if (n.anaerobic_te) stats.push(['Anaerobic effect', n.anaerobic_te.toFixed(1)])

  return (
    <>
      <Hero icon={ICON[v.sport] ?? Activity} title={v.name} meta={metaBits.filter(Boolean).join(' · ')}
        line={v.planned ? `Counted for your planned ${v.planned.title}.` : n.te_label ? `Garmin training effect: ${n.te_label.charAt(0) + n.te_label.slice(1).toLowerCase().replace(/_/g, ' ')}.` : ''}
        chip={{ label: 'Done', cls: 'bg-(--accent) text-(--on-fill)' }} />

      {v.planned && (
        <section aria-label="Planned workout" className="flex flex-col gap-2">
          {v.planned.went && <HowItWent w={v.planned.went} imperial={imperial} sport={v.sport} />}
          <Button variant="default" className="h-11 gap-1.5 self-start px-4 text-[0.8235rem]"
            onClick={() => { const p = v.planned!; onClose(); window.setTimeout(() => openWorkout(p.id, p.date), 220) }}>
            <CalendarDays className="size-4" aria-hidden /> See the planned {v.planned.title}
          </Button>
        </section>
      )}

      {stats.length > 0 && (
        <SectionCard title="Key numbers">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-3.5 pt-2 min-[400px]:grid-cols-3">
            {stats.map(([k, x]) => (
              <div key={k} className="min-w-0">
                <dt className="font-mono text-[0.6471rem] uppercase tracking-widest text-(--text-muted)">{k}</dt>
                <dd className="truncate font-mono text-[0.8824rem] font-semibold tabular-nums text-(--text)">{x}</dd>
              </div>
            ))}
          </dl>
        </SectionCard>
      )}

      {v.zones && <ZonesCard z={v.zones} />}
      {v.laps.length > 0 && <LapsCard laps={v.laps} imperial={imperial} sport={v.sport} />}
      <ActivityFeedback v={v} onAsk={onAsk} onSaved={onSaved} />
      {v.garmin_url && (
        <a href={v.garmin_url} target="_blank" rel="noopener noreferrer"
          className="flex min-h-11 items-center justify-center gap-1.5 text-[0.7647rem] font-medium text-(--accent)">
          <ExternalLink className="size-3.5" aria-hidden /> Open in Garmin Connect
        </a>
      )}
      {!v.ai && (
        <p className="px-1 text-[0.7059rem] text-(--text-muted)">
          Recorded by {SOURCE[v.source] ?? v.source}. Shown here for you only; Rabbit's AI doesn't use it.
        </p>
      )}
    </>
  )
}

function ZonesCard({ z }: { z: NonNullable<ActivityView['zones']> }) {
  const total = z.zones.reduce((a, b) => a + b.s, 0) || 1
  const COLORS = ['var(--bg-inset)', 'var(--accent-subtle)', 'color-mix(in oklab, var(--accent) 45%, transparent)', 'var(--warning)', 'var(--danger)']
  return (
    <SectionCard title="Time in heart-rate zones" icon={HeartPulse}>
      <div className="flex flex-col gap-2 px-3.5 pt-2">
        <div className="flex h-3 overflow-hidden rounded-full bg-(--bg-inset)" role="img"
          aria-label={z.zones.filter((x) => x.s).map((x) => `Zone ${x.zone} ${x.label}: ${Math.round(x.s / 60)} minutes`).join(', ')}>
          {z.zones.map((x, i) => x.s > 0 && <span key={x.zone} style={{ width: `${(x.s / total) * 100}%`, background: COLORS[i] }} />)}
        </div>
        <ul className="flex flex-col">
          {z.zones.map((x, i) => (
            <li key={x.zone} className="flex min-h-9 items-center gap-2 text-[0.7647rem]">
              <span className="size-2.5 shrink-0 rounded-full border border-(--border)" style={{ background: COLORS[i] }} aria-hidden />
              <span className="w-24 shrink-0 text-(--text)">Z{x.zone} {x.label}</span>
              <span className="flex-1 font-mono text-[0.7059rem] text-(--text-muted)">{x.low}–{x.high} bpm</span>
              <span className="font-mono tabular-nums text-(--text)">{x.s ? hms(x.s) : '–'}</span>
            </li>
          ))}
        </ul>
        {z.basis === 'average' && <p className="text-[0.7059rem] text-(--text-muted)">Estimate from your average heart rate (no laps with heart rate).</p>}
      </div>
    </SectionCard>
  )
}

function LapsCard({ laps, imperial, sport }: { laps: ActivityView['laps']; imperial: boolean; sport: string }) {
  const showHr = laps.some((l) => l.hr)
  const paced = sport === 'run' || sport === 'walk' || sport === 'hike'
  return (
    <SectionCard title={`Laps (${laps.length})`}>
      <div className="overflow-x-auto px-3.5 pt-2">
        <table className="w-full text-left text-[0.7647rem] tabular-nums">
          <thead className="font-mono text-[0.6471rem] uppercase tracking-widest text-(--text-muted)">
            <tr><th className="py-1 pr-2 font-semibold">#</th><th className="py-1 pr-2 font-semibold">Dist</th><th className="py-1 pr-2 font-semibold">Time</th>
              <th className="py-1 pr-2 font-semibold">{paced ? 'Pace' : 'Speed'}</th>{showHr && <th className="py-1 font-semibold">HR</th>}</tr>
          </thead>
          <tbody>
            {laps.map((l) => (
              <tr key={l.n} className="border-t border-(--border)">
                <td className="py-1.5 pr-2 text-(--text-muted)">{l.n}</td>
                <td className="py-1.5 pr-2">{fmtDist(l.km, imperial, distSport(sport))}</td>
                <td className="py-1.5 pr-2 font-mono">{hms(l.s)}</td>
                <td className="py-1.5 pr-2 font-mono">{paced ? fmtPaceKm(l.pace_s_per_km, imperial) : fmtSpeed(l.km / (l.s / 3600), imperial)}</td>
                {showHr && <td className="py-1.5 font-mono">{l.hr ?? '–'}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  )
}

function ActivityFeedback({ v, onAsk, onSaved }: { v: ActivityView; onAsk?: () => void; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [rpe, setRpe] = useState(5)
  const [feel, setFeel] = useState<(typeof FEELS)[number]['id'] | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const ck = v.checkin
  const fb = v.feedback
  const form = editing || !ck

  async function save() {
    setBusy(true); setErr(null)
    const f = FEELS.find((x) => x.id === feel)
    try {
      await createCheckin({ text: note.trim(), activity_id: checkinRef(String(v.key)), session_id: v.planned?.id,
        date: v.start?.slice(0, 10), rpe, feel: f?.feel, pain: feel === 'pain' })
      setEditing(false); setNote(''); onSaved()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <section aria-label="How did it go" className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
      <h4 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">How did it go?</h4>
      {ck && !editing && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1.5">
            {checkinChips(ck).map((x) => (
              <span key={x.label} className={cn('rounded-full border px-2 py-0.5 text-[0.7059rem] font-medium',
                x.warn ? 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)' : 'border-(--border) text-(--text)')}>{x.label}</span>
            ))}
          </div>
          {ck.text && <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">“{ck.text}”</p>}
          <button type="button" className="hit-44 self-start text-[0.7647rem] font-medium text-(--accent)" onClick={() => setEditing(true)}>Add another note</button>
        </div>
      )}
      {form && (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="flex items-baseline justify-between text-[0.7647rem] text-(--text)">
              <span>Effort (RPE)</span>
              <span className="font-mono font-semibold tabular-nums text-(--accent)" aria-hidden>{rpe}/10 · {RPE_WORD[rpe]}</span>
            </span>
            <input type="range" min={1} max={10} step={1} value={rpe} onChange={(e) => setRpe(Number(e.target.value))}
              aria-valuetext={`${rpe} out of 10, ${RPE_WORD[rpe]}`} className="h-11 w-full accent-(--accent)" />
          </label>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="How did it feel">
            {FEELS.map((f) => (
              <button key={f.id} type="button" role="radio" aria-checked={feel === f.id} onClick={() => setFeel(feel === f.id ? null : f.id)}
                className={cn('plan-chip min-h-11', feel === f.id && 'plan-chip--on', f.id === 'pain' && feel === f.id && 'border-(--danger) text-(--danger)')}>
                {f.label}
              </button>
            ))}
          </div>
          <textarea value={note} onChange={(e) => setNote(e.target.value.slice(0, 600))} rows={2} placeholder="Anything else? Legs, sleep, weather… (optional)"
            aria-label="Note about this workout"
            className="min-h-11 w-full rounded-md border border-input bg-transparent px-3 py-2 text-[0.8235rem] text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
          {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
          <div className="flex gap-2">
            <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy} onClick={() => void save()}>Save</Button>
            {editing && <Button variant="ghost" className="h-11 px-3 text-[0.8235rem]" onClick={() => setEditing(false)}>Cancel</Button>}
          </div>
        </div>
      )}
      {fb && (
        <div className={cn('flex flex-col gap-1.5 rounded-lg border px-3 py-2.5', TONE[fb.tone])} aria-live="polite">
          <p className="flex items-center gap-1.5 text-[0.8235rem] font-semibold text-(--text)"><Sparkles className="size-4 text-(--accent)" aria-hidden /> {fb.headline}</p>
          <div className="flex flex-col gap-1">
            {fb.lines.map((l) => <p key={l} className="m-0 text-[0.8235rem] leading-normal text-(--text-secondary)"><RabbitInline text={l} /></p>)}
          </div>
        </div>
      )}
      {onAsk && (
        <Button variant="default" className="h-11 gap-1.5 text-[0.8235rem]" onClick={onAsk}>
          <MessageCircle className="size-4" aria-hidden /> Ask Rabbit for feedback on this workout
        </Button>
      )}
    </section>
  )
}

/** The chat prefill: Garmin numbers and the athlete's own words only (never another app's data). */
function askText(v: ActivityView, imperial: boolean): string {
  const n = v.numbers
  const ds = distSport(v.sport)
  const bits = [n.km ? fmtDist(n.km, imperial, ds) : '', n.moving_s ? `in ${hms(n.moving_s)}` : '',
    n.pace_s_per_km ? `avg pace ${fmtPaceKm(n.pace_s_per_km, imperial)}` : '', n.avg_hr ? `avg HR ${Math.round(n.avg_hr)}` : '',
    n.max_hr ? `max HR ${Math.round(n.max_hr)}` : '', n.cadence ? `cadence ${n.cadence} ${n.cadence_unit ?? ''}`.trim() : '',
    n.avg_power_w ? `avg power ${Math.round(n.avg_power_w)} W` : ''].filter(Boolean).join(', ')
  const laps = v.laps.length >= 2 ? ` Laps: ${v.laps.slice(0, 12).map((l) => v.sport === 'run' ? fmtPaceKm(l.pace_s_per_km, imperial, false) : hms(l.s)).join(', ')}.` : ''
  const ck = v.checkin
  const words = [ck?.rpe != null ? `RPE ${ck.rpe}/10` : '', ck?.feel != null ? `felt ${ck.feel}/5` : '', ck?.pain_flag ? 'something hurt' : '', ck?.text ? `"${ck.text}"` : ''].filter(Boolean).join(', ')
  const day = v.start ? fmtDay(v.start.slice(0, 10), { weekday: 'long', month: 'short', day: 'numeric' }) : 'recently'
  return `Feedback on my ${v.name} (${day})${v.planned ? `, planned as ${v.planned.title}` : ''}: ${bits}.${laps}${words ? ` ${words}.` : ''} How did it go, and what should I change next time? `
}
