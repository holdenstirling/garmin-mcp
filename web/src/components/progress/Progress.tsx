// Gamification UI: level + XP, the home progress strip, setup quests and celebrations.
import { useEffect, useState } from 'react'
import { Award, Check, ChevronRight, Flame, ListChecks, Sparkles, Star, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { InfoTip } from '@/components/ui/InfoTip'
import { Screen } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { markProgressSeen, nextQuest, type Progress, type Quest, type QuestId } from '@/lib/progress'

/** Round level badge. */
export function LevelBadge({ level, size = 'md' }: { level: number; size?: 'sm' | 'md' | 'lg' }) {
  const cls = size === 'lg' ? 'size-16 text-[1.6rem]' : size === 'sm' ? 'size-7 text-[0.8rem]' : 'size-11 text-[1.15rem]'
  return (
    <span className={cn('relative flex shrink-0 items-center justify-center rounded-full bg-(--brand) font-display leading-none text-white shadow-sm', cls)}
      aria-label={`Level ${level}`}>
      {level}
    </span>
  )
}

export function XpBar({ p, className }: { p: Progress; className?: string }) {
  const pct = Math.max(2, Math.min(100, Math.round((100 * p.level_xp) / Math.max(1, p.level_span))))
  return (
    <span className={cn('block h-1.5 w-full overflow-hidden rounded-full bg-(--bg-elevated)', className)}
      role="progressbar" aria-valuemin={0} aria-valuemax={p.level_span} aria-valuenow={p.level_xp} aria-label="XP to next level">
      <span className="block h-full rounded-full bg-(--accent) transition-[width] duration-700" style={{ width: `${pct}%` }} />
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

/** One-line strip on home: level + XP, streak, this week. Tapping opens Stats. */
export function HomeProgress({ p, onOpenStats, onOpenSetup }: { p: Progress; onOpenStats: () => void; onOpenSetup: () => void }) {
  const q = nextQuest(p)
  return (
    <div className="flex shrink-0 flex-col gap-2 px-4 pt-2.5">
      <button type="button" onClick={onOpenStats} aria-label={`Level ${p.level} ${p.name}. Open your progress`}
        className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2 text-left active:bg-(--bg-inset)">
        <LevelBadge level={p.level} size="sm" />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[0.7647rem] font-medium text-(--text)">{p.name}</span>
            <span className="shrink-0 text-[0.6471rem] text-(--text-muted)">{p.to_next.toLocaleString()} XP to Lv {p.level + 1}</span>
          </span>
          <XpBar p={p} className="mt-1" />
        </span>
        <span className={cn('flex shrink-0 items-center gap-0.5 text-[0.8235rem] font-semibold',
          p.streak.at_risk ? 'text-(--warning-text)' : p.streak.current ? 'text-(--accent)' : 'text-(--text-muted)')}
          aria-label={`${p.streak.current} day streak${p.streak.at_risk ? ', at risk today' : ''}`}>
          <Flame className="size-4" />{p.streak.current}
        </span>
        <WeekRing done={p.week.done} target={p.week.target} size={34} />
      </button>
      {q && (
        <button type="button" onClick={onOpenSetup}
          className="flex items-center gap-2.5 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3 py-2 text-left active:opacity-80">
          <ListChecks className="size-4 shrink-0 text-(--accent)" />
          <span className="min-w-0 flex-1 text-[0.7059rem] leading-tight text-(--accent)">
            <span className="font-semibold">Setup {p.setup.done}/{p.setup.total}</span> · Next: {q.title}
          </span>
          <span className="shrink-0 rounded-full bg-(--accent) px-1.5 py-0.5 text-[0.6471rem] font-semibold text-white">+{q.xp} XP</span>
          <ChevronRight className="size-4 shrink-0 text-(--accent)" />
        </button>
      )}
    </div>
  )
}

/** "This week: 3 of 5 sessions": the one wording for the weekly goal everywhere. */
export const weekGoalText = (p: Progress) => `This week: ${p.week.done} of ${p.week.target} ${p.week.label}`

/** Big card at the top of Progress. ``planTime``: "2h 10m of 4h 30m" planned time this week. */
export function ProgressHero({ p, headline, planTime, onOpenPlan }: {
  p: Progress; headline: string; planTime?: string; onOpenPlan?: () => void
}) {
  const s = p.streak
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
          <p className="text-[0.6471rem] text-(--text-muted)">Level {p.level} · {p.xp.toLocaleString()} XP</p>
          <XpBar p={p} className="mt-2" />
          <p className="mt-1 text-[0.6471rem] text-(--text-muted)">
            {p.to_next.toLocaleString()} XP to level {p.level + 1}{p.next_name ? ` (${p.next_name})` : ''}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="relative flex items-center gap-2.5 rounded-xl bg-(--bg-inset) py-2.5 pl-3 pr-8">
          <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-full',
            s.at_risk ? 'bg-(--warning) text-white' : s.current ? 'bg-(--accent) text-white' : 'bg-(--bg-elevated) text-(--text-muted)')}>
            <Flame className="size-5" />
          </span>
          <span className="min-w-0">
            <span className="flex items-baseline gap-1">
              <span className="font-display text-[1.3rem] leading-none text-(--text)">{s.current}</span>
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
    </div>
  )
}

