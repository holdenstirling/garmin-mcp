// Progress recovery from the athlete's chosen source (Me -> Connected apps -> Oura): readiness,
// HRV and resting HR from the recovery source, sleep from the sleep source. With "Show both",
// a compact Garmin vs Oura table instead. App-only: Oura numbers never reach Rabbit's AI.
import { useEffect, useState } from 'react'
import { ChevronDown, HeartPulse } from 'lucide-react'
import { ErrorState } from '@/components/ui/ErrorState'
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
  return <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{children}</h3>
}

/** Progress: recovery as one tappable row ("Recovery · Garmin · readiness 72 · sleep 7.4 h")
 *  that expands to the full view. */
export function RecoveryRow({ source, summary, open, onToggle }: {
  source: string; summary: string; open: boolean; onToggle: () => void
}) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open}
      className="flex min-h-11 w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
      <HeartPulse className="size-4 shrink-0 text-(--accent)" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block text-[0.7647rem] font-medium text-(--text)">Recovery · {source}</span>
        <span className="block truncate text-[0.7059rem] text-(--text-muted)">{summary}</span>
      </span>
      <ChevronDown className={cn('size-4 shrink-0 text-(--text-muted) transition-transform', open && 'rotate-180')} aria-hidden />
    </button>
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
    <p className="px-1 text-[0.6471rem] text-(--text-muted)">
      Workouts come from Garmin only.{usesOura ? ' Oura data is shown here only and never sent to Rabbit.' : ''} Change in Settings → Data sources.
    </p>
  )

  const rec: DataSource = r.oura_connected ? r.sources.recovery : 'garmin'
  const slp: DataSource = r.oura_connected ? r.sources.sleep : 'garmin'
  const a = pick(rec), s = pick(slp)
  const wrap = (full: React.ReactNode) => {
    if (!compact) return full
    const bits = [a?.readiness != null ? `Readiness ${a.readiness}` : null, s?.sleep_hours != null ? `Sleep ${s.sleep_hours} h` : null,
      a?.hrv != null ? `HRV ${a.hrv} ms` : null].filter(Boolean)
    return (
      <section className="flex flex-col gap-2">
        <RecoveryRow source={`${SOURCE_NAME[rec]}${a ? ` · ${day(a)}` : ''}`} summary={bits.join(' · ') || 'Tap for details'}
          open={open} onToggle={() => setOpen((o) => !o)} />
        {open && full}
      </section>
    )
  }

  if (r.sources.show_both && r.oura_connected) {
    const g = latest(r.garmin), o = latest(r.oura)
    if (!g && !o) return null
    return wrap(
      <section className="flex flex-col gap-2" aria-label="Recovery, Garmin and Oura">
        <Label>Recovery · Garmin vs Oura</Label>
        <div className="overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
          <table className="w-full text-left text-[0.7647rem]">
            <thead>
              <tr className="text-[0.6471rem] text-(--text-muted)">
                <th scope="col" className="px-3 py-2 font-medium"><span className="sr-only">Measure</span></th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Garmin{g ? ` · ${day(g)}` : ''}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Oura{o ? ` · ${day(o)}` : ''}</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([k, label]) => (
                <tr key={k} className="border-t border-(--border)">
                  <th scope="row" className="px-3 py-2 font-normal text-(--text-muted)">{label}</th>
                  <td className="px-3 py-2 text-right tabular-nums text-(--text)">{fmt[k](g)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-(--text)">{fmt[k](o)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="px-1 text-[0.6471rem] text-(--text-muted)">Each device scores differently, so expect gaps. Rabbit plans from {SOURCE_NAME[r.sources.recovery]}.</p>
        {foot}
      </section>
    )
  }

  if (!a && !s) return null
  const tiles: [string, string, string | null][] = [
    [`${SOURCE_NAME[rec]} readiness`, fmt.readiness(a), rec === 'oura' ? 'oura_readiness' : 'garmin_readiness'],
    ['HRV', fmt.hrv(a), null],
    ['Resting HR', fmt.resting_hr(a), null],
    [slp === rec ? 'Sleep' : `Sleep · ${SOURCE_NAME[slp]}`, fmt.sleep_hours(s), null],
  ]
  return wrap(
    <section className="flex flex-col gap-2">
      {!compact && <Label>Recovery · {SOURCE_NAME[rec]}{a ? ` · ${day(a)}` : ''}</Label>}
      <div className="grid grid-cols-2 gap-1.5">
        {tiles.map(([label, v, term]) => (
          <div key={label} className="rounded-xl border border-(--border) bg-(--bg-surface) px-2 py-2.5 text-center">
            <span className="flex items-center justify-center gap-1 text-[0.6471rem] text-(--text-muted)">
              {label}{term && <InfoTip term={term as 'oura_readiness' | 'garmin_readiness'} />}
            </span>
            <span className="mt-0.5 block font-display text-[1.05rem] leading-tight text-(--text)">{v}</span>
          </div>
        ))}
      </div>
      {foot}
    </section>
  )
}
