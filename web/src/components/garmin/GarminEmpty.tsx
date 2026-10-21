// Friendly empty state for screens that need watch data (Progress, workout day, ...) when
// nothing is connected yet: what you'll see once it is, and one button. Sending a workout to the
// watch needs Garmin ("Connect Garmin"); everything else opens "Which watch do you wear?"
// (lib/connections requestWatchPicker), so Apple Watch and Oura people aren't sent to Garmin.
import { Watch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { requestConnectGarmin } from '@/lib/upnext'
import { requestWatchPicker } from '@/lib/connections'

const COPY: Record<'progress' | 'workout' | 'today', { title: string; body: string }> = {
  progress: {
    title: 'Your progress starts with your first workout',
    body: 'Connect a watch or ring and your workouts, streak and personal bests fill in on their own.',
  },
  workout: {
    title: 'Send workouts to your watch',
    body: 'Connect Garmin to put this workout on your watch and see how it went afterwards.',
  },
  today: {
    title: 'rabbt reads your training from your watch',
    body: "Connect Garmin, Apple Watch or Oura and today's advice uses your real workouts.",
  },
}

export function GarminEmpty({ what, compact, onConnect, className }: {
  what: keyof typeof COPY
  /** one line + button, for inside another card */
  compact?: boolean
  /** default: open Connect Garmin through the app */
  onConnect?: () => void
  className?: string
}) {
  const c = COPY[what]
  const garminOnly = what === 'workout'  // only Garmin can receive a structured workout
  const connect = onConnect ?? (garminOnly ? requestConnectGarmin : requestWatchPicker)
  const label = garminOnly ? 'Connect Garmin' : 'Connect your watch'
  if (compact) {
    return (
      <div className={cn('flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5', className)}>
        <Watch className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
        <p className="min-w-0 flex-1 text-meta leading-snug text-(--text-secondary)">{c.body}</p>
        <Button variant="primary" className="hit-44 h-9 shrink-0 px-3 text-meta" onClick={connect}>{label}</Button>
      </div>
    )
  }
  return (
    <section aria-label={c.title}
      className={cn('flex flex-col items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-5 py-6 text-center', className)}>
      <span className="flex size-12 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)">
        <Watch className="size-6" aria-hidden />
      </span>
      <h2 className="font-display text-title leading-tight text-(--brand)">{c.title}</h2>
      <p className="max-w-sm text-small leading-snug text-(--text-secondary)">{c.body}</p>
      <Button variant="primary" className="h-11 w-full max-w-xs text-body" onClick={connect}>{label}</Button>
      <p className="text-caption text-(--text-muted)">Takes about a minute. Change it any time in Me, Connected apps.</p>
    </section>
  )
}
