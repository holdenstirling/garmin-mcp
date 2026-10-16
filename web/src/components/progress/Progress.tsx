// Gamification UI: level + XP, setup quests and celebrations.
import { useEffect, useRef, useState } from 'react'
import { Award, Check, ChevronRight, ListChecks, PartyPopper, Star, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { InfoTip } from '@/components/ui/InfoTip'
import { Screen } from '@/components/plan/ui'
import { useDialog } from '@/hooks/useDialog'
import { cn } from '@/lib/utils'
import { RabbitLogo } from '@/components/RabbitLogo'
import { HopPrints } from '@/components/fx/HopPrints'
import { StreakFlame } from '@/components/fx/StreakFlame'
import { celebrate } from '@/components/fx/motion'
import { CountUp, RabbitHop } from '@/components/anim'
import { markProgressSeen, nextQuest, type Progress, type Quest, type QuestId } from '@/lib/progress'

/** Round level badge. */
export function LevelBadge({ level, size = 'md' }: { level: number; size?: 'sm' | 'md' | 'lg' }) {
  const cls = size === 'lg' ? 'size-16 text-[1.6rem]' : size === 'sm' ? 'size-7 text-[0.8rem]' : 'size-11 text-[1.15rem]'
  return (
    <span className={cn('relative flex shrink-0 items-center justify-center rounded-full bg-(--brand) font-display leading-none text-(--on-fill) shadow-sm', cls)}
      aria-label={`Level ${level}`}>
      {level}
    </span>
  )
}

/** ``rabbit``: the rabbit mark sits at the fill's end and hops along when XP rises (needs
 *  ~12px of room above the bar). */
export function XpBar({ p, className, rabbit }: { p: Progress; className?: string; rabbit?: boolean }) {
  const pct = Math.max(2, Math.min(100, Math.round((100 * p.level_xp) / Math.max(1, p.level_span))))
  return (
    <span className={cn('fx-bar w-full', className)}>
      <span className="block h-1.5 w-full overflow-hidden rounded-full bg-(--bg-elevated)"
        role="progressbar" aria-valuemin={0} aria-valuemax={p.level_span} aria-valuenow={p.level_xp} aria-label="XP to next level">
        <span className="block h-full rounded-full bg-(--accent) transition-[width] duration-700" style={{ width: `${pct}%` }} />
      </span>
      <HopPrints pct={pct} value={p.xp} storeKey="xp" />
      {rabbit && <RabbitHop pct={pct} value={p.xp} storeKey="xp" />}
    </span>
  )
}

/** Small ring for this week's goal. */
export function WeekRing({ done, target, size = 40 }: { done: number; target: number; size?: number }) {
  const r = 15, c = 2 * Math.PI * r, pct = target ? Math.min(1, done / target) : 0
  return (
    <span className="relative flex shrink-0 items-center justify-center" style={{ width: size, height: size }}
      role="img" aria-label={`${done} of ${target} this week`}>
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="4" className="stroke-(--bg-elevated)" />
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="4" strokeLinecap="round"
          className={cn('transition-all duration-700', pct >= 1 ? 'stroke-(--brand)' : 'stroke-(--accent)')}
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)} />
      </svg>
      <span className="text-[0.6471rem] font-semibold text-(--text)">{pct >= 1 ? <Check className="size-3.5" /> : `${done}/${target}`}</span>
    </span>
  )
}

