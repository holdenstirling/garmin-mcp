// Rabbit home "Up next" (server: upnext.py): the one card at the top of the Rabbit tab with one
// primary action. Today's planned session (Start, Send to watch) > rest day + tomorrow > build
// your plan > a group run tonight/tomorrow > set a goal. It wraps the Today card's advice, so
// that card isn't shown separately.
import { Suspense, lazy, useState, type ReactNode } from 'react'
import { CalendarClock, Check, Flag, Lightbulb, Moon, Route, Target, Thermometer, Users, Watch, Waves, Zap, Utensils } from 'lucide-react'
import { useSick } from '@/components/plan/SickHost'
import { Button } from '@/components/ui/button'
import { InfoTip } from '@/components/ui/InfoTip'
import { WeekDots } from '@/components/week/WeekStrip'
import type { WeekDay } from '@/lib/api'
import { fmtDuration } from '@/lib/format'
import type { Term } from '@/lib/glossary'
import type { TodayActionKind } from '@/lib/live'
import { syncGarmin } from '@/lib/plan'
import type { UpNext } from '@/lib/upnext'
import { cn } from '@/lib/utils'
import { openSick } from '@/lib/sick'
import { openWorkout } from '@/lib/workoutnav'
import { openActivity } from '@/lib/activitynav'

// "Move" today's session to another day (loaded on first use).
const MoveSessionSheet = lazy(() => import('@/components/plan/MoveSheet').then((m) => ({ default: m.MoveSessionSheet })))

const SEEN = 'rabbit.upnext.seen'
const isoToday = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
const SIGNAL_TERM: Record<string, Term> = {
  Form: 'form', Readiness: 'readiness', 'Oura readiness': 'oura_readiness', 'Garmin readiness': 'garmin_readiness', Streak: 'streak',
}
const TODAY_KINDS: readonly string[] = ['open_session', 'review_adjust', 'open_racepack', 'build_plan', 'log_rest', 'ask']

function iconFor(up: UpNext): typeof Zap {
  if (up.kind === 'group_run') return Users
  if (up.kind === 'set_goal') return Target
  if (up.kind === 'build_plan') return Route
  if (up.kind === 'rest' || up.tone === 'rest') return Moon
  return up.tone === 'race' ? Flag : up.tone === 'done' ? Check : up.tone === 'easy' ? Waves : up.tone === 'plan' ? Route : Zap
}

function firstShowToday(): boolean {
  const day = new Date().toDateString()
  try {
    if (window.localStorage.getItem(SEEN) === day) return false
    window.localStorage.setItem(SEEN, day)
  } catch { /* storage unavailable: no entrance animation */ return false }
  return true
}

