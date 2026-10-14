// Fitness, fatigue and form over the last 90 days and (with a plan) forward to race day.
import { useEffect, useMemo, useState } from 'react'
import { Card } from '@/components/plan/ui'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import type { Term } from '@/lib/glossary'
import { getLoad, type Load } from '@/lib/load'

const W = 360, H = 170, TOP = 96, PAD = 4

export function LoadCard({ base = '/api' }: { base?: string }) {
  const [l, setL] = useState<Load | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let live = true
    setError(null)
    getLoad(base).then((x) => { if (live) setL(x) }, (e) => { if (live) setError((e as Error).message) })
    return () => { live = false }
  }, [base, attempt])
  return (
    <section className="flex flex-col gap-2">
      <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Fitness & form{l?.has_plan ? ' · forecast to race day' : ''}</h3>
      {error && !l ? <ErrorState compact message="Couldn't load your fitness chart." onRetry={() => setAttempt((n) => n + 1)} /> : (
      <Card className="p-4">
        {!l ? <div className="skeleton h-[170px]" role="status" aria-label="Loading fitness chart" /> : <Chart l={l} />}
        {l && (
          <>
            <div className="mt-2 grid grid-cols-3 gap-2 text-center">
              <Stat label="Fitness" term="fitness" value={l.now?.ctl} color="var(--accent)" />
              <Stat label="Fatigue" term="fatigue" value={l.now?.atl} color="var(--chart-fatigue)" />
              <Stat label="Form" term="form" value={l.now?.tsb} color="var(--text)" signed />
            </div>
            <p className="mt-3 text-[0.7647rem] leading-snug text-(--text-secondary)">{l.advice}</p>
            <p className="mt-1 text-[0.6471rem] text-(--text-muted)">Dashed lines: what your plan adds.</p>
          </>
        )}
      </Card>
      )}
    </section>
  )
}

function Stat({ label, term, value, color, signed }: { label: string; term: Term; value?: number; color: string; signed?: boolean }) {
  return (
    <div>
      <span className="flex items-center justify-center gap-1 text-[0.6471rem] text-(--text-muted)">{label}<InfoTip term={term} /></span>
      <span className="font-display text-[1.2rem]" style={{ color }}>{value == null ? '–' : `${signed && value > 0 ? '+' : ''}${Math.round(value)}`}</span>
    </div>
  )
}

function Chart({ l }: { l: Load }) {
  const s = l.series
  const geo = useMemo(() => {
    const maxY = Math.max(10, ...s.map((p) => Math.max(p.ctl, p.atl))) * 1.1
    const maxT = Math.max(10, ...s.map((p) => Math.abs(p.tsb)))
    const x = (i: number) => PAD + (i / Math.max(1, s.length - 1)) * (W - 2 * PAD)
    const y = (v: number) => TOP - (v / maxY) * (TOP - 8)
    const zero = TOP + (H - TOP) / 2
    const ty = (v: number) => zero - (v / maxT) * ((H - TOP) / 2 - 4)
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
      <line x1={0} x2={W} y1={geo.zero} y2={geo.zero} stroke="var(--border)" strokeWidth={0.8} />
      {s.map((p, i) => (
        <rect key={p.date} x={geo.x(i) - bw / 2} width={bw} y={Math.min(geo.zero, geo.ty(p.tsb))} height={Math.abs(geo.ty(p.tsb) - geo.zero)}
          fill={p.tsb >= 0 ? 'var(--accent)' : 'var(--chart-form)'} opacity={p.planned ? 0.3 : 0.6} />
      ))}
      <path d={geo.path('atl', false)} fill="none" stroke="var(--chart-fatigue)" strokeWidth={1.4} />
      <path d={geo.path('atl', true)} fill="none" stroke="var(--chart-fatigue)" strokeWidth={1.4} strokeDasharray="3 3" opacity={0.7} />
      <path d={geo.path('ctl', false)} fill="none" stroke="var(--accent)" strokeWidth={2.2} />
      <path d={geo.path('ctl', true)} fill="none" stroke="var(--accent)" strokeWidth={2.2} strokeDasharray="4 3" />
      {geo.todayIdx >= 0 && <line x1={geo.x(geo.todayIdx)} x2={geo.x(geo.todayIdx)} y1={4} y2={H} stroke="var(--text-muted)" strokeWidth={0.8} strokeDasharray="2 2" />}
      {geo.todayIdx >= 0 && <text x={geo.x(geo.todayIdx) + 3} y={13} fontSize={10} fill="var(--text-muted)">today</text>}
      {geo.raceIdx >= 0 && (
        <>
          <line x1={geo.x(geo.raceIdx)} x2={geo.x(geo.raceIdx)} y1={4} y2={H} stroke="var(--brand)" strokeWidth={1.2} />
          <text x={geo.x(geo.raceIdx) - 3} y={13} fontSize={10} textAnchor="end" fill="var(--brand)">race</text>
        </>
      )}
      <text x={PAD} y={TOP + 12} fontSize={10} fill="var(--text-muted)">form</text>
    </svg>
  )
}
