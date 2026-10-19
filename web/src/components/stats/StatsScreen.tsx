// Your progress, calm and in order: level/streak/week, main race grade, two insights, recovery
// and challenges as one row each, fitness and form. Everything else sits under "More stats".
// Sport-agnostic: everything Garmin records counts.
import { BodyLinks } from '@/components/body/BodyLinks'
import { useRefreshOnShow } from '@/hooks/useRefreshOnShow'
import { EmptyState } from '@/components/ui/EmptyState'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Award, CalendarCheck, ChevronDown, Flame, Lock, Mountain, RefreshCw, Timer, Trophy, Zap } from 'lucide-react'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import { Card, Screen } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { getOura, type OuraRecovery } from '@/lib/oura'
import { LoadCard } from './LoadChart'
import { CheckinsCard } from '@/components/checkin/CheckinsCard'
import { ProgressHero } from '@/components/progress/Progress'
import { getProgress, type Progress } from '@/lib/progress'
import { SPORT_COLOR, SPORT_NAME, climb, dist, getStats, hours, type Sport, type Stats, type Totals } from '@/lib/stats'
import { fmtDuration } from '@/lib/format'
import { MainRaceGrade } from '@/components/events/Readiness'
import { RaceFitScreen } from '@/components/events/RaceFitScreen'
import { ChallengesCard } from '@/components/challenges/ChallengesCard'
import { InsightsCard } from '@/components/insights/InsightsCard'
import { TrendsCard } from '@/components/progress/TrendsCard'
import { PullToRefresh } from '@/components/fx/PullToRefresh'
import { hopIn } from '@/components/anim'
import { useRefreshGroup, useTrackRefresh } from './refresh'
import { GarminEmpty } from '@/components/garmin/GarminEmpty'
import { isGarminMissing } from '@/lib/upnext'

type Period = 'week' | 'month' | 'year'