/** Big card at the top of Progress. ``planTime``: "2h 10m of 4h 30m" planned time this week. */
export function ProgressHero({ p, headline, planTime, onOpenPlan, onOpenSetup }: {
  p: Progress; headline: string; planTime?: string; onOpenPlan?: () => void
  /** setup checklist: one line here until the core setup is done (then hidden) */
  onOpenSetup?: () => void
}) {
  const s = p.streak
  const q = nextQuest(p)
  const week = (
    <>
      <WeekRing done={p.week.done} target={p.week.target} />
      <span className="min-w-0">
        <span className="block text-[0.6471rem] leading-tight text-(--text-muted)">This week</span>
        <span className="block text-[0.8235rem] font-medium leading-tight text-(--text)">{p.week.done} of {p.week.target} {p.week.label}</span>
        {planTime && <span className="block text-[0.6471rem] leading-tight text-(--text-muted)">{planTime} planned time</span>}
        {onOpenPlan && <span className="block text-[0.6471rem] font-medium leading-tight text-(--accent)">Open plan</span>}
      </span>
    </>
  )
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
      <div className="flex items-center gap-3">
        <LevelBadge level={p.level} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="font-display text-[1.25rem] leading-tight text-(--brand)">{p.name}</p>
          <p className="text-[0.6471rem] text-(--text-muted)">Level {p.level} · <CountUp value={p.xp} storeKey="xp" /> XP</p>
          <XpBar p={p} className="mt-3" rabbit />
          <p className="mt-1 text-[0.6471rem] text-(--text-muted)">
            {p.to_next.toLocaleString()} XP to level {p.level + 1}{p.next_name ? ` (${p.next_name})` : ''}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="relative flex items-center gap-2.5 rounded-xl bg-(--bg-inset) py-2.5 pl-3 pr-8">
          <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-full',
            s.at_risk ? 'bg-(--warning) text-black' : s.current ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-elevated) text-(--text-muted)')}>
            <StreakFlame streak={s.current} atRisk={s.at_risk} className="size-5" />
          </span>
          <span className="min-w-0">
            <span className="flex items-baseline gap-1">
              <CountUp value={s.current} storeKey="streak" className="font-display text-[1.3rem] leading-none text-(--text)" />
              <span className="text-[0.7059rem] text-(--text-secondary)">day streak</span>
            </span>
            <span className="block text-[0.6471rem] text-(--text-muted)">Best {s.best}</span>
            {s.at_risk && <span className="block text-[0.6471rem] font-medium text-(--warning-text)">At risk today</span>}
          </span>
          <span className="absolute right-1 top-1"><InfoTip term="streak" align="end" /></span>
        </div>
        {onOpenPlan ? (
          <button type="button" onClick={onOpenPlan}
            className="flex items-center gap-2.5 rounded-xl bg-(--bg-inset) px-3 py-2.5 text-left active:opacity-80">{week}</button>
        ) : (
          <div className="flex items-center gap-2.5 rounded-xl bg-(--bg-inset) px-3 py-2.5">{week}</div>
        )}
      </div>
      <p className="text-[0.8235rem] leading-snug text-(--text)">{headline}</p>
      {!s.grace_left && <p className="-mt-2 text-[0.6471rem] text-(--text-muted)">This week's free rest day is used.</p>}
      {q && onOpenSetup && (
        <button type="button" onClick={onOpenSetup}
          className="-mt-1 flex min-h-11 items-center gap-2 border-t border-(--border) pt-3 text-left active:opacity-80">
          <ListChecks className="size-4 shrink-0 text-(--accent)" aria-hidden />
          <span className="min-w-0 flex-1 truncate text-[0.7059rem] text-(--text-secondary)">
            <span className="font-semibold text-(--accent)">Setup {p.setup.done}/{p.setup.total}</span> · Next: {q.title}
          </span>
          <span className="shrink-0 text-[0.6471rem] font-semibold text-(--accent)">+{q.xp} XP</span>
          <ChevronRight className="size-4 shrink-0 text-(--accent)" aria-hidden />
        </button>
      )}
    </div>
  )
}

const ACTION_LABEL: Record<QuestId, string> = {
  garmin: 'Connect', sports: 'Choose', goal: 'Set goal', plan: 'Build', sync: 'Send',
  notify: 'Turn on', calendar: 'Connect', oura: 'Connect', coach: 'Invite', coach_status: 'Answer', gear: 'Add gear', friend: 'Find', interests: 'Pick',
}

/** Setup checklist: each step earns XP. */
export function SetupScreen({ p, onClose, onAction }: { p: Progress; onClose: () => void; onAction: (q: QuestId) => void }) {
  const [closing, setClosing] = useState(false)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const core = p.quests.filter((q) => !q.optional), extra = p.quests.filter((q) => q.optional)
  const pct = Math.round((100 * p.setup.done) / Math.max(1, p.setup.total))
  return (
    <Screen title="Get set up" subtitle={`${p.setup.done} of ${p.setup.total} done · earn XP for each step`} closing={closing} onClose={close}>
      <div className="flex flex-col gap-2 rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
        <div className="mb-1 flex items-center justify-between text-[0.7059rem]">
          <span className="font-medium text-(--text)">{pct === 100 ? 'All set. Nice work!' : 'Your setup'}</span>
          <span className="text-(--text-muted)">{pct}%</span>
        </div>
        <span className="fx-bar">
          <span className="block h-2 overflow-hidden rounded-full bg-(--bg-elevated)">
            <span className="block h-full rounded-full bg-(--accent) transition-[width] duration-700" style={{ width: `${Math.max(3, pct)}%` }} />
          </span>
          <HopPrints pct={pct} value={p.setup.done} storeKey="setup" />
          <RabbitHop pct={Math.max(3, pct)} value={p.setup.done} storeKey="setup" />
        </span>
      </div>
      <QuestList quests={core} onAction={(q) => { onAction(q); onClose() }} />
      {extra.length > 0 && <>
        <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Bonus</h3>
        <QuestList quests={extra} onAction={(q) => { onAction(q); onClose() }} />
      </>}
    </Screen>
  )
}

