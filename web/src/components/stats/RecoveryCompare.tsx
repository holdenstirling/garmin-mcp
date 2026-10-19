// Progress recovery from the athlete's chosen source (Me -> Connected apps -> Oura): readiness,
// HRV and resting HR from the recovery source, sleep from the sleep source. With "Show both",
// a compact Garmin vs Oura table instead. App-only: Oura numbers never reach Rabbit's AI.
import { useEffect, useState } from 'react'
import { ChevronDown, HeartPulse } from 'lucide-react'
import { ErrorState } from '@/components/ui/ErrorState'
import { Section } from '@/components/ui/section'
import { InfoTip } from '@/components/ui/InfoTip'
import { cn } from '@/lib/utils'
import { useTrackRefresh } from './refresh'
import { getRecovery, SOURCE_NAME, type DataSource, type RecoveryBoth, type RecoveryData } from '@/lib/sources'

type Day = NonNullable<RecoveryData['latest']>

const fmt = {
  readiness: (d?: Day | null) => (d?.readiness != null ? String(d.readiness) : '–'),
  sleep_score: (d?: Day | null) => (d?.sleep_score != null ? String(d.sleep_score) : '–'),
  hrv: (d?: Day | null) => (d?.hrv != null ? `${d.hrv} ms` : '–'),
  resting_hr: (d?: Day | null) => (d?.resting_hr != null ? `${d.resting_hr} bpm` : '–'),
  sleep_hours: (d?: Day | null) => (d?.sleep_hours != null ? `${d.sleep_hours} h` : '–'),
}
const ROWS: [keyof typeof fmt, string][] = [
  ['readiness', 'Readiness'], ['sleep_score', 'Sleep score'], ['sleep_hours', 'Sleep'], ['hrv', 'HRV'], ['resting_hr', 'Resting HR'],
]

const latest = (r: RecoveryData | null | undefined): Day | null =>
  r?.latest ?? (r?.days?.length ? r.days[r.days.length - 1]! : null)
