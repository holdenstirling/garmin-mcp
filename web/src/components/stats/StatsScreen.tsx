// Your progress, focused: level and streak, recovery, fitness and form, this week's plan,
// the training trend and the next badges. Everything else sits under "More stats".
// Sport-agnostic: everything Garmin records counts.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Award, CalendarCheck, ChevronDown, Flame, Lock, Mountain, RefreshCw, Timer, Trophy, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card, Screen } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { getOura, type OuraRecovery } from '@/lib/oura'
import { LoadCard } from './LoadChart'
import { CheckinsCard } from '@/components/checkin/CheckinsCard'
import { ProgressHero } from '@/components/progress/Progress'
import { getProgress, type Progress } from '@/lib/progress'
import { SPORT_COLOR, SPORT_NAME, climb, dist, getStats, hours, type Sport, type Stats, type Totals } from '@/lib/stats'

type Period = 'week' | 'month' | 'year'

export function StatsScreen({ onClose, onOpenPlan, oura, onOpenRecap }: {
  onClose: () => void; onOpenPlan?: () => void; oura?: boolean; onOpenRecap?: () => void
}) {
  const [s, setS] = useState<Stats | null>(null)
  const [p, setP] = useState<Progress | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loadKey, setLoadKey] = useState(0)

  const load = useCallback((fresh = false) => {
    setBusy(true)
    getStats(fresh).then((r) => {
      setS(r); setError(null)
      getProgress().then(setP, () => {})
    }, (e) => setError((e as Error).message)).finally(() => setBusy(false))
    if (fresh) setLoadKey((k) => k + 1)
  }, [])
  useEffect(() => load(), [load])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  return (
    <Screen title="Your progress" subtitle={s ? `Updated from Garmin · ${new Date(`${s.today}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}` : undefined}
      closing={closing} onClose={close}
      headerExtra={s ? (
        <div className="mx-auto mt-1 flex max-w-xl justify-end gap-3">
          {onOpenRecap && (
            <button type="button" onClick={onOpenRecap}
              className="inline-flex items-center gap-1 text-[0.6471rem] font-medium text-(--accent)">
              <CalendarCheck className="size-3" /> Weekly recap
            </button>
          )}
          <button type="button" onClick={() => load(true)} disabled={busy} aria-label="Refresh"
            className="inline-flex items-center gap-1 text-[0.6471rem] text-(--text-muted) disabled:opacity-50">
            <RefreshCw className={cn('size-3', busy && 'animate-spin')} /> Refresh
          </button>
        </div>) : undefined}>
      {!s && !error && (
        <div className="flex flex-col gap-3">
          <RabbitLoader className="py-8" label="Loading stats" cycle={['Counting your miles…', 'Tallying your streak…', 'Crunching the numbers…']} />
          <div className="skeleton h-28" aria-hidden="true" />
          <div className="skeleton h-40" aria-hidden="true" />
        </div>
      )}
      {error && <p className="px-1 text-[0.8235rem] text-(--danger)" role="alert">{error}</p>}
      {s && <StatsBody s={s} progress={p} onOpenPlan={onOpenPlan} loadBase="/api" loadKey={loadKey}
        recovery={oura ? <Recovery /> : null} more={<CheckinsCard />} />}
    </Screen>
  )
}

/** The stats sections, most important first (also used in the coach's view of an athlete). */
export function StatsBody({ s, progress, onOpenPlan, loadBase, loadKey, recovery, more: moreExtra }: {
  s: Stats; progress?: Progress | null; onOpenPlan?: () => void; loadBase?: string; loadKey?: number; recovery?: React.ReactNode
  /** extra sections under "More stats" (the athlete's own check-ins) */
  more?: React.ReactNode
}) {
  const [period, setPeriod] = useState<Period>('week')
  const [more, setMore] = useState(false)
  return (
    <>
      {progress ? <ProgressHero p={progress} headline={s.headline} /> : <StreakHero s={s} />}
      {recovery}
      {loadBase && <LoadCard key={loadKey ?? 0} base={loadBase} />}
      {s.plan?.week && s.plan.week.planned > 0 && <PlanProgress s={s} onOpenPlan={onOpenPlan} />}
      <WeeklyBars s={s} />
      <BadgesCard s={s} />
      <button type="button" onClick={() => setMore((m) => !m)} aria-expanded={more}
        className="flex items-center justify-center gap-1.5 rounded-xl border border-(--border) bg-(--bg-surface) py-2.5 text-[0.7647rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)">
        {more ? 'Fewer stats' : 'More stats'} <ChevronDown className={cn('size-4 transition-transform', more && 'rotate-180')} />
      </button>
      {more && <>
        <TotalsCard s={s} period={period} setPeriod={setPeriod} />
        <CalendarHeat s={s} />
        {s.by_sport.length > 0 && <SportsCard s={s} />}
        {Object.keys(s.bests).length > 0 && <BestsCard s={s} />}
        {s.recent.length > 0 && <RecentCard s={s} />}
        {moreExtra}
      </>}
    </>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{children}</h3>
}

function StreakHero({ s }: { s: Stats }) {
  const st = s.streak
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-4 py-5 text-center">
      <div className="flex items-end gap-6">
        <div className="flex flex-col items-center">
          <span className={cn('flex size-16 items-center justify-center rounded-full', st.current ? 'bg-(--accent) text-white' : 'bg-(--bg-elevated) text-(--text-muted)')}>
            <Flame className="size-8" />
          </span>
          <span className="mt-2 font-display text-[2.2rem] leading-none text-(--brand)">{st.current}</span>
          <span className="text-[0.7059rem] text-(--text-muted)">day streak</span>
        </div>
        <div className="flex flex-col items-center pb-1">
          <span className="font-display text-[1.6rem] leading-none text-(--text)">{st.weeks_current}</span>
          <span className="max-w-[90px] text-[0.6471rem] leading-tight text-(--text-muted)">active weeks in a row ({st.active_week}+ workouts)</span>
        </div>
      </div>
      <p className="max-w-sm text-[0.8824rem] leading-snug text-(--text)">{s.headline}</p>
      <p className="text-[0.6471rem] text-(--text-muted)">Best: {st.best} days · {st.weeks_best} weeks</p>
      <WeekDots s={s} />
    </div>
  )
}

/** This week's seven days: filled when you trained. */
function WeekDots({ s }: { s: Stats }) {
  const today = new Date(`${s.today}T12:00:00`)
  const monday = new Date(today); monday.setDate(today.getDate() - ((today.getDay() + 6) % 7))
  const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return d })
  const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return (
    <div className="flex gap-2.5" aria-label="This week">
      {days.map((d) => {
        const k = key(d), mins = s.calendar.days[k] ?? 0, isToday = k === s.today, future = d > today
        return (
          <span key={k} className="flex flex-col items-center gap-1">
            <span className={cn('text-[0.5882rem] uppercase', isToday ? 'font-semibold text-(--accent)' : 'text-(--text-muted)')}>
              {d.toLocaleDateString([], { weekday: 'narrow' })}
            </span>
            <span className={cn('size-6 rounded-full border',
              mins > 0 ? 'border-(--accent) bg-(--accent)' : future ? 'border-dashed border-(--border-strong)' : 'border-(--border-strong)',
              isToday && 'ring-2 ring-(--accent)/30 ring-offset-1 ring-offset-(--bg-surface)')} title={mins ? `${mins} min` : ''} />
          </span>
        )
      })}
    </div>
  )
}

function PlanProgress({ s, onOpenPlan }: { s: Stats; onOpenPlan?: () => void }) {
  const w = s.plan!.week!
  const pct = Math.round((100 * w.done) / w.planned)
  const td = s.plan!.to_date
  return (
    <Card className="p-4">
      <div className="flex items-center gap-4">
        <Ring pct={pct} label={`${w.done}/${w.planned}`} />
        <div className="min-w-0 flex-1">
          <p className="text-[0.9412rem] font-medium text-(--text)">This week's plan</p>
          <p className="text-[0.7647rem] leading-snug text-(--text-muted)">
            {w.done} of {w.planned} sessions done · {hours(w.minutes_done / 60)} of {hours(w.minutes_planned / 60)}
          </p>
          {td.pct != null && <p className="mt-1 text-[0.7059rem] text-(--text-secondary)">Plan to date: {td.pct}% of sessions ({td.done}/{td.planned}){s.plan!.perfect_weeks ? ` · ${s.plan!.perfect_weeks} perfect week${s.plan!.perfect_weeks === 1 ? '' : 's'}` : ''}</p>}
        </div>
      </div>
      {onOpenPlan && <Button variant="default" className="mt-3 h-9 w-full text-[0.7647rem]" onClick={onOpenPlan}>Open plan</Button>}
    </Card>
  )
}

function Ring({ pct, label }: { pct: number; label: string }) {
  const r = 26, c = 2 * Math.PI * r
  return (
    <span className="relative flex size-[68px] shrink-0 items-center justify-center">
      <svg viewBox="0 0 64 64" className="absolute inset-0 -rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" strokeWidth="6" className="stroke-(--bg-elevated)" />
        <circle cx="32" cy="32" r={r} fill="none" strokeWidth="6" strokeLinecap="round" className="stroke-(--accent) transition-all duration-700"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(1, pct / 100))} />
      </svg>
      <span className="font-display text-[1rem] text-(--text)">{label}</span>
    </span>
  )
}

function TotalsCard({ s, period, setPeriod }: { s: Stats; period: Period; setPeriod: (p: Period) => void }) {
  const t: Totals = s.totals[period]
  const tiles: [typeof Zap, string, string][] = [
    [Zap, 'Workouts', String(t.workouts)],
    [Timer, 'Time', hours(t.hours)],
    [CalendarCheck, 'Active days', String(t.days)],
    [Mountain, 'Climbing', climb(t.climb_m, s.units)],
  ]
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <SectionLabel>Totals</SectionLabel>
        <div className="flex gap-1 rounded-lg bg-(--bg-elevated) p-0.5">
          {([['week', 'Week'], ['month', 'Month'], ['year', '12 mo']] as [Period, string][]).map(([p, l]) => (
            <button key={p} type="button" onClick={() => setPeriod(p)} aria-pressed={period === p}
              className={cn('h-7 rounded-md px-2.5 text-[0.6471rem] font-medium', period === p ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)')}>{l}</button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {tiles.map(([I, label, v]) => (
          <div key={label} className="rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
            <span className="flex items-center gap-1.5 text-[0.6471rem] text-(--text-muted)"><I className="size-3.5" />{label}</span>
            <span className="mt-1 block font-display text-[1.4rem] leading-tight text-(--text)">{v}</span>
          </div>
        ))}
      </div>
      {period === 'week' && t.vs_last_week_hours != null && (
        <p className="px-1 text-[0.7059rem] text-(--text-muted)">
          {t.vs_last_week_hours === 0 ? 'Same as this point last week.' : `${t.vs_last_week_hours > 0 ? '+' : '−'}${hours(Math.abs(t.vs_last_week_hours))} vs this point last week.`}
        </p>
      )}
    </section>
  )
}

function WeeklyBars({ s }: { s: Stats }) {
  const max = Math.max(1, ...s.weekly.map((w) => w.hours))
  const sports = useMemo(() => {
    const set = new Set<Sport>()
    s.weekly.forEach((w) => Object.keys(w.by_sport).forEach((k) => set.add(k as Sport)))
    return [...set]
  }, [s.weekly])
  return (
    <section className="flex flex-col gap-2">
      <SectionLabel>Weekly training time · 12 weeks</SectionLabel>
      <Card className="p-4">
        <div className="flex h-32 items-end gap-1.5">
          {s.weekly.map((w, i) => (
            <div key={w.start} className="flex h-full flex-1 flex-col justify-end" title={`${hours(w.hours)} · ${w.workouts} workouts`}>
              <div className="flex flex-col-reverse overflow-hidden rounded-t-[4px]" style={{ height: `${(w.hours / max) * 100}%` }}>
                {sports.map((sp) => (w.by_sport[sp] ? <span key={sp} style={{ flexGrow: w.by_sport[sp], background: SPORT_COLOR[sp] }} /> : null))}
              </div>
              <span className={cn('mt-1 text-center text-[0.5294rem]', i === s.weekly.length - 1 ? 'font-semibold text-(--accent)' : 'text-(--text-muted)')}>
                {new Date(`${w.start}T12:00:00`).toLocaleDateString([], { month: 'numeric', day: 'numeric' })}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
          {sports.map((sp) => <span key={sp} className="flex items-center gap-1 text-[0.6471rem] text-(--text-muted)"><span className="size-2 rounded-full" style={{ background: SPORT_COLOR[sp] }} />{SPORT_NAME[sp]}</span>)}
          <span className="ml-auto text-[0.6471rem] text-(--text-muted)">avg {hours(s.weekly.reduce((a, w) => a + w.hours, 0) / s.weekly.length)}/wk</span>
        </div>
      </Card>
    </section>
  )
}

function CalendarHeat({ s }: { s: Stats }) {
  const start = new Date(`${s.calendar.start}T12:00:00`)
  const today = new Date(`${s.today}T12:00:00`)
  const weeks = Array.from({ length: 26 }, (_, w) => Array.from({ length: 7 }, (_, d) => {
    const dt = new Date(start); dt.setDate(start.getDate() + w * 7 + d)
    const k = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
    return { k, mins: s.calendar.days[k] ?? 0, future: dt > today }
  }))
  const level = (m: number) => m <= 0 ? 0 : m < 30 ? 1 : m < 60 ? 2 : m < 120 ? 3 : 4
  const active = Object.values(s.calendar.days).filter((m) => m > 0).length
  return (
    <section className="flex flex-col gap-2">
      <SectionLabel>Training calendar · 6 months</SectionLabel>
      <Card className="p-4">
        <div className="flex gap-[3px] overflow-hidden" role="img" aria-label={`${active} active days in the last 6 months`}>
          {weeks.map((wk, i) => (
            <div key={i} className="flex flex-1 flex-col gap-[3px]">
              {wk.map((d) => (
                <span key={d.k} title={d.mins ? `${d.k}: ${d.mins} min` : d.k}
                  className={cn('aspect-square w-full rounded-[2px]', d.future && 'opacity-0')}
                  style={{ background: level(d.mins) === 0 ? 'var(--bg-elevated)' : `color-mix(in srgb, var(--accent) ${[0, 30, 55, 80, 100][level(d.mins)]}%, var(--bg-elevated))` }} />
              ))}
            </div>
          ))}
        </div>
        <p className="mt-2 text-[0.6471rem] text-(--text-muted)">{active} active days · darker = longer</p>
      </Card>
    </section>
  )
}

function SportsCard({ s }: { s: Stats }) {
  return (
    <section className="flex flex-col gap-2">
      <SectionLabel>By sport · 12 months</SectionLabel>
      <Card>
        <div className="divide-y divide-(--border)">
          {s.by_sport.map((x) => (
            <div key={x.sport} className="flex items-center gap-3 px-4 py-3">
              <span className="size-3 shrink-0 rounded-full" style={{ background: SPORT_COLOR[x.sport] }} />
              <span className="min-w-0 flex-1">
                <span className="block text-[0.8824rem] text-(--text)">{SPORT_NAME[x.sport]}{x.favorite && <span className="ml-1.5 text-[0.6471rem] text-(--accent)">favorite</span>}</span>
                <span className="block text-[0.6471rem] text-(--text-muted)">
                  {x.workouts} workouts{x.km > 0 ? ` · ${dist(x.km, s.units, x.sport)}` : ''}{x.climb_m > 0 ? ` · ${climb(x.climb_m, s.units)} up` : ''}
                </span>
              </span>
              <span className="text-[0.8235rem] font-medium text-(--text-secondary)">{hours(x.hours)}</span>
            </div>
          ))}
        </div>
      </Card>
    </section>
  )
}

function BestsCard({ s }: { s: Stats }) {
  const b = s.bests
  const rows: [string, string | null, string | undefined][] = [
    ['Longest workout', b.longest_workout_min ? hours(b.longest_workout_min.value / 60) : null, b.longest_workout_min?.date],
    ['Longest run', b.longest_run_km ? dist(b.longest_run_km.value, s.units) : null, b.longest_run_km?.date],
    ['Longest ride', b.longest_ride_km ? dist(b.longest_ride_km.value, s.units) : null, b.longest_ride_km?.date],
    ['Longest swim', b.longest_swim_km ? dist(b.longest_swim_km.value, s.units, 'swim') : null, b.longest_swim_km?.date],
    ['Biggest climb', b.biggest_climb_m ? climb(b.biggest_climb_m.value, s.units) : null, b.biggest_climb_m?.date],
  ]
  return (
    <section className="flex flex-col gap-2">
      <SectionLabel>Your bests · 12 months</SectionLabel>
      <div className="grid grid-cols-2 gap-2">
        {rows.filter(([, v]) => v).map(([label, v, d]) => (
          <div key={label} className="rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
            <span className="flex items-center gap-1.5 text-[0.6471rem] text-(--text-muted)"><Trophy className="size-3.5" />{label}</span>
            <span className="mt-1 block font-display text-[1.2rem] leading-tight text-(--text)">{v}</span>
            {d && <span className="text-[0.5882rem] text-(--text-muted)">{new Date(`${d}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}</span>}
          </div>
        ))}
      </div>
    </section>
  )
}

