// Progress trends (server: trends.py): three small charts, one at a time.
//   Distance:  km/mi per week for 16 weeks (columns), the plan's goal as a tick on each week.
//   Easy pace: pace at the same heart rate on easy runs (faster is up).
//   Sleep:     nightly sleep over the training load of the day before (two charts, one x axis,
//              never two y-scales on one plot).
// Each has a one-line takeaway, a "Why it matters" tip and a table view. Tap or arrow-key a
// week/day to read its value (the readout line); the latest is selected by default. Plain SVG,
// CSS-var colors, so light and dark both work.
import { useEffect, useMemo, useState } from 'react'
import { ChevronRight, Table2 } from 'lucide-react'
import { InfoTip } from '@/components/ui/InfoTip'
import { cn } from '@/lib/utils'
import { KM_PER_MI, YD_PER_M } from '@/lib/format'
import { getTrends, type DistSport, type Trends } from '@/lib/trends'
import { useTrackRefresh } from '@/components/stats/refresh'

type View = 'distance' | 'pace' | 'sleep'
const W = 320, H = 140, PAD_L = 40, PAD_R = 8, PAD_T = 10, PAD_B = 24
const SPORT_LABEL = { run: 'Run', bike: 'Ride', swim: 'Swim' } as const

const shortDate = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

function unitVal(km: number, imperial: boolean, sport: string) {
  if (sport === 'swim') return km * 1000 * (imperial ? YD_PER_M : 1)
  return imperial ? km / KM_PER_MI : km
}
function unitWord(imperial: boolean, sport: string) { return sport === 'swim' ? (imperial ? 'yd' : 'm') : imperial ? 'mi' : 'km' }
function fmtVal(v: number, sport: string) { return sport === 'swim' ? Math.round(v).toLocaleString() : v >= 100 ? String(Math.round(v)) : v.toFixed(1) }

/** 0, a clean middle and a clean top tick. */
function niceMax(v: number): number {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p
  return 10 * p
}
const compact = (v: number) => v >= 1000 ? `${Math.round(v / 100) / 10}K` : String(Math.round(v * 10) / 10)

/** Column path: 4px rounded top, square at the baseline. */
function colPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h)
  if (h <= 0) return ''
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

function Grid({ max, fmt }: { max: number; fmt: (v: number) => string }) {
  const ys = [0, max / 2, max]
  return (
    <g aria-hidden="true">
      {ys.map((v) => {
        const y = PAD_T + (H - PAD_T - PAD_B) * (1 - v / max)
        return (
          <g key={v}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y} y2={y} stroke="var(--border)" strokeWidth={1} />
            <text x={PAD_L - 4} y={y + 3} textAnchor="end" className="fill-(--text-muted) text-[12px] tabular-nums">{fmt(v)}</text>
          </g>
        )
      })}
    </g>
  )
}

/** Arrow keys move the selection; a value readout above the chart says what's selected. */
function useSelect(n: number) {
  const [sel, setSel] = useState(n - 1)
  useEffect(() => setSel(n - 1), [n])
  const onKeyDown = (e: React.KeyboardEvent) => {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!d) return
    e.preventDefault()
    setSel((s) => Math.max(0, Math.min(n - 1, s + d)))
  }
  return { sel: Math.min(sel, n - 1), setSel, onKeyDown }
}