export function UpNextCard({ up, week, insight, onOpenInsight, onStart, onToday, onPlan, onSetup, onClubs, onAsk, onSynced, hideStreak, hideReadiness }: {
  up: UpNext
  /** this plan week's days: dots next to the headline */
  week?: WeekDay[] | null
  /** top "do this" insight from Progress (one line, optional) */
  insight?: string | null; onOpenInsight?: () => void
  onStart: (sessionId: string) => void
  onToday: (kind: TodayActionKind) => void
  onPlan: () => void
  /** plan setup (goal + plan) */
  onSetup: () => void
  onClubs: (clubId?: string) => void
  onAsk: (text: string) => void
  /** after Send to watch: reload the card */
  onSynced: () => void
  hideStreak?: boolean
  /** Home's ReadinessSnapshot shows readiness and form: don't repeat them here */
  hideReadiness?: boolean
}) {
  const [hop] = useState(firstShowToday)
  const [sending, setSending] = useState(false)
  const [sendMsg, setSendMsg] = useState<string | null>(null)
  const [moving, setMoving] = useState<string | null>(null)  // session id; reload the card when the sheet closes
  const [moved, setMoved] = useState(false)
  const Icon = iconFor(up)
  const rest = up.kind === 'rest' || up.tone === 'rest'
  // One readiness signal at most, and only before today's session (details live in Progress).
  const signals = up.kind === 'session' && up.tone !== 'done'
    ? up.signals.filter((s) => !(hideStreak && s.label === 'Streak') && !(hideReadiness && s.label !== 'Streak')).slice(0, 1) : []
  const todayKind = up.today?.action.kind

  const logged = up.tone === 'done' ? up.today?.activity_id : undefined
  const primary = () => {
    const k = up.primary.kind
    if (logged != null && (k === 'ask' || (k === 'today' && todayKind === 'ask'))) { openActivity(logged); return } // "How did it go?": its page
    if (k === 'start' && up.session?.id) onStart(up.session.id)
    else if (k === 'today') { if (todayKind) onToday(todayKind); else onAsk('About today: ') }
    else if (k === 'open_plan') onPlan()
    else if (k === 'build_plan' || k === 'set_goal') onSetup()
    else if (k === 'group') onClubs(up.group?.club_id ?? undefined)
    else if (TODAY_KINDS.includes(k)) onToday(k as TodayActionKind)
  }
  const send = async () => {
    setSending(true); setSendMsg(null)
    try { await syncGarmin(7); setSendMsg('Sent. Sync your watch to pick it up.'); onSynced() }
    catch (e) { setSendMsg((e as Error).message) }
    finally { setSending(false) }
  }
  const s = up.session
  const sick = useSick()
  const sickOff = !!sick && !sick.active && !sick.returning
  const t = up.tomorrow
  const g = up.group
  const headline = s && up.kind === 'session' ? [s.title, fmtDuration(s.minutes)].filter(Boolean).join(' · ') : up.headline
  // Two chips at most (what to aim for, and whether it's on the watch); everything else is a line.
  const chips: { key: string; node: ReactNode }[] = []
  if (s?.target) chips.push({ key: 'target', node: <span className="rounded-full border border-(--border) px-3 py-1 text-meta font-medium text-(--text)">{s.target}</span> })
  if (s?.on_watch) {
    chips.push({ key: 'watch', node: (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-(--accent)/30 bg-(--accent-subtle) px-3 py-1 text-meta font-medium text-(--accent)">
        <Watch className="size-4" aria-hidden /> On your watch
      </span>
    ) })
  }
  for (const x of signals) {
    chips.push({ key: x.label, node: (
      <span className={cn('inline-flex items-center gap-1 rounded-full border py-1 pl-3 text-meta font-medium',
        SIGNAL_TERM[x.label] ? 'pr-1.5' : 'pr-3',
        x.good ? 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' : 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)')}>
        {x.label} {x.value}
        {SIGNAL_TERM[x.label] && <InfoTip term={SIGNAL_TERM[x.label]!} />}
      </span>
    ) })
  }
  const tomorrowLine = t && (rest || up.tone === 'done')
    ? `Tomorrow: ${t.rest ? 'rest' : `${t.title}${t.minutes ? `, ${fmtDuration(t.minutes)}` : ''}`}` : null
  const clubLine = g?.club ? `${g.club}${g.rsvp === 'going' ? ' · you\'re going' : ''}` : null
  const titleCls = 'block text-left text-title-sm font-semibold leading-snug text-(--text)'
  const quiet = 'hit-44 inline-flex min-h-11 items-center gap-1.5 text-body font-medium text-(--accent) underline-offset-2 hover:underline disabled:opacity-50'
  const canMove = !!s?.id && up.kind === 'session' && up.tone !== 'done'
  return (
    <section aria-label="Up next" data-usage-card="upnext"
      className={cn('relative shrink-0 rounded-2xl border bg-(--bg-surface) p-5 shadow-sm',
        up.tone === 'race' ? 'border-(--brand)/30' : rest ? 'border-(--border-strong)' : 'border-(--accent)/30', hop && 'rb-hop-in')}>
      <div className="flex items-start gap-3.5">
        <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-full text-(--on-fill)',
          up.tone === 'race' ? 'bg-(--brand)' : rest ? 'bg-(--text-muted)' : 'bg-(--accent)')}>
          <Icon className="size-6" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-meta font-medium text-(--text-muted)">Up next</span>
          {s?.id && up.kind === 'session' ? (
            <button type="button" onClick={() => openWorkout(s.id!, isoToday())} aria-label={`${headline}. Open the workout`}
              className={cn(titleCls, 'hit-44 underline-offset-2 hover:underline')}>{headline}</button>
          ) : logged != null ? (
            <button type="button" onClick={() => openActivity(logged)} aria-label={`${headline}. Open your workout`}
              className={cn(titleCls, 'hit-44 underline-offset-2 hover:underline')}>{headline}</button>
          ) : (
            <span className={titleCls}>{headline}</span>
          )}
        </span>
        {week && week.length === 7 && <WeekDots days={week} className="mt-1" />}
      </div>
      {up.detail && <p className="mt-3 text-body leading-normal text-(--text-secondary)">{up.detail}</p>}
      {up.fuel && (
        <p className="mt-3 flex items-start gap-2 text-small leading-snug text-(--text-secondary)">
          <Utensils className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden /><span>{up.fuel}</span>
        </p>
      )}
      {chips.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">{chips.slice(0, 2).map((c) => <span key={c.key} className="contents">{c.node}</span>)}</div>
      )}
      {(tomorrowLine || clubLine) && (
        <p className="mt-3 text-small leading-snug text-(--text-secondary)">
          {[tomorrowLine, clubLine].filter(Boolean).join('. ')}
        </p>
      )}
      {insight && (up.kind === 'session' || up.kind === 'today') && (
        <button type="button" onClick={onOpenInsight} disabled={!onOpenInsight}
          className="mt-3 flex min-h-11 items-start gap-2 text-left text-small leading-snug text-(--text-secondary)">
          <Lightbulb className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden />
          <span className="min-w-0"><span className="font-semibold">Insight:</span> {insight}</span>
        </button>
      )}
      <Button variant="primary" className="mt-4 w-full text-body-lg" onClick={primary}>{up.primary.label}</Button>
      {(up.secondary || canMove || (up.extra && todayKind) || g?.url) && (
        <div className="mt-2 flex flex-wrap items-center justify-center gap-x-6 gap-y-1">
          {up.secondary && (
            <button type="button" className={quiet} disabled={sending} aria-busy={sending || undefined} onClick={() => void send()}>
              <Watch className="size-5" aria-hidden /> {sending ? 'Sending…' : up.secondary.label}
            </button>
          )}
          {canMove && (
            <button type="button" className={quiet} aria-label={`Move ${s!.title} to another day`} onClick={() => { setMoved(false); setMoving(s!.id) }}>
              <CalendarClock className="size-5" aria-hidden /> Move
            </button>
          )}
          {up.extra && todayKind && (
            <button type="button" className={quiet} onClick={() => onToday(todayKind)}>{up.extra.label}</button>
          )}
          {g?.url && (
            <a href={g.url} target="_blank" rel="noopener noreferrer" className={quiet}>Details</a>
          )}
        </div>
      )}
      {canMove && sickOff && (
        <button type="button" onClick={openSick}
          className="mx-auto mt-1 flex min-h-11 items-center gap-1.5 text-small text-(--text-muted) underline-offset-2 hover:underline">
          <Thermometer className="size-4" aria-hidden /> Not feeling well? Sick mode
        </button>
      )}
      {sendMsg && <p className="mt-2 text-center text-small text-(--text-muted)" role="status">{sendMsg}</p>}
      {moving && (
        <Suspense fallback={null}>
          <MoveSessionSheet sessionId={moving} onClose={() => { setMoving(null); if (moved) onSynced() }} onMoved={() => setMoved(true)} />
        </Suspense>
      )}
    </section>
  )
}

/** Up next while it loads: the same shape and size as the card, so Home doesn't jump. */
export function UpNextSkeleton() {
  return (
    <div role="status" aria-label="Loading what's up next" className="shrink-0 rounded-2xl border border-(--border) bg-(--bg-surface) p-5">
      <div className="flex items-start gap-3.5" aria-hidden>
        <span className="skeleton size-11 rounded-full" />
        <span className="flex min-w-0 flex-1 flex-col gap-2 pt-0.5">
          <span className="skeleton h-3.5 w-16" />
          <span className="skeleton h-5 w-3/4" />
        </span>
      </div>
      <span className="skeleton mt-4 block h-4 w-full" aria-hidden />
      <span className="skeleton mt-2 block h-4 w-2/3" aria-hidden />
      <span className="skeleton mt-4 block h-12 w-full rounded-(--radius)" aria-hidden />
    </div>
  )
}
