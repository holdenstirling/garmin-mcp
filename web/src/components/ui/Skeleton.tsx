// Skeleton placeholders: grey shapes in the layout of what's loading, for the *first* load of
// a list or card (home cards, feed, events, progress). Actions keep RabbitLoader. Uses the
// `.rb-skel` shimmer (rabbit.css; still under reduced motion).
// One polite status per placeholder group names what's loading for screen readers; the
// shapes themselves are hidden from them.
import { cn } from '@/lib/utils'

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cn('rb-skel block', className)} />
}

export function SkeletonGroup({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <div role="status" aria-busy="true" className={className}>
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="contents">{children}</div>
    </div>
  )
}

/** Up next on Rabbit home: icon + headline, a line, two buttons. */
export function HomeCardSkeleton() {
  return (
    <SkeletonGroup label="Loading what's up next" className="mx-4 mt-3 shrink-0 rounded-xl border border-(--border) bg-(--bg-surface) px-3 pb-3 pt-2.5">
      <div className="flex items-center gap-2.5">
        <Skeleton className="size-8 rounded-full" />
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <Skeleton className="h-9 w-28 rounded-full" />
        <Skeleton className="h-9 w-20 rounded-full" />
      </div>
    </SkeletonGroup>
  )
}

/** Community feed: post cards (avatar, name, text lines, reactions). */
export function FeedSkeleton({ count = 3 }: { count?: number }) {
  return (
    <SkeletonGroup label="Loading the feed" className="flex flex-col gap-3">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5">
          <div className="flex items-center gap-2.5">
            <Skeleton className="size-9 rounded-full" />
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="h-2.5 w-20" />
            </div>
            <Skeleton className="h-5 w-14 rounded-full" />
          </div>
          <Skeleton className="mt-3 h-3.5 w-full" />
          <Skeleton className={cn('mt-1.5 h-3.5', i % 2 ? 'w-1/2' : 'w-4/5')} />
          <div className="mt-3 flex gap-1.5">
            {[0, 1, 2].map((k) => <Skeleton key={k} className="h-8 w-12 rounded-full" />)}
          </div>
        </div>
      ))}
    </SkeletonGroup>
  )
}

/** Events list: rows with a date tile, name and a chip. */
export function EventsSkeleton({ count = 3 }: { count?: number }) {
  return (
    <SkeletonGroup label="Loading events" className="flex flex-col gap-2.5">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3">
          <Skeleton className="size-11 rounded-lg" />
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className={cn('h-4', i % 2 ? 'w-2/3' : 'w-1/2')} />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <Skeleton className="h-6 w-10 rounded-full" />
        </div>
      ))}
    </SkeletonGroup>
  )
}

/** Progress: level hero, race grade line, two insight rows, fitness chart. */
export function ProgressSkeleton() {
  return (
    <SkeletonGroup label="Loading your progress" className="flex flex-col gap-3">
      <div className="rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
        <div className="flex items-center gap-3">
          <Skeleton className="size-12 rounded-full" />
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        </div>
        <Skeleton className="mt-3 h-2.5 w-full rounded-full" />
      </div>
      <Skeleton className="h-14 rounded-xl" />
      <Skeleton className="h-16 rounded-xl" />
      <Skeleton className="h-16 rounded-xl" />
      <Skeleton className="h-40 rounded-xl" />
    </SkeletonGroup>
  )
}

/** A simple list of rows (dashboards, settings-like lists). */
export function RowsSkeleton({ label, count = 4 }: { label: string; count?: number }) {
  return (
    <SkeletonGroup label={label} className="flex flex-col gap-2">
      {Array.from({ length: count }, (_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}
    </SkeletonGroup>
  )
}
