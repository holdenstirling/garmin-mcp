// Fitness, fatigue and form over the last 90 days and (with a plan) forward to race day.
import { useEffect, useMemo, useState } from 'react'
import { Card } from '@/components/plan/ui'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import type { Term } from '@/lib/glossary'
import { getLoad, type Load } from '@/lib/load'
import { useTrackRefresh } from './refresh'

const W = 360, H = 186, BAND = 18, TOP = 108, PAD = 4

export function LoadCard({ base = '/api' }: { base?: string }) {
  const [l, setL] = useState<Load | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const track = useTrackRefresh()
  useEffect(() => {
    let live = true
    setError(null)
    track(getLoad(base).then((x) => { if (live) setL(x) }, (e) => { if (live) setError((e as Error).message) }))
    return () => { live = false }
  }, [base, attempt, track])
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-sans px-1 text-caption font-semibold text-(--text-muted)">Fitness & form{l?.has_plan ? ' · forecast to race day' : ''}</h2>
      {error && !l ? <ErrorState compact message="Couldn't load your fitness chart." onRetry={() => setAttempt((n) => n + 1)} /> : (
      <Card className="p-4">
        {l && <Legend />}
        {!l ? <div className="skeleton h-[186px]" role="status" aria-label="Loading fitness chart" /> : <Chart l={l} />}
        {l && (
          <>
            <div className="mt-2 grid grid-cols-3 gap-2 text-center">
              <Stat label="Fitness" term="fitness" value={l.now?.ctl} color="var(--accent)" />
              <Stat label="Fatigue" term="fatigue" value={l.now?.atl} color="var(--chart-fatigue)" />
              <Stat label="Form" term="form" value={l.now?.tsb} color="var(--text)" signed />
            </div>
            <p className="mt-3 text-small leading-snug text-(--text-secondary)">{l.advice}</p>
            <p className="mt-1 text-caption text-(--text-muted)">Dashed lines: what your plan adds.</p>
          </>
        )}
      </Card>
      )}
    </section>
  )
}

function Legend() {
  const item = (swatch: React.ReactNode, label: string) => (
    <span className="flex items-center gap-1.5 text-caption text-(--text-muted)">{swatch}{label}</span>
  )
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1">
      {item(<span className="h-[3px] w-4 rounded-full bg-(--accent)" />, 'Fitness')}
      {item(<span className="h-[2px] w-4 rounded-full bg-(--chart-fatigue)" />, 'Fatigue')}
      {item(<span className="flex items-end gap-px"><span className="h-2 w-1 bg-(--accent) opacity-60" /><span className="h-1 w-1 bg-(--chart-form) opacity-60" /></span>, 'Form (fresh up, tired down)')}
    </div>
  )
}

function Stat({ label, term, value, color, signed }: { label: string; term: Term; value?: number; color: string; signed?: boolean }) {
  return (
    <div>
      <span className="flex items-center justify-center gap-1 text-caption text-(--text-muted)">{label}<InfoTip term={term} /></span>
      <span className="font-display text-title" style={{ color }}>{value == null ? '–' : `${signed && value > 0 ? '+' : ''}${Math.round(value)}`}</span>
    </div>
  )
}

function Chart({ l }: { l: Load }) {
  const s = l.series
  const geo = useMemo(() => {
    const maxY = Math.max(10, ...s.map((p) => Math.max(p.ctl, p.atl))) * 1.1
    const maxT = Math.max(10, ...s.map((p) => Math.abs(p.tsb)))
    const x = (i: number) => PAD + (i / Math.max(1, s.length - 1)) * (W - 2 * PAD)
    const y = (v: number) => TOP - 4 - (v / maxY) * (TOP - BAND - 8)
    const zero = TOP + 6 + (H - TOP - 6) / 2
    const ty = (v: number) => zero - (v / maxT) * ((H - TOP - 6) / 2 - 3)
    const path = (key: 'ctl' | 'atl', planned: boolean) => {
      let d = '', pen = false
      s.forEach((p, i) => {
        const on = planned ? (p.planned || s[i + 1]?.planned) : !p.planned
        if (!on) { pen = false; return }
        d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`
        pen = true
      })
      return d
    }
    return { x, y, ty, zero, path, todayIdx: s.findIndex((p) => p.date === l.today), raceIdx: s.findIndex((p) => p.date === l.race_date) }
  }, [s, l.today, l.race_date])
  const bw = Math.max(1, (W - 2 * PAD) / s.length - 0.6)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Fitness, fatigue and form chart">
      <line x1={0} x2={W} y1={TOP + 2} y2={TOP + 2} stroke="var(--border)" strokeWidth={0.6} strokeDasharray="1 3" />
      <line x1={0} x2={W} y1={geo.zero} y2={geo.zero} stroke="var(--border)" strokeWidth={0.8} />
      {s.map((p, i) => (
        <rect key={p.date} x={geo.x(i) - bw / 2} width={bw} y={Math.min(geo.zero, geo.ty(p.tsb))} height={Math.abs(geo.ty(p.tsb) - geo.zero)}
          fill={p.tsb >= 0 ? 'var(--accent)' : 'var(--chart-form)'} opacity={p.planned ? 0.3 : 0.6} />
      ))}
      <path d={geo.path('atl', false)} fill="none" stroke="var(--chart-fatigue)" strokeWidth={1.4} />
      <path d={geo.path('atl', true)} fill="none" stroke="var(--chart-fatigue)" strokeWidth={1.4} strokeDasharray="3 3" opacity={0.7} />
      <path d={geo.path('ctl', false)} fill="none" stroke="var(--accent)" strokeWidth={2.2} />
      <path d={geo.path('ctl', true)} fill="none" stroke="var(--accent)" strokeWidth={2.2} strokeDasharray="4 3" />
      {geo.todayIdx >= 0 && <line x1={geo.x(geo.todayIdx)} x2={geo.x(geo.todayIdx)} y1={BAND} y2={H} stroke="var(--text-muted)" strokeWidth={0.8} strokeDasharray="2 2" />}
      {geo.todayIdx >= 0 && (
        <text x={geo.x(geo.todayIdx)} y={12} fontSize={11} textAnchor={geo.todayIdx > s.length * 0.85 ? 'end' : 'middle'} fill="var(--text-muted)">today</text>
      )}
      {geo.raceIdx >= 0 && (
        <>
          <line x1={geo.x(geo.raceIdx)} x2={geo.x(geo.raceIdx)} y1={BAND} y2={H} stroke="var(--brand)" strokeWidth={1.2} />
          <text x={geo.x(geo.raceIdx)} y={12} fontSize={11} textAnchor="end" fill="var(--brand)">race</text>
        </>
      )}
    </svg>
  )
}