// ------------------------------------------------------------- distance --
function DistanceChart({ s, imperial }: { s: DistSport; imperial: boolean }) {
  const weeks = s.weeks
  const vals = weeks.map((w) => unitVal(w.km, imperial, s.sport))
  const goals = weeks.map((w) => (w.goal == null ? null : unitVal(w.goal, imperial, s.sport)))
  const max = niceMax(Math.max(...vals, ...goals.map((g) => g ?? 0)))
  const { sel, setSel, onKeyDown } = useSelect(weeks.length)
  const band = (W - PAD_L - PAD_R) / weeks.length
  const bw = Math.min(14, band - 2)
  const y = (v: number) => PAD_T + (H - PAD_T - PAD_B) * (1 - v / max)
  const u = unitWord(imperial, s.sport)
  const cur = weeks[sel]!
  const hasGoal = goals.some((g) => g != null)
  const last = weeks.length - 1
  return (
    <>
      <p className="m-0 text-[0.7647rem] text-(--text-secondary)" aria-live="polite">
        <span className="font-medium text-(--text)">Week of {shortDate(cur.start)}{sel === last ? ' (so far)' : ''}:</span>{' '}
        {fmtVal(vals[sel]!, s.sport)} {u}{goals[sel] != null ? ` of ${fmtVal(goals[sel]!, s.sport)} ${u} goal` : ''}
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full touch-pan-y" role="img" tabIndex={0} onKeyDown={onKeyDown}
        aria-label={`${SPORT_LABEL[s.sport]} distance per week for ${weeks.length} weeks. Last 4 weeks averaged ${fmtVal(unitVal(s.avg4_km, imperial, s.sport), s.sport)} ${u}. Use left and right arrows to read each week.`}>
        <Grid max={max} fmt={compact} />
        {weeks.map((w, i) => {
          const x = PAD_L + i * band + (band - bw) / 2
          const v = vals[i]!, g = goals[i]
          return (
            <g key={w.start} onPointerEnter={(e) => { if (e.pointerType === 'mouse') setSel(i) }} onClick={() => setSel(i)} className="cursor-pointer">
              <rect x={PAD_L + i * band} y={PAD_T} width={band} height={H - PAD_T - PAD_B} fill="transparent" />
              <path d={colPath(x, y(v), bw, y(0) - y(v))} fill="var(--accent)" opacity={i === last ? 0.5 : sel === i ? 1 : 0.82} />
              {g != null && <line x1={x - 2} x2={x + bw + 2} y1={y(g)} y2={y(g)} stroke="var(--text)" strokeWidth={2} strokeLinecap="round" />}
              {sel === i && <line x1={x + bw / 2} x2={x + bw / 2} y1={H - PAD_B + 2} y2={H - PAD_B + 6} stroke="var(--text)" strokeWidth={2} />}
            </g>
          )
        })}
        {[0, Math.floor(last / 2), last].map((i) => (
          <text key={i} x={PAD_L + i * band + band / 2} y={H - 6} textAnchor={i === 0 ? 'start' : i === last ? 'end' : 'middle'}
            className="fill-(--text-muted) text-[12px]" aria-hidden="true">{i === last ? 'This week' : shortDate(weeks[i]!.start)}</text>
        ))}
      </svg>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.7059rem] text-(--text-secondary)" aria-hidden="true">
        <span className="inline-flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-[3px] bg-(--accent)" /> Done</span>
        {hasGoal && <span className="inline-flex items-center gap-1.5"><span className="inline-block h-0.5 w-3 rounded bg-(--text)" /> Plan goal</span>}
        <span className="inline-flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-[3px] bg-(--accent) opacity-50" /> This week so far</span>
      </div>
    </>
  )
}

function distanceTakeaway(s: DistSport, imperial: boolean): string {
  const u = unitWord(imperial, s.sport)
  const avg = fmtVal(unitVal(s.avg4_km, imperial, s.sport), s.sport)
  if (s.change_pct == null || s.prev4_km <= 0) return `About ${avg} ${u} a week lately.`
  if (Math.abs(s.change_pct) < 5) return `Steady at about ${avg} ${u} a week.`
  return `${s.change_pct > 0 ? 'Up' : 'Down'} ${Math.abs(s.change_pct)}% over 4 weeks: about ${avg} ${u} a week.`
}