// Quests seen done (localStorage): one that's newly done draws its check and gets a small burst.
const QUESTS_SEEN = 'rabbit.fx.quests.done'
function useNewlyDone(quests: Quest[]): Set<QuestId> {
  const [fresh] = useState(() => {
    try {
      const raw = window.localStorage.getItem(QUESTS_SEEN)
      if (raw == null) return new Set<QuestId>() // first look: nothing to celebrate
      const seen = JSON.parse(raw) as QuestId[]
      return new Set(quests.filter((q) => q.done && !seen.includes(q.id)).map((q) => q.id))
    } catch { return new Set<QuestId>() }
  })
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(QUESTS_SEEN)
      const seen = raw ? (JSON.parse(raw) as QuestId[]) : []
      window.localStorage.setItem(QUESTS_SEEN, JSON.stringify([...new Set([...seen, ...quests.filter((q) => q.done).map((q) => q.id)])]))
    } catch { /* private mode */ }
  }, [quests])
  return fresh
}

function QuestList({ quests, onAction }: { quests: Quest[]; onAction: (q: QuestId) => void }) {
  const fresh = useNewlyDone(quests)
  const first = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!fresh.size) return
    const t = window.setTimeout(() => celebrate(first.current, 'quest'), 420)
    return () => window.clearTimeout(t)
  }, [fresh])
  const firstFresh = quests.find((q) => fresh.has(q.id))?.id
  return (
    <div className="divide-y divide-(--border) overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      {quests.map((q) => (
        <div key={q.id} className="flex items-center gap-3 px-4 py-3">
          <span ref={q.id === firstFresh ? first : undefined}
            className={cn('flex size-7 shrink-0 items-center justify-center rounded-full border',
              q.done ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong) text-transparent',
              fresh.has(q.id) && 'rb-pop rb-check-draw')}>
            <Check className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className={cn('block text-[0.8235rem]', q.done ? 'text-(--text-muted) line-through' : 'text-(--text)')}>{q.title}</span>
            <span className="block text-[0.6471rem] text-(--text-muted)">{q.hint} · +{q.xp} XP</span>
          </span>
          {!q.done && (
            <Button variant="default" className="h-8 shrink-0 px-3 text-[0.7059rem]" onClick={() => onAction(q.id)}>{ACTION_LABEL[q.id]}</Button>
          )}
        </div>
      ))}
    </div>
  )
}

/** Level-up and new-badge celebration, shown once. */
export function Celebration({ p, onDone }: { p: Progress; onDone: () => void }) {
  const [shown, setShown] = useState(true)
  const finish = () => {
    setShown(false)
    void markProgressSeen().catch(() => {}).finally(onDone)
  }
  const active = shown && (p.level_up || p.new_badges.length > 0)
  // A carrot burst from the card as it pops in (once per Celebration: Chat keys it by XP).
  const card = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!active) return
    const t = window.setTimeout(() => celebrate(card.current, p.level_up ? 'level' : 'badge'), 180)
    return () => window.clearTimeout(t)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps
  // Escape and the phone's Back close it like the X.
  useDialog(card, finish)
  if (!active) return null
  return (
    <div className="modal-overlay" onClick={finish}>
      <div ref={card} role="dialog" aria-modal="true" aria-label="Achievement"
        className="celebrate relative mx-auto mt-[20vh] flex w-[min(92vw,360px)] flex-col items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-5 py-6 text-center shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <button type="button" autoFocus className="hit-44 absolute right-3 top-3 text-(--text-muted)" aria-label="Close" onClick={finish}><X className="size-4" /></button>
        <span className="fx-leap-lane" aria-hidden="true"><span className="fx-leap"><RabbitLogo size={34} /></span></span>
        {p.level_up ? (
          <>
            <span className="flex items-center gap-1 text-(--accent)" aria-hidden="true"><PartyPopper className="size-4" /><Star className="size-5" /><PartyPopper className="size-4 -scale-x-100" /></span>
            <LevelBadge level={p.level} size="lg" />
            <p className="font-display text-[1.4rem] leading-tight text-(--brand)">Level {p.level}!</p>
            <p className="text-[0.8235rem] text-(--text-secondary)">You're a {p.name}. Every workout counts toward the next one.</p>
          </>
        ) : (
          <p className="font-display text-[1.3rem] leading-tight text-(--brand)">New badge{p.new_badges.length > 1 ? 's' : ''}!</p>
        )}
        {p.new_badges.length > 0 && (
          <div className="flex w-full flex-col gap-2">
            {p.new_badges.slice(0, 4).map((b, i) => (
              <div key={b.id} className="flex items-center gap-3 rounded-xl border border-(--accent)/40 bg-(--accent-subtle) px-3 py-2 text-left">
                <span className="fx-medal flex size-8 shrink-0 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)"
                  style={{ animationDelay: `${250 + i * 120}ms` }}><Award className="size-4" /></span>
                <span className="min-w-0">
                  <span className="block text-[0.8235rem] font-medium text-(--accent)">{b.title}</span>
                  <span className="block text-[0.6471rem] text-(--text-muted)">{b.description} · +100 XP</span>
                </span>
              </div>
            ))}
          </div>
        )}
        <Button variant="primary" className="mt-1 h-10 w-full" onClick={finish}>Keep going</Button>
      </div>
    </div>
  )
}
