// Progress recovery from the athlete's chosen source (Settings -> Data sources): readiness,
// HRV and resting HR from the recovery source, sleep from the sleep source. With "Show both",
// a compact Garmin vs Oura table instead. App-only: Oura numbers never reach Rabbit's AI.
import { useEffect, useState } from 'react'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
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

export function RecoveryCompare() {
  const [r, setR] = useState<RecoveryBoth | null>(null)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let live = true
    setError(false)
    getRecovery().then((x) => { if (live) setR(x) }, () => { if (live) setError(true) })
    return () => { live = false }
  }, [attempt])
  if (error && !r) return <ErrorState compact message="Couldn't load your recovery." onRetry={() => setAttempt((n) => n + 1)} />
  if (!r) return null
  const pick = (s: DataSource) => latest(s === 'oura' ? r.oura : r.garmin)
  const usesOura = r.oura_connected && (r.sources.show_both || r.sources.recovery === 'oura' || r.sources.sleep === 'oura')
  const foot = (
    <p className="px-1 text-[0.6471rem] text-(--text-muted)">
      Workouts come from Garmin only.{usesOura ? ' Oura data is shown here only and never sent to Rabbit.' : ''} Change in Settings → Data sources.
    </p>
  )

  if (r.sources.show_both && r.oura_connected) {
    const g = latest(r.garmin), o = latest(r.oura)
    if (!g && !o) return null
    return (
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

  const rec: DataSource = r.oura_connected ? r.sources.recovery : 'garmin'
  const slp: DataSource = r.oura_connected ? r.sources.sleep : 'garmin'
  const a = pick(rec), s = pick(slp)
  if (!a && !s) return null
  const tiles: [string, string, string | null][] = [
    [`${SOURCE_NAME[rec]} readiness`, fmt.readiness(a), rec === 'oura' ? 'oura_readiness' : 'garmin_readiness'],
    ['HRV', fmt.hrv(a), null],
    ['Resting HR', fmt.resting_hr(a), null],
    [slp === rec ? 'Sleep' : `Sleep · ${SOURCE_NAME[slp]}`, fmt.sleep_hours(s), null],
  ]
  return (
    <section className="flex flex-col gap-2">
      <Label>Recovery · {SOURCE_NAME[rec]}{a ? ` · ${day(a)}` : ''}</Label>
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