// ----------------------------------------------------------------- pace --
function PaceChart({ t }: { t: Trends['pace'] }) {
  const pts = t.points
  const secs = pts.map((p) => p.sec)
  const lo = Math.floor((Math.min(...secs) - 10) / 15) * 15, hi = Math.ceil((Math.max(...secs) + 10) / 15) * 15
  const { sel, setSel, onKeyDown } = useSelect(pts.length)
  // Faster (smaller) is higher on the chart.
  const y = (s: number) => PAD_T + (H - PAD_T - PAD_B) * ((s - lo) / Math.max(1, hi - lo))
  const x = (i: number) => PAD_L + 6 + (W - PAD_L - PAD_R - 12) * (pts.length === 1 ? 0.5 : i / (pts.length - 1))
  const u = t.imperial ? 'mi' : 'km'
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.sec)}`).join('')
  const cur = pts[sel]!
  const ticks = [lo, (lo + hi) / 2, hi]
  return (
    <>
      <p className="m-0 text-[0.7647rem] text-(--text-secondary)" aria-live="polite">
        <span className="font-medium text-(--text)">Week of {shortDate(cur.start)}:</span> {mmss(cur.sec)}/{u} at {t.ref_hr} bpm
        <span className="text-(--text-muted)"> · {cur.runs} easy run{cur.runs === 1 ? '' : 's'}</span>
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full touch-pan-y" role="img" tabIndex={0} onKeyDown={onKeyDown}
        aria-label={`Easy-run pace at ${t.ref_hr} beats per minute, ${pts.length} weeks, from ${mmss(pts[0]!.sec)} to ${mmss(pts[pts.length - 1]!.sec)} per ${u === 'mi' ? 'mile' : 'kilometre'}. Faster is higher. Use left and right arrows to read each week.`}>
        <g aria-hidden="true">
          {ticks.map((v) => (
            <g key={v}>
              <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth={1} />
              <text x={PAD_L - 4} y={y(v) + 3} textAnchor="end" className="fill-(--text-muted) text-[12px] tabular-nums">{mmss(v)}</text>
            </g>
          ))}
        </g>
        <path d={`${d}L${x(pts.length - 1)},${H - PAD_B}L${x(0)},${H - PAD_B}Z`} fill="var(--accent)" opacity={0.1} />
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {pts.map((p, i) => (
          <g key={p.start} onPointerEnter={(e) => { if (e.pointerType === 'mouse') setSel(i) }} onClick={() => setSel(i)} className="cursor-pointer">
            <rect x={x(i) - 10} y={PAD_T} width={20} height={H - PAD_T - PAD_B} fill="transparent" />
            {(sel === i || i === pts.length - 1) && (
              <circle cx={x(i)} cy={y(p.sec)} r={sel === i ? 5 : 4} fill="var(--accent)" stroke="var(--bg-surface)" strokeWidth={2} />
            )}
          </g>
        ))}
        {[0, pts.length - 1].map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? 'start' : 'end'} className="fill-(--text-muted) text-[12px]" aria-hidden="true">
            {shortDate(pts[i]!.start)}
          </text>
        ))}
      </svg>
    </>
  )
}

function paceTakeaway(t: Trends['pace']): string {
  const u = t.imperial ? 'mi' : 'km'
  if (t.change_s == null) return ''
  if (Math.abs(t.change_s) < 3) return `Holding steady at your easy heart rate (${t.ref_hr} bpm).`
  return t.change_s < 0
    ? `${Math.abs(t.change_s)} s/${u} faster at the same heart rate (${t.ref_hr} bpm). Your engine is growing.`
    : `${t.change_s} s/${u} slower at the same heart rate (${t.ref_hr} bpm). Heat, hills or fatigue can do this.`
}

// ---------------------------------------------------------------- sleep --
function SleepCharts({ t }: { t: Trends['sleep'] }) {
  const pts = t.points
  const { sel, setSel, onKeyDown } = useSelect(pts.length)
  const band = (W - PAD_L - PAD_R) / pts.length
  const bw = Math.min(8, band - 2)
  const sleepMax = niceMax(Math.max(8, ...pts.map((p) => p.sleep_h ?? 0)))
  const loadMax = niceMax(Math.max(1, ...pts.map((p) => p.load)))
  const h2 = 76
  const cur = pts[sel]!
  const loadWord = t.measure === 'load' ? 'training load' : 'minutes trained'
  const mini = (vals: (number | null)[], max: number, h: number, label: string, fmt: (v: number) => string) => {
    const y = (v: number) => 16 + (h - 16 - 6) * (1 - v / max)
    return (
      <svg viewBox={`0 0 ${W} ${h}`} className="block h-auto w-full touch-pan-y" aria-hidden="true">
        <text x={PAD_L} y={10} className="fill-(--text-muted) text-[12px]">{label}</text>
        <line x1={PAD_L} x2={W - PAD_R} y1={y(0)} y2={y(0)} stroke="var(--border)" strokeWidth={1} />
        <text x={PAD_L - 4} y={y(max) + 3} textAnchor="end" className="fill-(--text-muted) text-[12px] tabular-nums">{fmt(max)}</text>
        <line x1={PAD_L} x2={W - PAD_R} y1={y(max)} y2={y(max)} stroke="var(--border)" strokeWidth={1} />
        {vals.map((v, i) => {
          const x = PAD_L + i * band + (band - bw) / 2
          return (
            <g key={i} onPointerEnter={(e) => { if (e.pointerType === 'mouse') setSel(i) }} onClick={() => setSel(i)} className="cursor-pointer">
              <rect x={PAD_L + i * band} y={0} width={band} height={h} fill="transparent" />
              {v != null && v > 0 && <path d={colPath(x, y(v), bw, y(0) - y(v))} fill="var(--accent)" opacity={sel === i ? 1 : 0.75} />}
              {v == null && <circle cx={x + bw / 2} cy={y(0) - 2} r={1.5} fill="var(--text-muted)" />}
            </g>
          )
        })}
      </svg>
    )
  }
  return (
    <>
      <p className="m-0 text-[0.7647rem] text-(--text-secondary)" aria-live="polite">
        <span className="font-medium text-(--text)">{shortDate(cur.date)}:</span>{' '}
        {cur.load ? `${cur.load} ${t.measure === 'load' ? 'load' : 'min'}` : 'rest day'}
        {' · '}{cur.sleep_h != null ? `${cur.sleep_h} h sleep that night` : 'no sleep data that night'}
      </p>
      <div role="img" tabIndex={0} onKeyDown={onKeyDown} className="flex flex-col gap-1 rounded-md focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-(--accent)"
        aria-label={`Sleep each night and ${loadWord} the day before, last ${pts.length} days. Use left and right arrows to read each day.`}>
        {mini(pts.map((p) => p.sleep_h), sleepMax, h2, 'Sleep (hours)', (v) => String(v))}
        {mini(pts.map((p) => p.load), loadMax, h2, t.measure === 'load' ? 'Training load' : 'Minutes trained', compact)}
        <div className="flex justify-between pl-[12%] text-[0.6471rem] text-(--text-muted)" aria-hidden="true">
          <span>{shortDate(pts[0]!.date)}</span><span>Today</span>
        </div>
      </div>
    </>
  )
}

function sleepTakeaway(t: Trends['sleep']): string {
  if (t.hard_h == null || t.other_h == null) return ''
  const diff = Math.round((t.hard_h - t.other_h) * 10) / 10
  if (Math.abs(diff) < 0.2) return `You sleep about the same after hard days (${t.hard_h} h). Nice.`
  return diff < 0
    ? `After your hardest days you slept ${t.hard_h} h vs ${t.other_h} h. Hard days need more, not less.`
    : `After your hardest days you slept ${t.hard_h} h vs ${t.other_h} h. That's how recovery should look.`
}

