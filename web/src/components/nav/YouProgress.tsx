// The top of the You tab: progress at a glance (this week, streak, level) and one way into the
// full Progress page (fitness trend, stats, weekly recap). Me's rows follow underneath.
import type { ReactNode } from 'react'
import { ChevronRight, Flame, TrendingUp } from 'lucide-react'
import { LevelBadge } from '@/components/progress/Progress'
import type { Progress } from '@/lib/progress'

export function YouProgress({ progress, onOpen, recap }: {
  progress: Progress | null
  /** the full Progress page */
  onOpen: () => void
  /** the month recap entry, when there is one (not in the first week) */
  recap?: ReactNode
}) {
  const w = progress?.week
  const pct = w && w.target > 0 ? Math.min(100, Math.round((w.done / w.target) * 100)) : 0
  return (
    <div className="flex flex-col gap-3">
      <button type="button" onClick={onOpen} aria-label="Open Progress"
        className="flex flex-col gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) p-4 text-left shadow-sm active:bg-(--bg-inset)">
        <span className="flex items-center gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
            <TrendingUp className="size-5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-body-lg font-semibold text-(--text)">Your progress</span>
            <span className="block text-meta text-(--text-secondary)">
              {w ? `${w.label}: ${w.done} of ${w.target}` : 'How your training is going'}
            </span>
          </span>
          <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
        </span>
        {w && w.target > 0 && (
          <span className="block h-2 overflow-hidden rounded-full bg-(--bg-inset)" aria-hidden>
            <span className="block h-full rounded-full bg-(--accent)" style={{ width: `${pct}%` }} />
          </span>
        )}
        {progress && (
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1 text-small text-(--text-secondary)">
            <span className="flex items-center gap-1.5"><LevelBadge level={progress.level} size="sm" /> Level {progress.level}</span>
            {progress.streak.current > 0 && (
              <span className="flex items-center gap-1.5"><Flame className="size-4 text-(--accent)" aria-hidden /> {progress.streak.current}-day streak</span>
            )}
            <span className="ml-auto font-semibold text-(--accent)">See all progress</span>
          </span>
        )}
      </button>
      {recap}
    </div>
  )
}