const day = (d: Day | null) => (d ? new Date(`${d.date}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '')

function Label({ children }: { children: React.ReactNode }) {
  return <h3 className="section-title section-title--sm m-0 px-1">{children}</h3>
}

/** Progress: the Recovery section. Up to three labeled numbers (readiness, sleep, HRV) in one
 *  card that expands to the full view (``children``). */
export function RecoveryRow({ source, stats, open, onToggle, children }: {
  /** where and when, e.g. "From Garmin, Oct 18" */
  source: string
  stats: [string, string][]
  open: boolean; onToggle: () => void
  children?: React.ReactNode
}) {
  return (
    <Section title="Recovery" description={source}>
      <button type="button" onClick={onToggle} aria-expanded={open}
        className="flex w-full flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3.5 text-left active:bg-(--bg-inset)">
        <span className="flex w-full items-start gap-3">
          <HeartPulse className="mt-1 size-5 shrink-0 text-(--accent)" aria-hidden />
          <span className="grid min-w-0 flex-1 grid-cols-3 gap-2">
            {stats.map(([label, v]) => (
              <span key={label} className="min-w-0">
                <span className="block text-meta text-(--text-secondary)">{label}</span>
                <span className="block text-title-sm font-semibold leading-tight text-(--text)">{v}</span>
              </span>
            ))}
          </span>
        </span>
        <span className="flex items-center gap-1 self-end text-small font-medium text-(--accent)">
          {open ? 'Hide details' : 'Details'}
          <ChevronDown className={cn('size-5 shrink-0 transition-transform', open && 'rotate-180')} aria-hidden />
        </span>
      </button>
      {open && children}
    </Section>
  )
}

export function RecoveryCompare({ loadKey = 0, compact = false }: {
  /** bump to re-read (Progress refresh) */
  loadKey?: number
  /** one row that expands (Progress) */
  compact?: boolean
} = {}) {
  const [r, setR] = useState<RecoveryBoth | null>(null)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [open, setOpen] = useState(false)
  const track = useTrackRefresh()
  useEffect(() => {
    let live = true
    setError(false)
    track(getRecovery().then((x) => { if (live) setR(x) }, () => { if (live) setError(true) }))
    return () => { live = false }
  }, [attempt, loadKey, track])
  if (error && !r) return <ErrorState compact message="Couldn't load your recovery." onRetry={() => setAttempt((n) => n + 1)} />
  if (!r) return null
  const pick = (s: DataSource) => latest(s === 'oura' ? r.oura : r.garmin)
  const usesOura = r.oura_connected && (r.sources.show_both || r.sources.recovery === 'oura' || r.sources.sleep === 'oura')
  const foot = (
    <p className="px-1 text-small leading-snug text-(--text-secondary)">
      Stats and your plan count Garmin workouts; a workout two apps recorded counts once.{usesOura ? ' Oura data is shown here only and never sent to rabbt.' : ''} Change this in Settings, Data sources.
    </p>
  )

  const rec: DataSource = r.oura_connected ? r.sources.recovery : 'garmin'
  const slp: DataSource = r.oura_connected ? r.sources.sleep : 'garmin'
  const a = pick(rec), s = pick(slp)
  const wrap = (full: React.ReactNode) => {
    if (!compact) return full
    const stats: [string, string][] = [['Readiness', fmt.readiness(a)], ['Sleep', fmt.sleep_hours(s)], ['HRV', fmt.hrv(a)]]
    return (
      <RecoveryRow source={`From ${SOURCE_NAME[rec]}${a ? `, ${day(a)}` : ''}`} stats={stats}
        open={open} onToggle={() => setOpen((o) => !o)}>{full}</RecoveryRow>
    )
  }

  if (r.sources.show_both && r.oura_connected) {
    const g = latest(r.garmin), o = latest(r.oura)
    if (!g && !o) return null
    return wrap(
      <section className="flex flex-col gap-2" aria-label="Recovery, Garmin and Oura">
        <Label>Garmin and Oura side by side</Label>
        <div className="overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
          <table className="w-full text-left text-body">
            <thead>
              <tr className="text-meta text-(--text-secondary)">
                <th scope="col" className="px-3 py-2.5 font-medium"><span className="sr-only">Measure</span></th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Garmin{g ? <span className="block font-normal">{day(g)}</span> : null}</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Oura{o ? <span className="block font-normal">{day(o)}</span> : null}</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([k, label]) => (
                <tr key={k} className="border-t border-(--border)">
                  <th scope="row" className="px-3 py-2.5 font-normal text-(--text-secondary)">{label}</th>
                  <td className="px-3 py-2.5 text-right tabular-nums text-(--text)">{fmt[k](g)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-(--text)">{fmt[k](o)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="px-1 text-small text-(--text-secondary)">Each device scores differently, so expect gaps. rabbt plans from {SOURCE_NAME[r.sources.recovery]}.</p>
        {foot}
      </section>
    )
  }

  if (!a && !s) return null
  const tiles: [string, string, string | null][] = [
    [`${SOURCE_NAME[rec]} readiness`, fmt.readiness(a), rec === 'oura' ? 'oura_readiness' : 'garmin_readiness'],
    ['HRV', fmt.hrv(a), null],
    ['Resting HR', fmt.resting_hr(a), null],
    [slp === rec ? 'Sleep' : `Sleep (${SOURCE_NAME[slp]})`, fmt.sleep_hours(s), null],
  ]
  return wrap(
    <section className="flex flex-col gap-2">
      {!compact && <Label>Recovery from {SOURCE_NAME[rec]}{a ? `, ${day(a)}` : ''}</Label>}
      <div className="grid grid-cols-2 gap-3">
        {tiles.map(([label, v, term]) => (
          <div key={label} className="rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-3 text-center">
            <span className="flex items-center justify-center gap-1 text-meta text-(--text-secondary)">
              {label}{term && <InfoTip term={term as 'oura_readiness' | 'garmin_readiness'} />}
            </span>
            <span className="mt-1 block font-display text-title leading-tight text-(--text)">{v}</span>
          </div>
        ))}
      </div>
      {foot}
    </section>
  )
}