// ---------------------------------------------------------------- table --
function DataTable({ view, t, sport }: { view: View; t: Trends; sport: DistSport | null }) {
  const imperial = t.units === 'imperial'
  const cls = 'border-b border-(--border) px-2 py-1 text-left'
  if (view === 'distance' && sport) {
    const u = unitWord(imperial, sport.sport)
    return (
      <table className="w-full text-[0.7059rem] tabular-nums text-(--text)">
        <caption className="sr-only">{SPORT_LABEL[sport.sport]} per week</caption>
        <thead><tr><th className={cls}>Week of</th><th className={cls}>Done ({u})</th><th className={cls}>Goal ({u})</th></tr></thead>
        <tbody>{sport.weeks.slice().reverse().map((w) => (
          <tr key={w.start}><td className={cls}>{shortDate(w.start)}</td><td className={cls}>{fmtVal(unitVal(w.km, imperial, sport.sport), sport.sport)}</td>
            <td className={cls}>{w.goal == null ? '–' : fmtVal(unitVal(w.goal, imperial, sport.sport), sport.sport)}</td></tr>
        ))}</tbody>
      </table>
    )
  }
  if (view === 'pace') {
    return (
      <table className="w-full text-[0.7059rem] tabular-nums text-(--text)">
        <caption className="sr-only">Pace at {t.pace.ref_hr} bpm per week</caption>
        <thead><tr><th className={cls}>Week of</th><th className={cls}>Pace /{imperial ? 'mi' : 'km'}</th><th className={cls}>Easy runs</th></tr></thead>
        <tbody>{t.pace.points.slice().reverse().map((p) => (
          <tr key={p.start}><td className={cls}>{shortDate(p.start)}</td><td className={cls}>{mmss(p.sec)}</td><td className={cls}>{p.runs}</td></tr>
        ))}</tbody>
      </table>
    )
  }
  return (
    <table className="w-full text-[0.7059rem] tabular-nums text-(--text)">
      <caption className="sr-only">Sleep and training per day</caption>
      <thead><tr><th className={cls}>Day</th><th className={cls}>{t.sleep.measure === 'load' ? 'Load' : 'Minutes'}</th><th className={cls}>Sleep that night</th></tr></thead>
      <tbody>{t.sleep.points.slice().reverse().map((p) => (
        <tr key={p.date}><td className={cls}>{shortDate(p.date)}</td><td className={cls}>{p.load || '–'}</td><td className={cls}>{p.sleep_h == null ? '–' : `${p.sleep_h} h`}</td></tr>
      ))}</tbody>
    </table>
  )
}

