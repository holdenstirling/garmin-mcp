// Friendly empty state for screens that need Garmin data (Progress, workout day, ...) when
// Garmin isn't connected yet: what you'll see once it is, and one "Connect Garmin" button.
// The button asks the app to open Connect Garmin (lib/upnext.ts requestConnectGarmin).
import { Watch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { requestConnectGarmin } from '@/lib/upnext'

const COPY: Record<'progress' | 'workout' | 'today', { title: string; body: string }> = {
  progress: {
    title: 'Your progress lives here',
    body: 'Connect Garmin and your workouts, streak, fitness and personal bests fill in on their own. Nothing to log by hand.',
  },
  workout: {
    title: 'Send workouts to your watch',
    body: 'Connect Garmin to put this workout on your watch and see how it went afterwards.',
  },
  today: {
    title: 'rabbt reads your training from Garmin',
    body: "Connect it and today's advice uses your real workouts, form and recovery.",
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
  const connect = onConnect ?? requestConnectGarmin
  if (compact) {
    return (
      <div className={cn('flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5', className)}>
        <Watch className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
        <p className="min-w-0 flex-1 text-[0.7059rem] leading-snug text-(--text-secondary)">{c.body}</p>
        <Button variant="primary" className="hit-44 h-9 shrink-0 px-3 text-[0.7059rem]" onClick={connect}>Connect Garmin</Button>
      </div>
    )
  }
  return (
    <section aria-label={c.title}
      className={cn('flex flex-col items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-5 py-6 text-center', className)}>
      <span className="flex size-12 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)">
        <Watch className="size-6" aria-hidden />
      </span>
      <h2 className="font-display text-[1.1765rem] leading-tight text-(--brand)">{c.title}</h2>
      <p className="max-w-sm text-[0.7647rem] leading-snug text-(--text-secondary)">{c.body}</p>
      <Button variant="primary" className="h-11 w-full max-w-xs text-[0.8235rem]" onClick={connect}>Connect Garmin</Button>
      <p className="text-[0.6471rem] text-(--text-muted)">Takes about a minute with your Garmin Connect sign-in.</p>
    </section>
  )
}
