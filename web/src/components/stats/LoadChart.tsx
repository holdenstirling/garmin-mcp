// Fitness, fatigue and form over the last 90 days and (with a plan) forward to race day.
import { useEffect, useMemo, useState } from 'react'
import { Card } from '@/components/plan/ui'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import type { Term } from '@/lib/glossary'
import { getLoad, type Load } from '@/lib/load'
import { useTrackRefresh } from './refresh'
import { useWidth } from './useWidth'
import { Section } from '@/components/ui/section'

const H = 200, BAND = 24, TOP = 116, PAD = 4

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
    <Section title="Fitness and form" description={l?.has_plan ? 'The last 90 days, and what your plan adds through race day.' : 'The last 90 days.'}>
      {error && !l ? <ErrorState compact message="Couldn't load your fitness chart." onRetry={() => setAttempt((n) => n + 1)} /> : (
      <Card className="p-4">
        {l && (
          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat label="Fitness" term="fitness" value={l.now?.ctl} color="var(--accent)" />
            <Stat label="Fatigue" term="fatigue" value={l.now?.atl} color="var(--chart-fatigue)" />
            <Stat label="Form" term="form" value={l.now?.tsb} color="var(--text)" signed />
          </div>
        )}
        {l && <p className="mt-3 text-body leading-snug text-(--text)">{l.advice}</p>}
        {l && <Legend />}
        {!l ? <div className="skeleton h-[200px]" role="status" aria-label="Loading fitness chart" /> : <Chart l={l} />}
        {l?.has_plan && <p className="mt-2 text-small text-(--text-secondary)">Dashed lines: what your plan adds.</p>}
      </Card>
      )}
    </Section>
  )
}

function Legend() {
  const item = (swatch: React.ReactNode, label: string) => (
    <span className="flex items-center gap-2 text-small text-(--text-secondary)">{swatch}{label}</span>
  )
  return (
    <div className="mb-2 mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {item(<span className="h-[3px] w-5 rounded-full bg-(--accent)" />, 'Fitness')}
      {item(<span className="h-[2px] w-5 rounded-full bg-(--chart-fatigue)" />, 'Fatigue')}
      {item(<span className="flex items-end gap-px"><span className="h-2.5 w-1.5 bg-(--accent) opacity-60" /><span className="h-1.5 w-1.5 bg-(--chart-form) opacity-60" /></span>, 'Form: fresh above the line, tired below')}
    </div>
  )
}

function Stat({ label, term, value, color, signed }: { label: string; term: Term; value?: number; color: string; signed?: boolean }) {
  return (
    <div>
      <span className="flex items-center justify-center gap-1 text-small text-(--text-secondary)">{label}<InfoTip term={term} /></span>
      <span className="font-display text-title-md" style={{ color }}>{value == null ? '–' : `${signed && value > 0 ? '+' : ''}${Math.round(value)}`}</span>
    </div>
  )
}

function Chart({ l }: { l: Load }) {
  const [box, W] = useWidth<HTMLDivElement>(300)
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
  }, [s, l.today, l.race_date, W])
  const bw = Math.max(1, (W - 2 * PAD) / s.length - 0.6)
  return (
    <div ref={box}>
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img" aria-label="Fitness, fatigue and form chart">
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
        <text x={geo.x(geo.todayIdx)} y={15} fontSize={13} textAnchor={geo.todayIdx > s.length * 0.85 ? 'end' : 'middle'} fill="var(--text-secondary)">Today</text>
      )}
      {geo.raceIdx >= 0 && (
        <>
          <line x1={geo.x(geo.raceIdx)} x2={geo.x(geo.raceIdx)} y1={BAND} y2={H} stroke="var(--brand)" strokeWidth={1.2} />
          <text x={geo.x(geo.raceIdx)} y={15} fontSize={13} fontWeight={600} textAnchor="end" fill="var(--brand)">Race</text>
        </>
      )}
    </svg>
    </div>
  )
}