const WHY: Record<View, string> = {
  distance: 'Steady weekly volume builds fitness with the least injury risk. Big jumps (more than about 10 to 20% a week) are when most overuse injuries start.',
  pace: 'If you run faster at the same heart rate, your aerobic engine is improving. It is the clearest sign easy running is working, with no race or test needed.',
  sleep: 'Training breaks you down; sleep is when you rebuild. Less sleep after hard days means you are recovering less from the work you did.',
}

export function TrendsCard({ loadKey = 0 }: { loadKey?: number }) {
  const [t, setT] = useState<Trends | null>(null)
  const [failed, setFailed] = useState(false)
  const [view, setView] = useState<View>('distance')
  const [sport, setSport] = useState<string | null>(null)
  const [table, setTable] = useState(false)
  const track = useTrackRefresh()
  useEffect(() => {
    let live = true
    const p = getTrends(loadKey > 0).then((x) => { if (live) { setT(x); setFailed(false) } }, () => { if (live) setFailed(true) })
    track(p)
    return () => { live = false }
  }, [loadKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const imperial = t?.units === 'imperial'
  const ORDER = ['run', 'bike', 'swim']
  const rank = (x: string) => { const i = ORDER.indexOf(x); return i < 0 ? 9 : i }
  const sports = useMemo(() => [...(t?.distance.sports ?? [])].sort((a, b) => rank(a.sport) - rank(b.sport)), [t])  // runs first
  const cur = useMemo(() => sports.find((s) => s.sport === sport) ?? sports[0] ?? null, [sports, sport])
  if (failed || !t) return failed ? null : <div className="skeleton h-56 rounded-xl" aria-hidden="true" />

  const views: [View, string][] = [['distance', 'Distance'], ['pace', 'Easy pace'], ['sleep', 'Sleep']]
  const takeaway = view === 'distance' ? (cur ? distanceTakeaway(cur, imperial) : '')
    : view === 'pace' ? paceTakeaway(t.pace) : sleepTakeaway(t.sleep)
  const empty = view === 'distance' ? (cur ? null : 'No runs, rides or swims with distance in the last 16 weeks.')
    : view === 'pace' ? (t.pace.points.length ? null : t.pace.reason)
    : t.sleep.reason && t.sleep.nights < 7 ? t.sleep.reason : null
  return (
    <div className="flex flex-col gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="m-0 flex items-center gap-1 text-[0.8824rem] font-semibold text-(--text)">
          Trends <InfoTip label={views.find(([v]) => v === view)![1]} text={WHY[view]} align="start" />
        </h3>
        {!empty && (
          <button type="button" onClick={() => setTable((x) => !x)} aria-pressed={table}
            className="hit-44 inline-flex items-center gap-1 text-[0.7059rem] text-(--text-muted)">
            {table ? <><ChevronRight className="size-3.5 rotate-180" aria-hidden /> Chart</> : <><Table2 className="size-3.5" aria-hidden /> Table</>}
          </button>
        )}
      </div>
      <div role="tablist" aria-label="Trend" className="flex gap-1 rounded-full bg-(--bg-inset) p-0.5">
        {views.map(([v, l]) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
            className={cn('min-h-11 flex-1 rounded-full text-[0.7647rem] font-medium transition-colors',
              view === v ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)')}>{l}</button>
        ))}
      </div>
      {view === 'distance' && sports.length > 1 && (
        <div className="flex gap-1.5" role="group" aria-label="Sport">
          {sports.map((s) => (
            <button key={s.sport} type="button" aria-pressed={cur?.sport === s.sport} onClick={() => setSport(s.sport)}
              className={cn('plan-chip', cur?.sport === s.sport && 'plan-chip--on')}>{SPORT_LABEL[s.sport]}</button>
          ))}
        </div>
      )}
      {takeaway && !empty && <p className="m-0 text-[0.8235rem] font-medium leading-snug text-(--text)">{takeaway}</p>}
      {empty ? (
        <p className="m-0 py-4 text-center text-[0.7647rem] text-(--text-muted)">{empty}</p>
      ) : table ? (
        <div className="max-h-64 overflow-y-auto"><DataTable view={view} t={t} sport={cur} /></div>
      ) : view === 'distance' && cur ? (
        <DistanceChart key={cur.sport} s={cur} imperial={imperial} />
      ) : view === 'pace' ? (
        <PaceChart t={t.pace} />
      ) : (
        <SleepCharts t={t.sleep} />
      )}
      {view === 'sleep' && !empty && t.sleep.source && (
        <p className="m-0 text-[0.6471rem] text-(--text-muted)">Sleep from {t.sleep.source === 'oura' ? 'Oura' : 'Garmin'} · only you see this</p>
      )}
    </div>
  )
}
