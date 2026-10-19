// Rabbit home "Up next" (server: upnext.py): the one card at the top of the Rabbit tab with one
// primary action. Today's planned session (Start, Send to watch) > rest day + tomorrow > build
// your plan > a group run tonight/tomorrow > set a goal. It wraps the Today card's advice, so
// that card isn't shown separately.
import { Suspense, lazy, useState } from 'react'
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
  return (
    <section aria-label="Up next" data-usage-card="upnext"
      className={cn('relative mx-4 mt-3 shrink-0 rounded-xl border bg-(--bg-surface) px-3 pb-3 pt-2.5 shadow-sm',
        up.tone === 'race' ? 'border-(--brand)/30' : rest ? 'border-(--border-strong)' : 'border-(--accent)/30', hop && 'rb-hop-in')}>
      <div className="flex items-center gap-2.5">
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full text-(--on-fill)',
          up.tone === 'race' ? 'bg-(--brand)' : rest ? 'bg-(--text-muted)' : 'bg-(--accent)')}>
          <Icon className="size-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-caption font-semibold text-(--text-muted)">Up next</span>
          {s?.id && up.kind === 'session' ? (
            <button type="button" onClick={() => openWorkout(s.id!, isoToday())} aria-label={`${headline}. Open the workout`}
              className="hit-44 block max-w-full truncate text-left text-lead font-semibold leading-tight text-(--text) underline-offset-2 hover:underline">{headline}</button>
          ) : logged != null ? (
            <button type="button" onClick={() => openActivity(logged)} aria-label={`${headline}. Open your workout`}
              className="hit-44 block max-w-full truncate text-left text-lead font-semibold leading-tight text-(--text) underline-offset-2 hover:underline">{headline}</button>
          ) : (
            <span className="block truncate text-lead font-semibold leading-tight text-(--text)">{headline}</span>
          )}
        </span>
        {week && week.length === 7 && <WeekDots days={week} />}
      </div>
      {up.detail && <p className="mt-1.5 line-clamp-2 text-small leading-snug text-(--text-secondary)">{up.detail}</p>}
      {up.fuel && (
        <p className="mt-1.5 flex items-start gap-1.5 text-meta leading-snug text-(--text-secondary)">
          <Utensils className="mt-px size-4 shrink-0 text-(--accent)" aria-hidden /><span>{up.fuel}</span>
        </p>
      )}
      {(s?.target || s?.on_watch || (rest && t) || (t && up.tone === 'done') || g?.club || signals.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {s?.target && <span className="rounded-full border border-(--border) px-2 py-0.5 text-meta font-medium text-(--text)">{s.target}</span>}
          {s?.on_watch && (
            <span className="inline-flex items-center gap-1 rounded-full border border-(--accent)/30 bg-(--accent-subtle) px-2 py-0.5 text-meta font-medium text-(--accent)">
              <Watch className="size-3.5" aria-hidden /> On your watch
            </span>
          )}
          {t && (rest || up.tone === 'done') && (
            <span className="rounded-full border border-(--border) px-2 py-0.5 text-meta text-(--text-secondary)">
              Tomorrow: {t.rest ? 'rest' : `${t.title}${t.minutes ? ` · ${fmtDuration(t.minutes)}` : ''}`}
            </span>
          )}
          {g?.club && <span className="rounded-full border border-(--border) px-2 py-0.5 text-meta text-(--text-secondary)">{g.club}{g.rsvp === 'going' ? ' · going' : ''}</span>}
          {signals.map((x) => (
            <span key={x.label}
              className={cn('inline-flex items-center gap-1 rounded-full border py-0.5 pl-2 text-meta font-medium',
                SIGNAL_TERM[x.label] ? 'pr-1' : 'pr-2',
                x.good ? 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' : 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)')}>
              {x.label} {x.value}
              {SIGNAL_TERM[x.label] && <InfoTip term={SIGNAL_TERM[x.label]!} />}
            </span>
          ))}
        </div>
      )}
      {insight && (up.kind === 'session' || up.kind === 'today') && (
        <button type="button" onClick={onOpenInsight} disabled={!onOpenInsight}
          className="hit-44 mt-1 flex items-center gap-1.5 text-left text-meta leading-snug text-(--text-secondary)">
          <Lightbulb className="size-4 shrink-0 text-(--accent)" aria-hidden />
          <span className="min-w-0 truncate"><span className="font-semibold">Insight:</span> {insight}</span>
        </button>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Button variant="primary" className="h-11 min-w-28 px-4 text-body" onClick={primary}>{up.primary.label}</Button>
        {up.secondary && (
          <Button variant="default" className="h-11 gap-1.5 px-3 text-body" loading={sending} onClick={() => void send()}>
            <Watch className="size-5" aria-hidden /> {up.secondary.label}
          </Button>
        )}
        {s?.id && up.kind === 'session' && up.tone !== 'done' && (
          <Button variant="ghost" className="h-11 gap-1.5 px-3 text-body" aria-label={`Move ${s.title} to another day`} onClick={() => { setMoved(false); setMoving(s.id) }}>
            <CalendarClock className="size-5" aria-hidden /> Move
          </Button>
        )}
        {up.extra && todayKind && (
          <button type="button" className="hit-44 px-1 text-small font-medium text-(--accent) underline-offset-2 hover:underline"
            onClick={() => onToday(todayKind)}>{up.extra.label}</button>
        )}
        {g?.url && (
          <a href={g.url} target="_blank" rel="noopener noreferrer"
            className="hit-44 px-1 text-small text-(--text-muted) underline-offset-2 hover:underline">Details</a>
        )}
      </div>
      {s?.id && up.kind === 'session' && up.tone !== 'done' && sickOff && (
        <button type="button" onClick={openSick}
          className="hit-44 mt-0.5 flex items-center gap-1 px-1 text-meta text-(--text-muted) underline-offset-2 hover:underline">
          <Thermometer className="size-4" aria-hidden /> Not feeling well? Sick mode
        </button>
      )}
      {sendMsg && <p className="mt-1.5 text-meta text-(--text-muted)" role="status">{sendMsg}</p>}
      {moving && (
        <Suspense fallback={null}>
          <MoveSessionSheet sessionId={moving} onClose={() => { setMoving(null); if (moved) onSynced() }} onMoved={() => setMoved(true)} />
        </Suspense>
      )}
    </section>
  )
}