function BadgesCard({ s }: { s: Stats }) {
  const [all, setAll] = useState(false)
  const earned = s.badges.filter((b) => b.earned)
  const next = s.badges.filter((b) => !b.earned).sort((a, b) => b.progress - a.progress)
  const shown = all ? [...next, ...earned] : next.slice(0, 3)
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <SectionLabel>{all ? 'All badges' : 'Next badges'} · {earned.length} of {s.badges.length} earned</SectionLabel>
        <button type="button" onClick={() => setAll((a) => !a)} className="text-[0.6471rem] font-medium text-(--accent)">{all ? 'Show less' : 'See all'}</button>
      </div>
      {shown.length === 0 && <p className="px-1 text-[0.7647rem] text-(--text-muted)">Every badge earned. Legendary.</p>}
      <div className="grid grid-cols-3 gap-2">
        {shown.map((b) => (
          <div key={b.id} title={b.description}
            className={cn('flex flex-col items-center gap-1 rounded-xl border px-2 py-3 text-center',
              b.earned ? 'border-(--accent)/40 bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
            <span className={cn('flex size-9 items-center justify-center rounded-full', b.earned ? 'bg-(--accent) text-white' : 'bg-(--bg-elevated) text-(--text-muted)')}>
              {b.earned ? <Award className="size-5" /> : <Lock className="size-4" />}
            </span>
            <span className={cn('text-[0.7059rem] font-medium leading-tight', b.earned ? 'text-(--accent)' : 'text-(--text)')}>{b.title}</span>
            <span className="text-[0.5882rem] leading-tight text-(--text-muted)">{b.description}</span>
            {!b.earned && (
              <>
                <span className="mt-0.5 h-1 w-full overflow-hidden rounded-full bg-(--bg-elevated)">
                  <span className="block h-full rounded-full bg-(--accent)" style={{ width: `${Math.round(b.progress * 100)}%` }} />
                </span>
                <span className="text-[0.5294rem] text-(--text-muted)">{Math.round(b.progress * 100)}% · +100 XP</span>
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

function RecentCard({ s }: { s: Stats }) {
  return (
    <section className="flex flex-col gap-2">
      <SectionLabel>Recent workouts</SectionLabel>
      <Card>
        <div className="divide-y divide-(--border)">
          {s.recent.map((r) => (
            <div key={`${r.id}-${r.date}`} className="flex items-center gap-3 px-4 py-2.5">
              <span className="size-2.5 shrink-0 rounded-full" style={{ background: SPORT_COLOR[r.sport] }} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.8235rem] text-(--text)">{r.name}</span>
                <span className="block text-[0.6471rem] text-(--text-muted)">
                  {new Date(`${r.date}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}
                </span>
              </span>
              <span className="text-right text-[0.7059rem] text-(--text-secondary)">
                {hours(r.minutes / 60)}{r.km > 0 ? <><br />{dist(r.km, s.units, r.sport)}</> : null}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </section>
  )
}

/** Oura readiness, HRV, resting HR and sleep vs your own baseline (app-only data). */
function Recovery() {
  const [r, setR] = useState<OuraRecovery | null>(null)
  useEffect(() => { getOura(28).then(setR, () => {}) }, [])
  if (!r?.connected || !r.days?.length) return null
  const last = r.latest ?? r.days[r.days.length - 1]!
  const b = r.baseline
  const delta = (v: number | undefined, base: number | null | undefined, unit: string, higherIsBetter: boolean) => {
    if (v == null || base == null) return null
    const d = Math.round((v - base) * 10) / 10
    const good = higherIsBetter ? d >= 0 : d <= 0
    return <span className={good ? 'text-(--accent)' : 'text-(--warning)'}>{d >= 0 ? '+' : ''}{d}{unit}</span>
  }
  const tiles: [string, string, React.ReactNode][] = [
    ['Readiness', last.readiness != null ? String(last.readiness) : '–', delta(last.readiness, b?.readiness, '', true)],
    ['HRV', last.hrv != null ? `${last.hrv} ms` : '–', delta(last.hrv, b?.hrv, ' ms', true)],
    ['Resting HR', last.resting_hr != null ? `${last.resting_hr} bpm` : '–', delta(last.resting_hr, b?.resting_hr, ' bpm', false)],
    ['Sleep', last.sleep_hours != null ? `${last.sleep_hours} h` : '–', delta(last.sleep_hours, b?.sleep_hours, ' h', true)],
  ]
  return (
    <section className="flex flex-col gap-2">
      <SectionLabel>Recovery · Oura · {new Date(`${last.date}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}</SectionLabel>
      <div className="grid grid-cols-4 gap-1.5">
        {tiles.map(([label, v, d]) => (
          <div key={label} className="rounded-xl border border-(--border) bg-(--bg-surface) px-2 py-2.5 text-center">
            <span className="block text-[0.5882rem] text-(--text-muted)">{label}</span>
            <span className="mt-0.5 block font-display text-[1.05rem] leading-tight text-(--text)">{v}</span>
            {d && <span className="block text-[0.5294rem] leading-tight">{d}</span>}
          </div>
        ))}
      </div>
      <p className="px-1 text-[0.5882rem] text-(--text-muted)">Compared with your usual. Shown here only; Oura data isn't sent to the AI coach.</p>
    </section>
  )
}
