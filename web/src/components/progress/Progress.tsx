// Gamification UI: level + XP, setup quests and celebrations.
import type React from 'react'
import { useEffect, useRef, useState } from 'react'
import { Award, Check, ChevronRight, ListChecks, PartyPopper, Star, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { InfoTip } from '@/components/ui/InfoTip'
import { Screen } from '@/components/plan/ui'
import { Section } from '@/components/ui/section'
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
  const cls = size === 'lg' ? 'size-16 text-display' : size === 'sm' ? 'size-7 text-body' : 'size-11 text-title'
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
          className={cn('rb-ring', pct >= 1 ? 'stroke-(--brand)' : 'stroke-(--accent)')}
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)} style={{ '--rb-ring': c } as React.CSSProperties} />
      </svg>
      <span className="text-caption font-semibold text-(--text)">{pct >= 1 ? <Check className="size-4" /> : `${done}/${target}`}</span>
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
        <span className="block text-meta leading-snug text-(--text-secondary)">This week</span>
        <span className="block text-body-lg font-semibold leading-snug text-(--text)">{p.week.done} of {p.week.target} {p.week.label}</span>
        {planTime && <span className="block text-meta leading-snug text-(--text-secondary)">{planTime} planned</span>}
        {onOpenPlan && <span className="mt-0.5 block text-meta font-semibold leading-snug text-(--accent)">Open plan</span>}
      </span>
    </>
  )
  return (
    <div className="flex flex-col gap-5 rounded-2xl border border-(--border) bg-(--bg-surface) p-5">
      <div className="flex items-center gap-4">
        <LevelBadge level={p.level} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-0.5 font-display text-title-md leading-tight text-(--brand)">{p.name}<InfoTip term="level" /></p>
          <p className="text-small text-(--text-secondary)">Level {p.level} · <CountUp value={p.xp} storeKey="xp" /> XP</p>
          <XpBar p={p} className="mt-3" rabbit />
          <p className="mt-1.5 text-meta text-(--text-secondary)">
            {p.to_next.toLocaleString()} XP to level {p.level + 1}{p.next_name ? ` (${p.next_name})` : ''}
          </p>
        </div>
      </div>
      {/* Two tiles side by side; one per row on narrow screens or with larger text. */}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-3">
        <div className="relative flex items-center gap-3 rounded-xl bg-(--bg-inset) py-3 pl-3.5 pr-9">
          <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-full',
            s.at_risk ? 'bg-(--warning) text-black' : s.current ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-elevated) text-(--text-muted)')}>
            <StreakFlame streak={s.current} atRisk={s.at_risk} className="size-5" />
          </span>
          <span className="min-w-0">
            <span className="flex items-baseline gap-1">
              <CountUp value={s.current} storeKey="streak" className="font-display text-title-md leading-none text-(--text)" />
              <span className="text-small text-(--text-secondary)">day streak</span>
            </span>
            <span className="block text-meta text-(--text-secondary)">Best {s.best}</span>
            {s.at_risk && <span className="block text-meta font-semibold text-(--warning-text)">At risk today</span>}
          </span>
          <span className="absolute right-1 top-1"><InfoTip term="streak" align="end" /></span>
        </div>
        {onOpenPlan ? (
          <button type="button" onClick={onOpenPlan}
            className="flex items-center gap-3 rounded-xl bg-(--bg-inset) px-3.5 py-3 text-left active:opacity-80">{week}</button>
        ) : (
          <div className="flex items-center gap-3 rounded-xl bg-(--bg-inset) px-3.5 py-3">{week}</div>
        )}
      </div>
      <p className="text-body-lg leading-snug text-(--text)">{headline}</p>
      {!s.grace_left && <p className="-mt-3 text-small text-(--text-secondary)">This week's free rest day is used.</p>}
      {q && onOpenSetup && (
        <button type="button" onClick={onOpenSetup}
          className="-mt-1 flex min-h-14 items-center gap-3 border-t border-(--border) pt-4 text-left active:opacity-80">
          <ListChecks className="size-6 shrink-0 text-(--accent)" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-body font-semibold text-(--accent)">Setup: {p.setup.done} of {p.setup.total} done</span>
            <span className="block text-small leading-snug text-(--text-secondary)">Next: {q.title}, +{q.xp} XP</span>
          </span>
          <ChevronRight className="size-5 shrink-0 text-(--accent)" aria-hidden />
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
    <Screen title="Get set up" subtitle={`${p.setup.done} of ${p.setup.total} done. Each step earns XP.`} closing={closing} onClose={close}>
      <div className="flex flex-col gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) p-5">
        <div className="mb-1 flex items-center justify-between text-body">
          <span className="font-semibold text-(--text)">{pct === 100 ? 'All set. Nice work!' : 'Your setup'}</span>
          <span className="text-(--text-secondary)">{pct}%</span>
        </div>
        <span className="fx-bar">
          <span className="block h-2 overflow-hidden rounded-full bg-(--bg-elevated)">
            <span className="block h-full rounded-full bg-(--accent) transition-[width] duration-700" style={{ width: `${Math.max(3, pct)}%` }} />
          </span>
          <HopPrints pct={pct} value={p.setup.done} storeKey="setup" />
          <RabbitHop pct={Math.max(3, pct)} value={p.setup.done} storeKey="setup" />
        </span>
      </div>
      <Section title="The basics">
        <QuestList quests={core} onAction={(q) => { onAction(q); onClose() }} />
      </Section>
      {extra.length > 0 && (
        <Section title="Bonus" description="Optional extras, more XP.">
          <QuestList quests={extra} onAction={(q) => { onAction(q); onClose() }} />
        </Section>
      )}
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
        <div key={q.id} className="flex min-h-16 items-center gap-3.5 px-4 py-3.5">
          <span ref={q.id === firstFresh ? first : undefined}
            className={cn('flex size-7 shrink-0 items-center justify-center rounded-full border',
              q.done ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong) text-transparent',
              fresh.has(q.id) && 'rb-pop rb-check-draw')}>
            <Check className="size-5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className={cn('block text-body-lg font-medium leading-snug', q.done ? 'text-(--text-muted) line-through' : 'text-(--text)')}>{q.title}</span>
            <span className="mt-0.5 block text-small leading-snug text-(--text-secondary)">{q.hint}</span>
            <span className="block text-meta font-medium text-(--accent)">+{q.xp} XP</span>
          </span>
          {!q.done && (
            <Button variant="default" size="sm" className="shrink-0" onClick={() => onAction(q.id)}>{ACTION_LABEL[q.id]}</Button>
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
        className="celebrate relative mx-auto mt-[20dvh] flex w-[min(92vw,360px)] flex-col items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-5 py-6 text-center shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <button type="button" autoFocus className="hit-44 absolute right-3 top-3 text-(--text-muted)" aria-label="Close" onClick={finish}><X className="size-5" /></button>
        <span className="fx-leap-lane" aria-hidden="true"><span className="fx-leap"><RabbitLogo size={34} /></span></span>
        {p.level_up ? (
          <>
            <span className="flex items-center gap-1 text-(--accent)" aria-hidden="true"><PartyPopper className="size-5" /><Star className="size-6" /><PartyPopper className="size-5 -scale-x-100" /></span>
            <LevelBadge level={p.level} size="lg" />
            <p className="font-display text-title-lg leading-tight text-(--brand)">Level {p.level}!</p>
            <p className="text-body text-(--text-secondary)">You're a {p.name} now{p.level < 5 ? ' (a baby rabbit)' : ''}. Every workout counts toward the next level.</p>
          </>
        ) : (
          <p className="font-display text-title-md leading-tight text-(--brand)">New badge{p.new_badges.length > 1 ? 's' : ''}!</p>
        )}
        {p.new_badges.length > 0 && (
          <div className="flex w-full flex-col gap-2">
            {p.new_badges.slice(0, 4).map((b, i) => (
              <div key={b.id} className="flex items-center gap-3 rounded-xl border border-(--accent)/40 bg-(--accent-subtle) px-3 py-2 text-left">
                <span className="fx-medal flex size-8 shrink-0 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)"
                  style={{ animationDelay: `${250 + i * 120}ms` }}><Award className="size-5" /></span>
                <span className="min-w-0">
                  <span className="block text-body font-medium text-(--accent)">{b.title}</span>
                  <span className="block text-meta text-(--text-secondary)">{b.description} +100 XP</span>
                </span>
              </div>
            ))}
          </div>
        )}
        <Button variant="primary" className="mt-1 w-full" onClick={finish}>Keep going</Button>
      </div>
    </div>
  )
}