const ACTION_LABEL: Record<QuestId, string> = {
  garmin: 'Connect', sports: 'Choose', goal: 'Set goal', plan: 'Build', sync: 'Send',
  notify: 'Turn on', calendar: 'Connect', oura: 'Connect', coach: 'Invite', gear: 'Add gear', friend: 'Find', interests: 'Pick',
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
        <div className="flex items-center justify-between text-[0.7059rem]">
          <span className="font-medium text-(--text)">{pct === 100 ? 'All set. Nice work!' : 'Your setup'}</span>
          <span className="text-(--text-muted)">{pct}%</span>
        </div>
        <span className="block h-2 overflow-hidden rounded-full bg-(--bg-elevated)">
          <span className="block h-full rounded-full bg-(--accent) transition-[width] duration-700" style={{ width: `${Math.max(3, pct)}%` }} />
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

function QuestList({ quests, onAction }: { quests: Quest[]; onAction: (q: QuestId) => void }) {
  return (
    <div className="divide-y divide-(--border) overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      {quests.map((q) => (
        <div key={q.id} className="flex items-center gap-3 px-4 py-3">
          <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-full border',
            q.done ? 'border-(--accent) bg-(--accent) text-white' : 'border-(--border-strong) text-transparent')}>
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
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setShown(false); void markProgressSeen().catch(() => {}).finally(onDone) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, onDone])
  if (!active) return null
  return (
    <div className="modal-overlay" onClick={finish}>
      <div role="dialog" aria-modal="true" aria-label="Achievement"
        className="celebrate relative mx-auto mt-[20vh] flex w-[min(92vw,360px)] flex-col items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-5 py-6 text-center shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <button type="button" className="hit-44 absolute right-3 top-3 text-(--text-muted)" aria-label="Close" onClick={finish}><X className="size-4" /></button>
        {p.level_up ? (
          <>
            <span className="flex items-center gap-1 text-(--accent)"><Sparkles className="size-4" /><Star className="size-5" /><Sparkles className="size-4" /></span>
            <LevelBadge level={p.level} size="lg" />
            <p className="font-display text-[1.4rem] leading-tight text-(--brand)">Level {p.level}!</p>
            <p className="text-[0.8235rem] text-(--text-secondary)">You're a {p.name}. Every workout counts toward the next one.</p>
          </>
        ) : (
          <p className="font-display text-[1.3rem] leading-tight text-(--brand)">New badge{p.new_badges.length > 1 ? 's' : ''}!</p>
        )}
        {p.new_badges.length > 0 && (
          <div className="flex w-full flex-col gap-2">
            {p.new_badges.slice(0, 4).map((b) => (
              <div key={b.id} className="flex items-center gap-3 rounded-xl border border-(--accent)/40 bg-(--accent-subtle) px-3 py-2 text-left">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-(--accent) text-white"><Award className="size-4" /></span>
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