export function StatsScreen({ onClose, onOpenPlan, onOpenRecap, onAsk, onOpenGear, onOpenSession, onOpenSetup }: {
  /** none when it is the Progress tab page (no X) */
  onClose?: () => void; onOpenPlan?: () => void; onOpenRecap?: () => void
  /** insight actions ("What your data says") */
  onAsk?: (text: string) => void; onOpenGear?: () => void; onOpenSession?: (sessionId: string) => void
  /** the setup checklist (one line in the hero until core setup is done) */
  onOpenSetup?: () => void
}) {
  const [s, setS] = useState<Stats | null>(null)
  const [p, setP] = useState<Progress | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [noGarmin, setNoGarmin] = useState(false) // 409 garmin_not_connected: friendly empty state
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loadKey, setLoadKey] = useState(0)
  const [fitId, setFitId] = useState<string | null>(null)
  const group = useRefreshGroup(loadKey)

  const load = useCallback((fresh = false): Promise<unknown> => {
    setBusy(true)
    return getStats(fresh).then((r) => {
      setS(r); setError(null)
      return getProgress().then(setP, () => {})
    }, (e) => { setNoGarmin(isGarminMissing(e)); setError((e as Error).message) }).finally(() => setBusy(false))
  }, [])
  useEffect(() => { void load() }, [load])
  useRefreshOnShow(() => load())
  // Refresh = stats + every card below; resolves when all of them have landed (pull rabbit).
  const refresh = useCallback(() => group.refresh(() => setLoadKey((k) => k + 1), load(true)), [group, load])
  const close = onClose && (() => { setClosing(true); setTimeout(onClose, 200) })
  const imperial = s?.units !== 'metric'

  return (
    <Screen title="Progress" subtitle={s ? `Updated from Garmin · ${new Date(`${s.today}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}` : undefined}
      closing={closing} onClose={close}
      headerExtra={s ? (
        <div className="mx-auto mt-1 flex max-w-xl justify-end gap-3">
          {onOpenRecap && (
            <button type="button" onClick={onOpenRecap}
              className="hit-44 inline-flex items-center gap-1 text-caption font-medium text-(--accent)">
              <CalendarCheck className="size-3.5" /> Weekly recap
            </button>
          )}
          <button type="button" onClick={() => void refresh()} disabled={busy} aria-label="Refresh"
            className="hit-44 inline-flex items-center gap-1 text-caption text-(--text-muted) disabled:opacity-50">
            <RefreshCw className={cn('size-3.5', busy && 'animate-spin motion-reduce:animate-none')} /> Refresh
          </button>
        </div>) : undefined}>
      <group.Provider value={group.track}>
        <PullToRefresh onRefresh={() => (busy ? undefined : refresh())} />
        {!s && !error && (
          <ProgressSkeleton />
        )}
        {noGarmin && !s && <GarminEmpty what="progress" />}
        {error && !(noGarmin && !s) && <ErrorState message={s ? `Couldn't refresh: ${error}` : `Couldn't load your progress: ${error}`} onRetry={() => void refresh()} compact={!!s} />}
        {s && s.totals.year.workouts === 0 && (
          <EmptyState card mode="sleep" title="Your story starts with one workout"
            body="Finish a workout with your watch and it lands here within minutes: your streak, trends and what they mean."
            action={onOpenPlan ? "See what's next" : undefined} onAction={onOpenPlan} />
        )}
        {s && <StatsBody s={s} progress={p} onOpenPlan={onOpenPlan} onOpenSetup={onOpenSetup} loadBase="/api" loadKey={loadKey}
          race={<MainRaceGrade onOpen={setFitId} loadKey={loadKey} />}
          insights={<InsightsCard refresh={loadKey} max={2} onOpenPlan={onOpenPlan} onOpenSession={onOpenSession} onOpenGear={onOpenGear} onAsk={onAsk} />}
          trends={<><TrendsCard loadKey={loadKey} /><BodyLinks /></>}
          recovery={<Recovery loadKey={loadKey} />}
          challenges={<ChallengesCard imperial={imperial} loadKey={loadKey} collapsible />}
          more={<CheckinsCard />} />}
      </group.Provider>
      {fitId && <RaceFitScreen eventId={fitId} onClose={() => setFitId(null)} />}
    </Screen>
  )
}

/** The stats sections in Progress order (also the coach's view of an athlete):
 *  1 hero (level/XP, streak, week; setup as one line) 2 main race grade 3 insights (2 + Show all)
 *  3b trends (distance, easy pace, sleep) 4 recovery (one row) 5 challenges (one row) 6 fitness & form 7 "More stats" (weekly bars,
 *  badges, totals, calendar, sports, bests, check-ins). */
export function StatsBody({ s, progress, onOpenPlan, onOpenSetup, loadBase, loadKey, race, recovery, challenges, insights, trends, more: moreExtra }: {
  s: Stats; progress?: Progress | null; onOpenPlan?: () => void; onOpenSetup?: () => void
  loadBase?: string; loadKey?: number
  race?: React.ReactNode; recovery?: React.ReactNode; challenges?: React.ReactNode
  /** "What your data says" */
  insights?: React.ReactNode
  /** trend charts (distance vs goal, easy pace, sleep vs load) */
  trends?: React.ReactNode
  /** extra sections under "More stats" (the athlete's own check-ins) */
  more?: React.ReactNode
}) {
  const [period, setPeriod] = useState<Period>('week')
  const [more, setMore] = useState(false)
  return (
    <>
      {progress ? <ProgressHero p={progress} headline={s.headline} planTime={planTime(s)} onOpenPlan={onOpenPlan} onOpenSetup={onOpenSetup} />
        : <StreakHero s={s} />}
      {race}
      {insights}
      {trends}
      {recovery}
      {challenges}
      {loadBase && <LoadCard key={loadKey ?? 0} base={loadBase} />}
      <button type="button" onClick={() => setMore((m) => !m)} aria-expanded={more}
        className="flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-(--border) bg-(--bg-surface) py-2.5 text-small font-medium text-(--text-secondary) active:bg-(--bg-inset)">
        {more ? 'Fewer stats' : 'More stats'} <ChevronDown className={cn('size-5 transition-transform', more && 'rotate-180')} />
      </button>
      {more && <>
        <WeeklyBars s={s} />
        <BadgesCard s={s} />
        <TotalsCard s={s} period={period} setPeriod={setPeriod} />
        <CalendarHeat s={s} />
        {s.by_sport.length > 0 && <SportsCard s={s} />}
        {Object.keys(s.bests).length > 0 && <BestsCard s={s} />}
        {moreExtra}
      </>}
    </>
  )
}

/** "2h 10m of 4h 30m" planned time this week, when there's a plan. */
function planTime(s: Stats): string | undefined {
  const w = s.plan?.week
  return w && w.planned > 0 && w.minutes_planned > 0 ? `${fmtDuration(w.minutes_done)} of ${fmtDuration(w.minutes_planned)}` : undefined
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h2 className="font-sans px-1 text-caption font-semibold text-(--text-muted)">{children}</h2>
}

function StreakHero({ s }: { s: Stats }) {
  const st = s.streak
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-4 py-5 text-center">
      <div className="flex items-end gap-6">
        <div className="flex flex-col items-center">
          <span className={cn('flex size-16 items-center justify-center rounded-full', st.current ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-elevated) text-(--text-muted)')}>
            <Flame className="size-8" />
          </span>
          <span className="mt-2 font-display text-display-xl leading-none text-(--brand)">{st.current}</span>
          <span className="text-meta text-(--text-muted)">day streak</span>
        </div>
        <div className="flex flex-col items-center pb-1">
          <span className="font-display text-display leading-none text-(--text)">{st.weeks_current}</span>
          <span className="max-w-[90px] text-caption leading-tight text-(--text-muted)">active weeks in a row ({st.active_week}+ workouts)</span>
        </div>
      </div>
      <p className="max-w-sm text-body-lg leading-snug text-(--text)">{s.headline}</p>
      <p className="text-caption text-(--text-muted)">Best: {st.best} days · {st.weeks_best} weeks</p>
      {s.plan?.week && s.plan.week.planned > 0 && (
        <p className="text-small text-(--text-secondary)">
          This week: {s.plan.week.done} of {s.plan.week.planned} sessions{planTime(s) ? ` · ${planTime(s)}` : ''}
        </p>
      )}
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
            <span className={cn('text-caption uppercase', isToday ? 'font-semibold text-(--accent)' : 'text-(--text-muted)')}>
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

function TotalsCard({ s, period, setPeriod }: { s: Stats; period: Period; setPeriod: (p: Period) => void }) {
  const t: Totals = s.totals[period]
  const tiles: [typeof Zap, string, string][] = [
    [Zap, 'Workouts', String(t.workouts)],
    [Timer, 'Time', hours(t.hours)],
    [Mountain, 'Climbing', climb(t.climb_m, s.units)],
  ]
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <SectionLabel>Totals</SectionLabel>
        <div className="flex gap-1 rounded-lg bg-(--bg-elevated) p-0.5">
          {([['week', 'Week'], ['month', 'Month'], ['year', '12 mo']] as [Period, string][]).map(([p, l]) => (
            <button key={p} type="button" onClick={() => setPeriod(p)} aria-pressed={period === p}
              className={cn('hit-44 h-7 rounded-md px-2.5 text-caption font-medium', period === p ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)')}>{l}</button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {tiles.map(([I, label, v]) => (
          <div key={label} className="rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-3">
            <span className="flex items-center gap-1.5 text-caption text-(--text-muted)"><I className="size-4" />{label}</span>
            <span className="mt-1 block font-display text-title leading-tight text-(--text)">{v}</span>
          </div>
        ))}
      </div>
      {period === 'week' && t.vs_last_week_hours != null && (
        <p className="px-1 text-meta text-(--text-muted)">
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
        <div className="flex h-28 items-end gap-1.5">
          {s.weekly.map((w) => (
            <div key={w.start} className="flex h-full flex-1 flex-col justify-end" title={`${hours(w.hours)} · ${w.workouts} workouts`}>
              <div className="flex flex-col-reverse overflow-hidden rounded-t-[4px]" style={{ height: `${Math.max(w.hours > 0 ? 3 : 0, (w.hours / max) * 100)}%` }}>
                {sports.map((sp) => (w.by_sport[sp] ? <span key={sp} style={{ flexGrow: w.by_sport[sp], background: SPORT_COLOR[sp] }} /> : null))}
              </div>
            </div>
          ))}
        </div>
        {/* dates under every other bar (always this week), in their own row so bars stay aligned */}
        <div className="mt-1 flex gap-1.5">
          {s.weekly.map((w, i) => {
            const shown = (s.weekly.length - 1 - i) % 2 === 0
            return (
              <span key={w.start} aria-hidden={!shown}
                className={cn('flex-1 overflow-visible whitespace-nowrap text-center text-caption leading-tight', i === s.weekly.length - 1 ? 'font-semibold text-(--accent)' : 'text-(--text-muted)')}>
                {shown ? new Date(`${w.start}T12:00:00`).toLocaleDateString([], { month: 'numeric', day: 'numeric' }) : '\u00a0'}
              </span>
            )
          })}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
          {sports.map((sp) => <span key={sp} className="flex items-center gap-1 text-caption text-(--text-muted)"><span className="size-2 rounded-full" style={{ background: SPORT_COLOR[sp] }} />{SPORT_NAME[sp]}</span>)}
          <span className="ml-auto text-caption text-(--text-muted)">avg {hours(s.weekly.reduce((a, w) => a + w.hours, 0) / s.weekly.length)}/wk</span>
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
        <p className="mt-2 text-caption text-(--text-muted)">{active} active days · darker = longer</p>
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
                <span className="block text-body-lg text-(--text)">{SPORT_NAME[x.sport]}{x.favorite && <span className="ml-1.5 text-caption text-(--accent)">favorite</span>}</span>
                <span className="block text-caption text-(--text-muted)">
                  {x.workouts} workouts{x.km > 0 ? ` · ${dist(x.km, s.units, x.sport)}` : ''}{x.climb_m > 0 ? ` · ${climb(x.climb_m, s.units)} up` : ''}
                </span>
              </span>
              <span className="text-body font-medium text-(--text-secondary)">{hours(x.hours)}</span>
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
            <span className="flex items-center gap-1.5 text-caption text-(--text-muted)"><Trophy className="size-4" />{label}</span>
            <span className="mt-1 block font-display text-title leading-tight text-(--text)">{v}</span>
            {d && <span className="text-caption text-(--text-muted)">{new Date(`${d}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}</span>}
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
        <button type="button" onClick={() => setAll((a) => !a)} className="hit-44 text-caption font-medium text-(--accent)">{all ? 'Show less' : 'See all'}</button>
      </div>
      {shown.length === 0 && <p className="px-1 text-small text-(--text-muted)">Every badge earned. Legendary.</p>}
      <div className="grid grid-cols-3 gap-2">
        {shown.map((b, i) => (
          <div key={b.id} title={b.description}
            {...hopIn(i, cn('flex flex-col items-center gap-1 rounded-xl border px-2 py-3 text-center',
              b.earned ? 'border-(--accent)/40 bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)'))}>
            <span className={cn('flex size-9 items-center justify-center rounded-full', b.earned ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-elevated) text-(--text-muted)')}>
              {b.earned ? <Award className="size-6" /> : <Lock className="size-5" />}
            </span>
            <span className={cn('text-meta font-medium leading-tight', b.earned ? 'text-(--accent)' : 'text-(--text)')}>{b.title}</span>
            <span className="text-caption leading-tight text-(--text-muted)">{b.description}</span>
            {!b.earned && (
              <>
                <span className="mt-0.5 h-1 w-full overflow-hidden rounded-full bg-(--bg-elevated)">
                  <span className="block h-full rounded-full bg-(--accent)" style={{ width: `${Math.round(b.progress * 100)}%` }} />
                </span>
                <span className="text-meta text-(--text-muted)">{Math.round(b.progress * 100)}% · +100 XP</span>
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

// Recovery follows the source chosen in Me -> Connected apps -> Oura: Oura-only keeps the baseline tiles below;
// Garmin, mixed sources or "Show both" render RecoveryCompare.
import { RecoveryCompare, RecoveryRow } from './RecoveryCompare'
import { useDataSources } from '@/lib/sources'
import { ProgressSkeleton } from '@/components/ui/Skeleton'

function Recovery({ loadKey = 0 }: { loadKey?: number }) {
  const src = useDataSources()
  if (src && (src.recovery !== 'oura' || src.sleep !== 'oura' || src.show_both)) return <RecoveryCompare loadKey={loadKey} compact />
  return <OuraRecovery loadKey={loadKey} />
}

/** Oura readiness, HRV, resting HR and sleep vs your own baseline (app-only data). */
function OuraRecovery({ loadKey = 0 }: { loadKey?: number }) {
  const [r, setR] = useState<OuraRecovery | null>(null)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [open, setOpen] = useState(false)
  const track = useTrackRefresh()
  useEffect(() => {
    let live = true
    setError(false)
    track(getOura(28).then((x) => { if (live) setR(x) }, () => { if (live) setError(true) }))
    return () => { live = false }
  }, [attempt, loadKey, track])
  if (error && !r) return <ErrorState compact message="Couldn't load your Oura recovery." onRetry={() => setAttempt((n) => n + 1)} />
  if (!r?.connected || !r.days?.length) return null
  const last = r.latest ?? r.days[r.days.length - 1]!
  const b = r.baseline
  const delta = (v: number | undefined, base: number | null | undefined, unit: string, higherIsBetter: boolean) => {
    if (v == null || base == null) return null
    const d = Math.round((v - base) * 10) / 10
    const good = higherIsBetter ? d >= 0 : d <= 0
    return <span className={good ? 'text-(--accent)' : 'text-(--warning-text)'}>{d >= 0 ? '+' : ''}{d}{unit}</span>
  }
  const tiles: [string, string, React.ReactNode][] = [
    ['Oura readiness', last.readiness != null ? String(last.readiness) : '–', delta(last.readiness, b?.readiness, '', true)],
    ['HRV', last.hrv != null ? `${last.hrv} ms` : '–', delta(last.hrv, b?.hrv, ' ms', true)],
    ['Resting HR', last.resting_hr != null ? `${last.resting_hr} bpm` : '–', delta(last.resting_hr, b?.resting_hr, ' bpm', false)],
    ['Sleep', last.sleep_hours != null ? `${last.sleep_hours} h` : '–', delta(last.sleep_hours, b?.sleep_hours, ' h', true)],
  ]
  const when = new Date(`${last.date}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })
  const summary = [last.readiness != null ? `Readiness ${last.readiness}` : null,
    last.sleep_hours != null ? `Sleep ${last.sleep_hours} h` : null, last.hrv != null ? `HRV ${last.hrv} ms` : null].filter(Boolean).join(' · ')
  return (
    <section className="flex flex-col gap-2">
      <RecoveryRow source={`Oura · ${when}`} summary={summary || 'Tap for details'} open={open} onToggle={() => setOpen((o) => !o)} />
      {open && <>
      <div className="grid grid-cols-2 gap-1.5">
        {tiles.map(([label, v, d]) => (
          <div key={label} className="rounded-xl border border-(--border) bg-(--bg-surface) px-2 py-2.5 text-center">
            <span className="flex items-center justify-center gap-1 text-caption text-(--text-muted)">
              {label}{label === 'Oura readiness' && <InfoTip term="oura_readiness" />}
            </span>
            <span className="mt-0.5 block font-display text-title-sm leading-tight text-(--text)">{v}</span>
            {d && <span className="block text-meta leading-tight">{d}</span>}
          </div>
        ))}
      </div>
      <p className="px-1 text-caption text-(--text-muted)">Compared with your usual. Shown here only; Oura data is never sent to rabbt.</p>
      </>}
    </section>
  )
}
